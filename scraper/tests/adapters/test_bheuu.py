"""Tests for the BHEUU Strapi v3 API adapter.

Covers:
  - Helper functions: _parse_strapi_date, _get_nested, _resolve_file_url
  - Discovery: collection, single_type, metadata_only source types
  - Pagination and max_pages limiting
  - since date filtering
  - Empty and malformed API responses
  - fetch_and_extract()
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from polisi_scraper.adapters.bheuu import (
    STRAPI_BASE,
    BheuuAdapter,
    _get_nested,
    _parse_strapi_date,
    _resolve_file_url,
)
from polisi_scraper.adapters.base import DiscoveredItem, DocumentCandidate, HTTPClient

FIXTURES = Path(__file__).parent.parent / "fixtures" / "bheuu"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _mock_http(json_pages: list[list | dict]) -> MagicMock:
    """Build a mock HTTPClient that returns paginated JSON responses.

    Each call to http.get() returns a MagicMock response whose .json()
    returns the next item from json_pages.
    """
    http = MagicMock(spec=HTTPClient)
    call_counter = [0]

    def fake_get(url, **kwargs):
        idx = call_counter[0]
        call_counter[0] += 1
        resp = MagicMock()
        if idx < len(json_pages):
            resp.json.return_value = json_pages[idx]
        else:
            resp.json.return_value = []
        return resp

    http.get.side_effect = fake_get
    return http


def _make_adapter(config: dict, http: MagicMock | None = None) -> BheuuAdapter:
    adapter = BheuuAdapter.__new__(BheuuAdapter)
    adapter.config = config
    adapter.http = http or _mock_http([])
    adapter.state = None
    adapter.archiver = None
    adapter.browser_pool = None
    return adapter


# ── Section configs for reuse ─────────────────────────────────────────────


_COLLECTION_SECTION = {
    "endpoint": "media-statements",
    "source_type": "collection",
    "doc_type": "press_release",
    "language": "ms",
    "title_field": "title",
    "date_field": "publishDate",
    "file_field": "fileName.url",
}

_SINGLE_TYPE_SECTION = {
    "endpoint": "act-protection-newspaper-clip",
    "source_type": "single_type",
    "doc_type": "other",
    "language": "ms",
    "title_field": "title",
    "date_field": "createdAt",
    "file_field": "pdfFile.url",
}

_METADATA_ONLY_SECTION = {
    "endpoint": "latest-news",
    "source_type": "metadata_only",
    "doc_type": "press_release",
    "language": "ms",
    "title_field": "title",
    "date_field": "publishDate",
}


# ═══════════════════════════════════════════════════════════════════════════
# _parse_strapi_date
# ═══════════════════════════════════════════════════════════════════════════


class TestParseStrapiDate:
    def test_iso_date_passthrough(self):
        assert _parse_strapi_date("2024-01-08") == "2024-01-08"

    def test_iso_datetime_utc(self):
        assert _parse_strapi_date("2024-08-14T02:22:22.887Z") == "2024-08-14"

    def test_iso_datetime_with_offset(self):
        assert _parse_strapi_date("2025-03-01T09:00:00+08:00") == "2025-03-01"

    def test_published_at_format(self):
        assert _parse_strapi_date("2024-10-08T07:52:58.284Z") == "2024-10-08"

    def test_year_only_string(self):
        assert _parse_strapi_date("2010") == "2010-01-01"

    def test_year_2024(self):
        assert _parse_strapi_date("2024") == "2024-01-01"

    def test_empty_string(self):
        assert _parse_strapi_date("") == ""

    def test_none(self):
        assert _parse_strapi_date(None) == ""

    def test_whitespace_only(self):
        assert _parse_strapi_date("   ") == ""

    def test_invalid_string(self):
        assert _parse_strapi_date("not-a-date") == ""

    def test_start_date(self):
        assert _parse_strapi_date("2024-10-24") == "2024-10-24"

    def test_result_date(self):
        assert _parse_strapi_date("2025-01-06") == "2025-01-06"

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2024-01-08", "2024-01-08"),
            ("2024-08-14T02:22:22.887Z", "2024-08-14"),
            ("2010", "2010-01-01"),
            ("", ""),
            (None, ""),
            ("   ", ""),
        ],
    )
    def test_parametrized(self, value, expected):
        assert _parse_strapi_date(value) == expected


# ═══════════════════════════════════════════════════════════════════════════
# _get_nested
# ═══════════════════════════════════════════════════════════════════════════


class TestGetNested:
    def test_single_key(self):
        assert _get_nested({"url": "https://example.com/file.pdf"}, "url") == \
            "https://example.com/file.pdf"

    def test_dotted_key(self):
        data = {"fileName": {"url": "/uploads/file.pdf"}}
        assert _get_nested(data, "fileName.url") == "/uploads/file.pdf"

    def test_deeply_nested(self):
        data = {"a": {"b": {"c": "value"}}}
        assert _get_nested(data, "a.b.c") == "value"

    def test_missing_key_returns_none(self):
        assert _get_nested({"title": "test"}, "fileName.url") is None

    def test_non_dict_intermediate_returns_none(self):
        assert _get_nested({"fileName": "not-a-dict"}, "fileName.url") is None

    def test_none_leaf_returns_none(self):
        assert _get_nested({"url": None}, "url") is None

    def test_numeric_value_cast_to_string(self):
        assert _get_nested({"count": 42}, "count") == "42"

    def test_empty_dict_returns_none(self):
        assert _get_nested({}, "key") is None

    def test_single_level_string(self):
        assert _get_nested({"title": "Hello"}, "title") == "Hello"


# ═══════════════════════════════════════════════════════════════════════════
# _resolve_file_url
# ═══════════════════════════════════════════════════════════════════════════


class TestResolveFileUrl:
    def test_relative_gets_strapi_base(self):
        result = _resolve_file_url("/uploads/file.pdf")
        assert result == f"{STRAPI_BASE}/uploads/file.pdf"

    def test_absolute_https_unchanged(self):
        url = "https://strapi.bheuu.gov.my/uploads/file.pdf"
        assert _resolve_file_url(url) == url

    def test_absolute_http_unchanged(self):
        url = "http://strapi.bheuu.gov.my/uploads/file.pdf"
        assert _resolve_file_url(url) == url

    def test_empty_returns_empty(self):
        assert _resolve_file_url("") == ""

    def test_none_returns_empty(self):
        assert _resolve_file_url(None) == ""

    def test_whitespace_trimmed(self):
        result = _resolve_file_url("  /uploads/file.pdf  ")
        assert result == f"{STRAPI_BASE}/uploads/file.pdf"

    def test_url_with_spaces(self):
        result = _resolve_file_url("/uploads/LAPORAN TAHUNAN 2022.pdf")
        assert result.startswith(f"{STRAPI_BASE}/uploads/")

    def test_bare_path_no_leading_slash(self):
        result = _resolve_file_url("uploads/file.pdf")
        assert result == "uploads/file.pdf"


# ═══════════════════════════════════════════════════════════════════════════
# Fixture-based field extraction via adapter helper
# ═══════════════════════════════════════════════════════════════════════════


class TestMediaStatementFixture:
    def setup_method(self):
        self.rec = _load("media_statement.json")

    def test_title_extraction(self):
        title = _get_nested(self.rec, "title") or ""
        assert "EKSPLOITASI" in title

    def test_date_extraction(self):
        raw = _get_nested(self.rec, "publishDate")
        assert _parse_strapi_date(raw) == "2024-01-08"

    def test_file_url_relative_resolved(self):
        raw = _get_nested(self.rec, "fileName.url")
        url = _resolve_file_url(raw)
        assert url.startswith(f"{STRAPI_BASE}/uploads/")
        assert url.endswith(".pdf")


class TestAnnualReportFixture:
    def setup_method(self):
        self.rec = _load("annual_report.json")

    def test_title(self):
        title = _get_nested(self.rec, "title") or ""
        assert "Laporan Tahunan" in title

    def test_date_from_createdAt(self):
        assert _parse_strapi_date(_get_nested(self.rec, "createdAt")) == "2024-07-19"

    def test_absolute_url_preserved(self):
        raw = _get_nested(self.rec, "url")
        url = _resolve_file_url(raw)
        assert url == "https://strapi.bheuu.gov.my/uploads/LAPORAN_TAHUNAN_2022_abc123.pdf"


class TestNewspaperClipFixture:
    def setup_method(self):
        self.rec = _load("newspaper_clip.json")

    def test_pdfFile_url_resolved(self):
        raw = _get_nested(self.rec, "pdfFile.url")
        url = _resolve_file_url(raw)
        assert url.startswith(f"{STRAPI_BASE}/uploads/")

    def test_date_falls_back_to_createdAt(self):
        assert _parse_strapi_date(_get_nested(self.rec, "createdAt")) == "2024-07-26"

    def test_missing_title_field(self):
        title = _get_nested(self.rec, "title")
        assert title is None


class TestActArchiveFixture:
    def setup_method(self):
        self.rec = _load("act_archive.json")

    def test_year_as_title(self):
        assert _get_nested(self.rec, "year") == "2010"

    def test_year_as_date(self):
        assert _parse_strapi_date(_get_nested(self.rec, "year")) == "2010-01-01"

    def test_pdfFile_url(self):
        raw = _get_nested(self.rec, "pdfFile.url")
        url = _resolve_file_url(raw)
        assert url.endswith(".pdf")


class TestActLawWithPdfFixture:
    def setup_method(self):
        self.rec = _load("act_law_with_pdf.json")

    def test_title_from_titleEN(self):
        assert _get_nested(self.rec, "titleEN") == "Research and Bill"

    def test_nested_pdf_url(self):
        raw = _get_nested(self.rec, "pdf.url")
        url = _resolve_file_url(raw)
        assert url.endswith(".pdf")
        assert url.startswith(f"{STRAPI_BASE}/uploads/")


class TestActLawNavOnlyFixture:
    def setup_method(self):
        self.rec = _load("act_law_nav_only.json")

    def test_no_pdf_field(self):
        raw = _get_nested(self.rec, "pdf.url")
        assert raw is None

    def test_file_url_empty_for_none(self):
        raw = _get_nested(self.rec, "pdf.url")
        assert _resolve_file_url(raw) == ""


# ═══════════════════════════════════════════════════════════════════════════
# discover() — collection source_type
# ═══════════════════════════════════════════════════════════════════════════


class TestDiscoverCollection:
    def test_single_record_discovered(self):
        record = {
            "title": "Kenyataan Media Test",
            "publishDate": "2024-03-01",
            "fileName": {"url": "/uploads/km_test.pdf"},
        }
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover())
        assert len(items) == 1
        assert items[0].title == "Kenyataan Media Test"
        assert items[0].published_at == "2024-03-01"

    def test_source_url_is_file_url(self):
        record = {
            "title": "Test",
            "publishDate": "2024-01-01",
            "fileName": {"url": "/uploads/test.pdf"},
        }
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover())
        assert items[0].source_url == f"{STRAPI_BASE}/uploads/test.pdf"

    def test_multiple_records_on_one_page(self):
        records = [
            {
                "title": f"Doc {i}",
                "publishDate": "2024-01-01",
                "fileName": {"url": f"/uploads/doc{i}.pdf"},
            }
            for i in range(5)
        ]
        http = _mock_http([records, []])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover())
        assert len(items) == 5

    def test_pagination_two_pages(self):
        page1 = [
            {
                "title": f"Doc {i}",
                "publishDate": "2024-01-01",
                "fileName": {"url": f"/uploads/doc{i}.pdf"},
            }
            for i in range(100)
        ]
        page2 = [
            {
                "title": "Doc 100",
                "publishDate": "2024-01-01",
                "fileName": {"url": "/uploads/doc100.pdf"},
            }
        ]
        http = _mock_http([page1, page2])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover())
        assert len(items) == 101

    def test_pagination_stops_when_page_smaller_than_limit(self):
        """When a page has fewer than `limit` records, pagination stops without
        fetching the next page."""
        records = [
            {
                "title": "Doc",
                "publishDate": "2024-01-01",
                "fileName": {"url": "/uploads/doc.pdf"},
            }
        ]
        http = _mock_http([records])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover())
        assert len(items) == 1
        # Only one call: page had fewer than 100 items so pagination stopped
        assert http.get.call_count == 1

    def test_max_pages_respected(self):
        page = [
            {
                "title": "Doc",
                "publishDate": "2024-01-01",
                "fileName": {"url": "/uploads/doc.pdf"},
            }
        ] * 100  # full page
        http = _mock_http([page, page, page, page, page])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover(max_pages=1))
        # Only first page processed
        assert http.get.call_count == 1

    def test_missing_file_url_skipped(self):
        record = {
            "titleEN": "Navigation Only",
            "createdAt": "2024-08-05T03:58:48.468Z",
        }
        section = {**_COLLECTION_SECTION, "file_field": "pdf.url", "title_field": "titleEN"}
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [section]}, http)
        items = list(adapter.discover())
        assert len(items) == 0

    def test_record_with_absolute_file_url(self):
        record = {
            "title": "Report",
            "publishDate": "2024-01-01",
            "url": "https://strapi.bheuu.gov.my/uploads/report.pdf",
        }
        section = {**_COLLECTION_SECTION, "file_field": "url"}
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [section]}, http)
        items = list(adapter.discover())
        assert len(items) == 1
        assert items[0].source_url == "https://strapi.bheuu.gov.my/uploads/report.pdf"

    def test_doc_type_propagated(self):
        record = {
            "title": "Test",
            "publishDate": "2024-01-01",
            "fileName": {"url": "/uploads/test.pdf"},
        }
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover())
        assert items[0].doc_type == "press_release"

    def test_language_propagated(self):
        record = {
            "title": "Test",
            "publishDate": "2024-01-01",
            "fileName": {"url": "/uploads/test.pdf"},
        }
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover())
        assert items[0].language == "ms"

    def test_metadata_contains_strapi_api(self):
        record = {
            "title": "Test",
            "publishDate": "2024-01-01",
            "fileName": {"url": "/uploads/test.pdf"},
        }
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover())
        assert "strapi_api" in items[0].metadata

    def test_title_fallback_chain(self):
        """When primary title_field is empty, falls back to titleEN, titleBM, etc."""
        record = {
            "title": "",
            "titleEN": "English Title",
            "publishDate": "2024-01-01",
            "fileName": {"url": "/uploads/test.pdf"},
        }
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover())
        assert items[0].title == "English Title"

    def test_title_fallback_to_titleBM(self):
        record = {
            "title": "",
            "titleBM": "Tajuk Bahasa Melayu",
            "publishDate": "2024-01-01",
            "fileName": {"url": "/uploads/test.pdf"},
        }
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover())
        assert items[0].title == "Tajuk Bahasa Melayu"

    def test_title_fallback_to_tenderTitle(self):
        record = {
            "title": "",
            "tenderTitle": "Tender ABC",
            "publishDate": "2024-01-01",
            "fileName": {"url": "/uploads/test.pdf"},
        }
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover())
        assert items[0].title == "Tender ABC"

    def test_date_fallback_to_published_at(self):
        record = {
            "title": "Test",
            "published_at": "2024-10-08T07:52:58.284Z",
            "fileName": {"url": "/uploads/test.pdf"},
        }
        section = {**_COLLECTION_SECTION, "date_field": ""}
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [section]}, http)
        items = list(adapter.discover())
        assert items[0].published_at == "2024-10-08"

    def test_date_fallback_to_createdAt(self):
        record = {
            "title": "Test",
            "createdAt": "2024-07-19T02:56:17.631Z",
            "fileName": {"url": "/uploads/test.pdf"},
        }
        section = {**_COLLECTION_SECTION, "date_field": "nonexistent"}
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [section]}, http)
        items = list(adapter.discover())
        assert items[0].published_at == "2024-07-19"


# ═══════════════════════════════════════════════════════════════════════════
# discover() — single_type source_type
# ═══════════════════════════════════════════════════════════════════════════


class TestDiscoverSingleType:
    def test_single_type_dict_discovered(self):
        record = {
            "createdAt": "2024-07-26T12:32:55.596Z",
            "pdfFile": {"url": "/uploads/Keratan_Akhbar.pdf"},
        }
        http = _mock_http([record])
        adapter = _make_adapter({"sections": [_SINGLE_TYPE_SECTION]}, http)
        items = list(adapter.discover())
        assert len(items) == 1

    def test_single_type_uses_correct_endpoint(self):
        record = {
            "createdAt": "2024-07-26T12:32:55.596Z",
            "pdfFile": {"url": "/uploads/Keratan_Akhbar.pdf"},
        }
        http = _mock_http([record])
        adapter = _make_adapter({"sections": [_SINGLE_TYPE_SECTION]}, http)
        list(adapter.discover())
        url = http.get.call_args[0][0]
        assert "act-protection-newspaper-clip" in url

    def test_single_type_non_dict_response_skipped(self):
        """If a single_type endpoint returns a list, nothing is yielded."""
        http = _mock_http([[{"some": "data"}]])
        adapter = _make_adapter({"sections": [_SINGLE_TYPE_SECTION]}, http)
        items = list(adapter.discover())
        assert len(items) == 0

    def test_single_type_missing_file_url_skipped(self):
        record = {
            "createdAt": "2024-07-26T12:32:55.596Z",
            # pdfFile intentionally missing
        }
        http = _mock_http([record])
        adapter = _make_adapter({"sections": [_SINGLE_TYPE_SECTION]}, http)
        items = list(adapter.discover())
        assert len(items) == 0

    def test_single_type_file_url_resolved(self):
        record = {
            "createdAt": "2024-07-26T12:32:55.596Z",
            "pdfFile": {"url": "/uploads/Keratan_Akhbar.pdf"},
        }
        http = _mock_http([record])
        adapter = _make_adapter({"sections": [_SINGLE_TYPE_SECTION]}, http)
        items = list(adapter.discover())
        assert items[0].source_url == f"{STRAPI_BASE}/uploads/Keratan_Akhbar.pdf"

    def test_single_type_http_error_graceful(self):
        http = MagicMock(spec=HTTPClient)
        http.get.side_effect = Exception("Connection error")
        adapter = _make_adapter({"sections": [_SINGLE_TYPE_SECTION]}, http)
        items = list(adapter.discover())
        assert len(items) == 0


# ═══════════════════════════════════════════════════════════════════════════
# discover() — metadata_only source_type
# ═══════════════════════════════════════════════════════════════════════════


class TestDiscoverMetadataOnly:
    def test_metadata_only_yields_items(self):
        record = {
            "title": "Latest News Item",
            "publishDate": "2024-09-01",
        }
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [_METADATA_ONLY_SECTION]}, http)
        items = list(adapter.discover())
        assert len(items) == 1
        assert items[0].title == "Latest News Item"

    def test_metadata_only_source_url_is_api_url(self):
        record = {"title": "Test", "publishDate": "2024-09-01"}
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [_METADATA_ONLY_SECTION]}, http)
        items = list(adapter.discover())
        assert "latest-news" in items[0].source_url

    def test_metadata_only_has_correct_metadata(self):
        record = {"title": "Test", "publishDate": "2024-09-01"}
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [_METADATA_ONLY_SECTION]}, http)
        items = list(adapter.discover())
        assert items[0].metadata.get("type") == "metadata_only"

    def test_metadata_only_pagination(self):
        page1 = [{"title": f"News {i}", "publishDate": "2024-09-01"} for i in range(100)]
        page2 = [{"title": "News 100", "publishDate": "2024-09-01"}]
        http = _mock_http([page1, page2])
        adapter = _make_adapter({"sections": [_METADATA_ONLY_SECTION]}, http)
        items = list(adapter.discover())
        assert len(items) == 101

    def test_metadata_only_stops_when_page_smaller_than_limit(self):
        """When page has fewer than limit records, pagination stops."""
        page1 = [{"title": "News", "publishDate": "2024-09-01"}]
        http = _mock_http([page1])
        adapter = _make_adapter({"sections": [_METADATA_ONLY_SECTION]}, http)
        items = list(adapter.discover())
        assert len(items) == 1
        # Only one call: page had fewer than 100 items
        assert http.get.call_count == 1

    def test_metadata_only_since_filtering(self):
        records = [
            {"title": "Old", "publishDate": "2020-01-01"},
            {"title": "New", "publishDate": "2025-01-01"},
        ]
        http = _mock_http([records, []])
        adapter = _make_adapter({"sections": [_METADATA_ONLY_SECTION]}, http)
        items = list(adapter.discover(since=date(2024, 1, 1)))
        assert len(items) == 1
        assert items[0].title == "New"


# ═══════════════════════════════════════════════════════════════════════════
# discover() — since date filtering
# ═══════════════════════════════════════════════════════════════════════════


class TestSinceDateFiltering:
    def test_record_before_since_skipped(self):
        record = {
            "title": "Old Document",
            "publishDate": "2022-01-01",
            "fileName": {"url": "/uploads/old.pdf"},
        }
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover(since=date(2024, 1, 1)))
        assert len(items) == 0

    def test_record_on_since_date_included(self):
        record = {
            "title": "New Document",
            "publishDate": "2024-01-01",
            "fileName": {"url": "/uploads/new.pdf"},
        }
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover(since=date(2024, 1, 1)))
        assert len(items) == 1

    def test_record_after_since_included(self):
        record = {
            "title": "New Document",
            "publishDate": "2025-06-01",
            "fileName": {"url": "/uploads/new.pdf"},
        }
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover(since=date(2024, 1, 1)))
        assert len(items) == 1

    def test_no_since_returns_all(self):
        records = [
            {
                "title": f"Doc {i}",
                "publishDate": f"20{20+i}-01-01",
                "fileName": {"url": f"/uploads/doc{i}.pdf"},
            }
            for i in range(3)
        ]
        http = _mock_http([records, []])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover(since=None))
        assert len(items) == 3

    def test_record_with_no_date_not_filtered(self):
        record = {
            "title": "No Date",
            "fileName": {"url": "/uploads/nodate.pdf"},
        }
        section = {**_COLLECTION_SECTION, "date_field": "nonexistent"}
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [section]}, http)
        items = list(adapter.discover(since=date(2024, 1, 1)))
        # Records without dates should still be included
        assert len(items) == 1


# ═══════════════════════════════════════════════════════════════════════════
# discover() — empty and malformed responses
# ═══════════════════════════════════════════════════════════════════════════


class TestEmptyAndMalformedResponses:
    def test_empty_sections_config(self):
        adapter = _make_adapter({"sections": []}, _mock_http([]))
        items = list(adapter.discover())
        assert items == []

    def test_no_sections_key(self):
        adapter = _make_adapter({}, _mock_http([]))
        items = list(adapter.discover())
        assert items == []

    def test_empty_list_response(self):
        http = _mock_http([[]])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover())
        assert items == []

    def test_non_list_response_for_collection(self):
        """Collection expects a list; a dict response should stop pagination."""
        http = _mock_http([{"unexpected": "dict"}])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover())
        assert items == []

    def test_http_error_graceful(self):
        http = MagicMock(spec=HTTPClient)
        http.get.side_effect = Exception("Connection refused")
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover())
        assert items == []

    def test_json_decode_error_graceful(self):
        http = MagicMock(spec=HTTPClient)
        resp = MagicMock()
        resp.json.side_effect = ValueError("Invalid JSON")
        http.get.return_value = resp
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover())
        assert items == []

    def test_record_with_empty_title_and_no_fallback(self):
        record = {
            "publishDate": "2024-01-01",
            "fileName": {"url": "/uploads/test.pdf"},
        }
        http = _mock_http([[record], []])
        adapter = _make_adapter({"sections": [_COLLECTION_SECTION]}, http)
        items = list(adapter.discover())
        # Record yields because file_url is present, but title is empty
        assert len(items) == 1
        assert items[0].title == ""


# ═══════════════════════════════════════════════════════════════════════════
# discover() — multiple sections
# ═══════════════════════════════════════════════════════════════════════════


class TestMultipleSections:
    def test_two_sections_combined(self):
        media_record = {
            "title": "Media Statement",
            "publishDate": "2024-01-01",
            "fileName": {"url": "/uploads/media.pdf"},
        }
        news_record = {
            "title": "News Item",
            "publishDate": "2024-02-01",
        }
        # Each section with < limit records stops after 1 page fetch
        http = _mock_http([
            [media_record],   # collection section (< 100 records, stops)
            [news_record],    # metadata_only section (< 100 records, stops)
        ])
        adapter = _make_adapter(
            {"sections": [_COLLECTION_SECTION, _METADATA_ONLY_SECTION]},
            http,
        )
        items = list(adapter.discover())
        assert len(items) == 2

    def test_custom_strapi_base(self):
        record = {
            "title": "Test",
            "publishDate": "2024-01-01",
            "fileName": {"url": "/uploads/test.pdf"},
        }
        http = _mock_http([[record], []])
        config = {
            "strapi_base": "https://custom-strapi.example.com",
            "sections": [_COLLECTION_SECTION],
        }
        adapter = _make_adapter(config, http)
        list(adapter.discover())
        url = http.get.call_args_list[0][0][0]
        assert url.startswith("https://custom-strapi.example.com/")


# ═══════════════════════════════════════════════════════════════════════════
# fetch_and_extract()
# ═══════════════════════════════════════════════════════════════════════════


class TestFetchAndExtract:
    def test_yields_document_candidate(self):
        adapter = _make_adapter({})
        item = DiscoveredItem(
            source_url=f"{STRAPI_BASE}/uploads/test.pdf",
            title="Test Document",
            published_at="2024-01-08",
            doc_type="press_release",
            language="ms",
            metadata={"strapi_api": f"{STRAPI_BASE}/media-statements?_start=0"},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert len(candidates) == 1
        assert isinstance(candidates[0], DocumentCandidate)

    def test_candidate_url_matches_source(self):
        adapter = _make_adapter({})
        item = DiscoveredItem(
            source_url=f"{STRAPI_BASE}/uploads/test.pdf",
            title="Test",
            metadata={"strapi_api": "api-url"},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates[0].url == f"{STRAPI_BASE}/uploads/test.pdf"

    def test_candidate_content_type_inferred(self):
        adapter = _make_adapter({})
        item = DiscoveredItem(
            source_url=f"{STRAPI_BASE}/uploads/test.pdf",
            title="Test",
            metadata={},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates[0].content_type == "application/pdf"

    def test_candidate_source_page_url_from_metadata(self):
        adapter = _make_adapter({})
        item = DiscoveredItem(
            source_url=f"{STRAPI_BASE}/uploads/test.pdf",
            title="Test",
            metadata={"strapi_api": "https://strapi.bheuu.gov.my/media-statements?_start=0"},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates[0].source_page_url == \
            "https://strapi.bheuu.gov.my/media-statements?_start=0"

    def test_candidate_preserves_title_and_date(self):
        adapter = _make_adapter({})
        item = DiscoveredItem(
            source_url=f"{STRAPI_BASE}/uploads/test.pdf",
            title="My Title",
            published_at="2024-03-15",
            doc_type="report",
            language="en",
            metadata={},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates[0].title == "My Title"
        assert candidates[0].published_at == "2024-03-15"
        assert candidates[0].doc_type == "report"


# ═══════════════════════════════════════════════════════════════════════════
# Adapter properties
# ═══════════════════════════════════════════════════════════════════════════


class TestAdapterProperties:
    def test_slug(self):
        assert BheuuAdapter.slug == "bheuu"

    def test_agency(self):
        assert "BHEUU" in BheuuAdapter.agency

    def test_requires_browser_false(self):
        assert BheuuAdapter.requires_browser is False
