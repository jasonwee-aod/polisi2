"""
Tests for the SQLite state store (dedup logic, upsert, mark_inactive).
"""
import pytest

from moh_scraper.models import Record
from moh_scraper.state import StateStore


def _make_record(**overrides) -> Record:
    defaults = dict(
        record_id="rec-001",
        source_url="https://www.moh.gov.my/en/listing",
        canonical_url="https://www.moh.gov.my/en/article/test",
        title="Test Article",
        published_at="2026-02-23",
        agency="MOH",
        doc_type="press_release",
        content_type="text/html",
        language="ms",
        sha256="abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
        spaces_bucket="test-bucket",
        spaces_path="gov-docs/moh/raw/2026/02/23/abc123_test.html",
        spaces_url="https://test-bucket.sgp1.digitaloceanspaces.com/gov-docs/moh/raw/2026/02/23/abc123_test.html",
        http_etag='"abc123"',
        http_last_modified="Mon, 23 Feb 2026 00:00:00 GMT",
        fetched_at="2026-02-23T10:00:00Z",
        crawl_run_id="2026-02-23-moh",
    )
    defaults.update(overrides)
    return Record(**defaults)


@pytest.fixture
def store():
    s = StateStore(":memory:")
    yield s
    s.close()


class TestStateStoreUpsert:
    def test_insert_and_get_by_url(self, store):
        rec = _make_record()
        store.upsert_record(rec)
        row = store.get_by_url(rec.canonical_url)
        assert row is not None
        assert row["canonical_url"] == rec.canonical_url

    def test_unknown_url_returns_none(self, store):
        row = store.get_by_url("https://www.moh.gov.my/en/not-there")
        assert row is None

    def test_upsert_updates_existing(self, store):
        rec = _make_record()
        store.upsert_record(rec)
        updated = _make_record(record_id="rec-002", http_etag='"new-etag"')
        store.upsert_record(updated)
        row = store.get_by_url(rec.canonical_url)
        assert row["http_etag"] == '"new-etag"'

    def test_duplicate_url_does_not_raise(self, store):
        rec = _make_record()
        store.upsert_record(rec)
        store.upsert_record(rec)  # should not raise


class TestStateStoreSha256Lookup:
    def test_get_spaces_url_by_sha256(self, store):
        rec = _make_record()
        store.upsert_record(rec)
        url = store.get_spaces_url_by_sha256(rec.sha256)
        assert url == rec.spaces_url

    def test_get_spaces_path_by_sha256(self, store):
        rec = _make_record()
        store.upsert_record(rec)
        path = store.get_spaces_path_by_sha256(rec.sha256)
        assert path == rec.spaces_path

    def test_unknown_sha256_returns_none(self, store):
        assert store.get_spaces_url_by_sha256("nonexistent") is None
        assert store.get_spaces_path_by_sha256("nonexistent") is None


class TestMarkInactive:
    def test_mark_inactive_changes_status(self, store):
        rec = _make_record()
        store.upsert_record(rec)
        store.mark_inactive(rec.canonical_url)
        row = store.get_by_url(rec.canonical_url)
        assert row is not None
        assert row["status"] == "inactive"

    def test_upsert_reactivates(self, store):
        rec = _make_record()
        store.upsert_record(rec)
        store.mark_inactive(rec.canonical_url)
        store.upsert_record(rec)
        row = store.get_by_url(rec.canonical_url)
        assert row["status"] == "active"


class TestSaveCrawlRun:
    def test_save_and_retrieve(self, store):
        store.save_crawl_run(
            crawl_run_id="2026-02-23-moh",
            site_slug="moh",
            started_at="2026-02-23T10:00:00Z",
            completed_at="2026-02-23T10:05:00Z",
            new_count=10,
            changed_count=0,
            skipped_count=5,
            failed_count=1,
        )
        cur = store.conn.execute(
            "SELECT * FROM crawl_runs WHERE crawl_run_id = ?",
            ("2026-02-23-moh",),
        )
        row = cur.fetchone()
        assert row is not None
        assert row["new_count"] == 10
        assert row["failed_count"] == 1
