"""
Tests for SQLite state store deduplication logic.
"""
import tempfile
from pathlib import Path

import pytest

from bheuu_scraper.models import Record
from bheuu_scraper.state import StateStore


def _make_record(**overrides) -> Record:
    defaults = dict(
        record_id="rec-001",
        source_url="https://strapi.bheuu.gov.my/media-statements?_start=0&_limit=100",
        canonical_url="https://strapi.bheuu.gov.my/uploads/file.pdf",
        title="Test Document",
        published_at="2024-01-08",
        agency="BHEUU",
        doc_type="press_release",
        content_type="application/pdf",
        language="ms",
        sha256="abc123",
        spaces_bucket="test-bucket",
        spaces_path="gov-docs/bheuu/raw/2024/01/08/abc123_file.pdf",
        spaces_url="https://test-bucket.sgp1.digitaloceanspaces.com/gov-docs/bheuu/raw/2024/01/08/abc123_file.pdf",
        http_etag='"etag123"',
        http_last_modified="Mon, 08 Jan 2024 00:00:00 GMT",
        fetched_at="2024-01-08T00:00:00Z",
        crawl_run_id="2024-01-08-bheuu",
    )
    defaults.update(overrides)
    return Record(**defaults)


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        s = StateStore(db_path)
        yield s
        s.close()


class TestUpsertAndGetByUrl:
    def test_get_missing_url_returns_none(self, store):
        assert store.get_by_url("https://example.com/nonexistent.pdf") is None

    def test_upsert_and_retrieve(self, store):
        rec = _make_record()
        store.upsert_record(rec)
        row = store.get_by_url(rec.canonical_url)
        assert row is not None
        assert row["sha256"] == "abc123"

    def test_upsert_updates_existing(self, store):
        rec = _make_record()
        store.upsert_record(rec)
        updated = _make_record(sha256="new_sha", spaces_url="https://new.url/file.pdf")
        store.upsert_record(updated)
        row = store.get_by_url(rec.canonical_url)
        assert row["sha256"] == "new_sha"


class TestSha256Dedup:
    def test_get_spaces_url_by_sha256(self, store):
        rec = _make_record()
        store.upsert_record(rec)
        result = store.get_spaces_url_by_sha256("abc123")
        assert result == rec.spaces_url

    def test_missing_sha256_returns_none(self, store):
        assert store.get_spaces_url_by_sha256("deadbeef") is None

    def test_get_spaces_path_by_sha256(self, store):
        rec = _make_record()
        store.upsert_record(rec)
        path = store.get_spaces_path_by_sha256("abc123")
        assert "bheuu" in path

    def test_different_urls_same_sha256(self, store):
        """Two URLs pointing to identical content share the same Spaces path."""
        rec1 = _make_record(
            record_id="rec-001",
            canonical_url="https://strapi.bheuu.gov.my/uploads/file_v1.pdf",
            sha256="same_hash",
        )
        store.upsert_record(rec1)
        result = store.get_spaces_url_by_sha256("same_hash")
        assert result is not None


class TestMarkInactive:
    def test_mark_inactive(self, store):
        rec = _make_record()
        store.upsert_record(rec)
        store.mark_inactive(rec.canonical_url)
        row = store.get_by_url(rec.canonical_url)
        assert row["status"] == "inactive"


class TestCrawlRun:
    def test_save_and_retrieve(self, store):
        store.save_crawl_run(
            crawl_run_id="2024-01-08-bheuu",
            site_slug="bheuu",
            started_at="2024-01-08T00:00:00Z",
            completed_at="2024-01-08T00:10:00Z",
            new_count=10,
            changed_count=2,
            skipped_count=5,
            failed_count=0,
        )
        row = store.conn.execute(
            "SELECT * FROM crawl_runs WHERE crawl_run_id = ?",
            ("2024-01-08-bheuu",),
        ).fetchone()
        assert row["new_count"] == 10
        assert row["site_slug"] == "bheuu"
