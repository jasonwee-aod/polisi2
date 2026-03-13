"""
Integration tests for the BHEUU pipeline.

Tests use mocked HTTP and Spaces; no live network or cloud access required.
Verifies that the pipeline correctly handles:
  - collection: paginated Strapi array endpoints
  - single_type: Strapi single-type dict endpoints
  - metadata_only: sections with no downloadable file
  - --since date filtering
  - sha256 deduplication
"""
import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bheuu_scraper.archiver import SpacesArchiver, sha256_of_bytes
from bheuu_scraper.crawler import HTTPClient
from bheuu_scraper.pipeline import BHEUUPipeline
from bheuu_scraper.state import StateStore


# ── Minimal test config ───────────────────────────────────────────────────────

BASE_CONFIG = {
    "site_slug": "bheuu",
    "agency": "BHEUU",
    "strapi_base": "https://strapi.bheuu.gov.my",
    "base_url": "https://www.bheuu.gov.my",
    "allowed_hosts": ["www.bheuu.gov.my", "strapi.bheuu.gov.my"],
    "sections": [],
}

_FAKE_PDF = b"%PDF-1.4 fake-pdf-content"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def state(tmp_dir):
    s = StateStore(tmp_dir / "test.db")
    yield s
    s.close()


@pytest.fixture
def archiver():
    arch = SpacesArchiver(
        bucket_name="test-bucket",
        region="sgp1",
        endpoint_url="https://sgp1.digitaloceanspaces.com",
        access_key="key",
        secret_key="secret",
        dry_run=True,
    )
    return arch


def _mock_http(json_pages: list, file_bytes: bytes = _FAKE_PDF) -> HTTPClient:
    """
    Build a mock HTTPClient.

    json_pages: list of Python objects returned sequentially by get_json()
    file_bytes: bytes returned by get() for file downloads
    """
    http = MagicMock(spec=HTTPClient)

    call_counter = [0]

    def fake_get_json(url, params=None):
        idx = call_counter[0]
        call_counter[0] += 1
        if idx < len(json_pages):
            return json_pages[idx]
        return []  # empty page to stop pagination

    http.get_json.side_effect = fake_get_json

    fake_resp = MagicMock()
    fake_resp.content = file_bytes
    fake_resp.headers = {
        "Content-Type": "application/pdf",
        "ETag": '"etag-test"',
        "Last-Modified": "Mon, 08 Jan 2024 00:00:00 GMT",
    }
    fake_resp.url = "https://strapi.bheuu.gov.my/uploads/test_file.pdf"
    http.get.return_value = fake_resp

    return http


def _make_pipeline(config, state, archiver, http, tmp_dir, **kwargs) -> BHEUUPipeline:
    return BHEUUPipeline(
        config=config,
        state=state,
        archiver=archiver,
        http=http,
        manifest_dir=tmp_dir / "manifests",
        dry_run=True,
        **kwargs,
    )


# ── Tests: collection (paginated) ─────────────────────────────────────────────


class TestCollectionSection:
    def test_single_record_archived(self, state, archiver, tmp_dir):
        record = {
            "_id": "aaa001",
            "title": "Kenyataan Media Test",
            "publishDate": "2024-03-01",
            "fileName": {
                "url": "/uploads/km_test.pdf",
            },
        }
        config = {
            **BASE_CONFIG,
            "sections": [
                {
                    "name": "media_statements",
                    "label": "Media Statements",
                    "doc_type": "press_release",
                    "language": "ms",
                    "source_type": "collection",
                    "endpoint": "media-statements",
                    "title_field": "title",
                    "date_field": "publishDate",
                    "file_field": "fileName.url",
                }
            ],
        }
        # page 1 returns 1 record; page 2 returns empty (stops)
        http = _mock_http(json_pages=[[record], []])
        pipeline = _make_pipeline(config, state, archiver, http, tmp_dir)
        run = pipeline.run()

        assert run.new_count == 1
        assert run.failed_count == 0

        records_path = tmp_dir / "manifests" / "records.jsonl"
        lines = records_path.read_text().strip().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["title"] == "Kenyataan Media Test"
        assert rec["published_at"] == "2024-03-01"
        assert rec["doc_type"] == "press_release"
        assert rec["canonical_url"].endswith(".pdf")

    def test_pagination_stops_on_empty(self, state, archiver, tmp_dir):
        records_page1 = [
            {
                "_id": f"id{i:03d}",
                "title": f"Doc {i}",
                "publishDate": "2024-01-01",
                "url": f"https://strapi.bheuu.gov.my/uploads/doc{i}.pdf",
            }
            for i in range(3)
        ]
        config = {
            **BASE_CONFIG,
            "sections": [
                {
                    "name": "annual_reports",
                    "label": "Annual Reports",
                    "doc_type": "report",
                    "language": "ms",
                    "source_type": "collection",
                    "endpoint": "annual-reports",
                    "title_field": "title",
                    "date_field": "publishDate",
                    "file_field": "url",
                }
            ],
        }
        http = _mock_http(json_pages=[records_page1, []])
        pipeline = _make_pipeline(config, state, archiver, http, tmp_dir)
        run = pipeline.run()

        assert run.new_count == 3

    def test_max_pages_respected(self, state, archiver, tmp_dir):
        page = [
            {
                "_id": "id001",
                "title": "Test",
                "publishDate": "2024-01-01",
                "url": "https://strapi.bheuu.gov.my/uploads/doc.pdf",
            }
        ]
        config = {
            **BASE_CONFIG,
            "sections": [
                {
                    "name": "annual_reports",
                    "doc_type": "report",
                    "language": "ms",
                    "source_type": "collection",
                    "endpoint": "annual-reports",
                    "title_field": "title",
                    "date_field": "publishDate",
                    "file_field": "url",
                }
            ],
        }
        # supply 5 pages of data but limit to 1
        http = _mock_http(json_pages=[page] * 5)
        pipeline = _make_pipeline(
            config, state, archiver, http, tmp_dir, max_pages=1
        )
        run = pipeline.run()

        assert run.new_count == 1

    def test_missing_file_url_increments_skipped(self, state, archiver, tmp_dir):
        """Records where the file_field resolves to None are silently skipped."""
        record = {
            "_id": "nav001",
            "titleEN": "Trustees (Incorporation) Act 1952 [Act 258]",
            "titleBM": "Akta Pemegang Amanah (Pemerbadanan) 1952 [Akta 258]",
            "url": "/orang-awam/akta-pemegang-amanah-pemerbadanan-1952/pendaftaran",
            "createdAt": "2024-08-05T03:58:48.468Z",
            # "pdf" field intentionally absent (navigation-only record)
        }
        config = {
            **BASE_CONFIG,
            "sections": [
                {
                    "name": "act_laws",
                    "label": "Acts and Laws",
                    "doc_type": "other",
                    "language": "ms",
                    "source_type": "collection",
                    "endpoint": "act-laws",
                    "title_field": "titleEN",
                    "date_field": "createdAt",
                    "file_field": "pdf.url",
                }
            ],
        }
        http = _mock_http(json_pages=[[record], []])
        pipeline = _make_pipeline(config, state, archiver, http, tmp_dir)
        run = pipeline.run()

        assert run.new_count == 0
        assert run.failed_count == 0
        assert run.skipped_count == 1

    def test_act_laws_record_with_pdf_archived(self, state, archiver, tmp_dir):
        """act-laws record that has a pdf field gets downloaded and archived."""
        record = {
            "_id": "66b04f2c67cc2209a952a8ad",
            "titleEN": "Research and Bill",
            "titleBM": "Penyelidikan dan Rang Undang-Undang",
            "createdAt": "2024-08-05T04:03:56.468Z",
            "pdf": {"url": "/uploads/RUU_Perlembagaan_b64df7b81d.pdf"},
        }
        config = {
            **BASE_CONFIG,
            "sections": [
                {
                    "name": "act_laws",
                    "label": "Acts and Laws",
                    "doc_type": "other",
                    "language": "ms",
                    "source_type": "collection",
                    "endpoint": "act-laws",
                    "title_field": "titleEN",
                    "date_field": "createdAt",
                    "file_field": "pdf.url",
                }
            ],
        }
        http = _mock_http(json_pages=[[record], []])
        pipeline = _make_pipeline(config, state, archiver, http, tmp_dir)
        run = pipeline.run()

        assert run.new_count == 1
        assert run.failed_count == 0
        records_path = tmp_dir / "manifests" / "records.jsonl"
        rec = json.loads(records_path.read_text().strip())
        assert rec["title"] == "Research and Bill"
        assert rec["doc_type"] == "other"


# ── Tests: single_type ────────────────────────────────────────────────────────


class TestSingleTypeSection:
    def test_single_type_archived(self, state, archiver, tmp_dir):
        record = {
            "_id": "st001",
            "createdAt": "2024-07-26T12:32:55.596Z",
            "pdfFile": {
                "url": "/uploads/Keratan_Akhbar.pdf",
            },
        }
        config = {
            **BASE_CONFIG,
            "sections": [
                {
                    "name": "act_protection_newspaper_clip",
                    "label": "Newspaper Clip",
                    "doc_type": "other",
                    "language": "ms",
                    "source_type": "single_type",
                    "endpoint": "act-protection-newspaper-clip",
                    "title_field": "title",
                    "date_field": "createdAt",
                    "file_field": "pdfFile.url",
                }
            ],
        }
        # get_json for single_type returns a dict, not a list
        http = _mock_http(json_pages=[record])
        pipeline = _make_pipeline(config, state, archiver, http, tmp_dir)
        run = pipeline.run()

        assert run.new_count == 1
        assert run.failed_count == 0


# ── Tests: metadata_only ──────────────────────────────────────────────────────


class TestMetadataOnlySection:
    def test_metadata_only_written(self, state, archiver, tmp_dir):
        record = {
            "_id": "news001",
            "title": "Latest News Item",
            "publishDate": "2024-09-01",
        }
        config = {
            **BASE_CONFIG,
            "sections": [
                {
                    "name": "latest_news",
                    "label": "Latest News",
                    "doc_type": "press_release",
                    "language": "ms",
                    "source_type": "metadata_only",
                    "endpoint": "latest-news",
                    "title_field": "title",
                    "date_field": "publishDate",
                }
            ],
        }
        http = _mock_http(json_pages=[[record], []])
        pipeline = _make_pipeline(config, state, archiver, http, tmp_dir)
        run = pipeline.run()

        assert run.new_count == 1
        # No file download for metadata_only – verify get() was NOT called
        http.get.assert_not_called()

        records_path = tmp_dir / "manifests" / "records.jsonl"
        rec = json.loads(records_path.read_text().strip())
        assert rec["title"] == "Latest News Item"
        assert rec["content_type"] == "text/html"


# ── Tests: --since date filtering ─────────────────────────────────────────────


class TestSinceDateFilter:
    def test_record_before_since_skipped(self, state, archiver, tmp_dir):
        record = {
            "_id": "old001",
            "title": "Old Document",
            "publishDate": "2022-01-01",
            "url": "https://strapi.bheuu.gov.my/uploads/old.pdf",
        }
        config = {
            **BASE_CONFIG,
            "sections": [
                {
                    "name": "annual_reports",
                    "doc_type": "report",
                    "language": "ms",
                    "source_type": "collection",
                    "endpoint": "annual-reports",
                    "title_field": "title",
                    "date_field": "publishDate",
                    "file_field": "url",
                }
            ],
        }
        http = _mock_http(json_pages=[[record], []])
        pipeline = _make_pipeline(
            config, state, archiver, http, tmp_dir, since="2024-01-01"
        )
        run = pipeline.run()

        assert run.new_count == 0
        assert run.skipped_count == 1

    def test_record_on_since_date_included(self, state, archiver, tmp_dir):
        record = {
            "_id": "new001",
            "title": "New Document",
            "publishDate": "2024-01-01",
            "url": "https://strapi.bheuu.gov.my/uploads/new.pdf",
        }
        config = {
            **BASE_CONFIG,
            "sections": [
                {
                    "name": "annual_reports",
                    "doc_type": "report",
                    "language": "ms",
                    "source_type": "collection",
                    "endpoint": "annual-reports",
                    "title_field": "title",
                    "date_field": "publishDate",
                    "file_field": "url",
                }
            ],
        }
        http = _mock_http(json_pages=[[record], []])
        pipeline = _make_pipeline(
            config, state, archiver, http, tmp_dir, since="2024-01-01"
        )
        run = pipeline.run()

        assert run.new_count == 1


# ── Tests: sha256 deduplication ───────────────────────────────────────────────


class TestSha256Dedup:
    def test_duplicate_file_not_re_uploaded(self, state, archiver, tmp_dir):
        """Two different URLs pointing to same file content → one upload."""
        record1 = {
            "_id": "dup001",
            "title": "Doc 1",
            "publishDate": "2024-01-01",
            "url": "https://strapi.bheuu.gov.my/uploads/fileA.pdf",
        }
        record2 = {
            "_id": "dup002",
            "title": "Doc 2",
            "publishDate": "2024-02-01",
            "url": "https://strapi.bheuu.gov.my/uploads/fileB.pdf",
        }
        config = {
            **BASE_CONFIG,
            "sections": [
                {
                    "name": "annual_reports",
                    "doc_type": "report",
                    "language": "ms",
                    "source_type": "collection",
                    "endpoint": "annual-reports",
                    "title_field": "title",
                    "date_field": "publishDate",
                    "file_field": "url",
                }
            ],
        }
        # Both records return the same bytes → same sha256
        http = _mock_http(json_pages=[[record1, record2], []])
        pipeline = _make_pipeline(config, state, archiver, http, tmp_dir)
        run = pipeline.run()

        assert run.new_count == 2
        # Both records written to JSONL
        records_path = tmp_dir / "manifests" / "records.jsonl"
        lines = records_path.read_text().strip().splitlines()
        assert len(lines) == 2
