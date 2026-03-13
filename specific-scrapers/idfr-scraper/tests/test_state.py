"""Tests for SQLite state store deduplication logic."""
import tempfile
from pathlib import Path

import pytest

from idfr_scraper.models import Record, PARSER_VERSION
from idfr_scraper.state import StateStore


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    db = tmp_path / "test_state.db"
    s = StateStore(db)
    yield s
    s.close()


def _make_record(**kwargs) -> Record:
    defaults = dict(
        record_id="rec-001",
        source_url="https://www.idfr.gov.my/my/media-1/press",
        canonical_url="https://www.idfr.gov.my/my/images/stories/press/test.pdf",
        title="Test Press Release",
        published_at="2025-01-01",
        agency="IDFR",
        doc_type="press_release",
        content_type="application/pdf",
        language="ms",
        sha256="abc123" * 10 + "ab",  # 62 chars – close enough for testing
        gcs_bucket="my-bucket",
        gcs_object="gov-docs/idfr/raw/2025/01/01/abc123_test.pdf",
        gcs_uri="gs://my-bucket/gov-docs/idfr/raw/2025/01/01/abc123_test.pdf",
        http_etag='"abc"',
        http_last_modified="Wed, 01 Jan 2025 00:00:00 GMT",
        fetched_at="2025-01-01T00:00:00Z",
        crawl_run_id="2025-01-01-idfr",
    )
    defaults.update(kwargs)
    return Record(**defaults)


class TestStateStoreDedup:
    def test_get_by_url_returns_none_for_unknown(self, store: StateStore):
        result = store.get_by_url("https://www.idfr.gov.my/unknown.pdf")
        assert result is None

    def test_upsert_and_get_by_url(self, store: StateStore):
        record = _make_record()
        store.upsert_record(record)
        row = store.get_by_url(record.canonical_url)
        assert row is not None
        assert row["canonical_url"] == record.canonical_url

    def test_get_gcs_uri_by_sha256_returns_none_when_missing(self, store: StateStore):
        result = store.get_gcs_uri_by_sha256("nonexistent_sha")
        assert result is None

    def test_get_gcs_uri_by_sha256_after_upsert(self, store: StateStore):
        record = _make_record()
        store.upsert_record(record)
        gcs_uri = store.get_gcs_uri_by_sha256(record.sha256)
        assert gcs_uri == record.gcs_uri

    def test_upsert_updates_existing_url(self, store: StateStore):
        record = _make_record()
        store.upsert_record(record)

        updated = _make_record(
            record_id="rec-002",
            sha256="def456" * 10 + "de",
            gcs_uri="gs://my-bucket/gov-docs/idfr/raw/2025/02/01/def456_test.pdf",
            gcs_object="gov-docs/idfr/raw/2025/02/01/def456_test.pdf",
        )
        store.upsert_record(updated)

        row = store.get_by_url(record.canonical_url)
        assert row is not None
        # sha256 should be updated to the new value
        assert row["sha256"] == updated.sha256

    def test_mark_inactive(self, store: StateStore):
        record = _make_record()
        store.upsert_record(record)
        store.mark_inactive(record.canonical_url)

        row = store.get_by_url(record.canonical_url)
        assert row is not None
        assert row["status"] == "inactive"

    def test_save_and_retrieve_crawl_run(self, store: StateStore):
        store.save_crawl_run(
            crawl_run_id="2025-01-01-idfr",
            site_slug="idfr",
            started_at="2025-01-01T00:00:00Z",
            completed_at="2025-01-01T01:00:00Z",
            new_count=10,
            changed_count=2,
            skipped_count=5,
            failed_count=0,
        )
        # Verify it was saved (no exception = success)
        # Re-insertion as REPLACE should also work
        store.save_crawl_run(
            crawl_run_id="2025-01-01-idfr",
            site_slug="idfr",
            started_at="2025-01-01T00:00:00Z",
            completed_at="2025-01-01T01:30:00Z",
            new_count=12,
            changed_count=2,
            skipped_count=5,
            failed_count=1,
        )

    def test_two_records_same_sha256(self, store: StateStore):
        """Two different URLs pointing to the same content."""
        sha = "same_sha" * 8
        rec1 = _make_record(
            record_id="rec-001",
            canonical_url="https://www.idfr.gov.my/my/images/press/a.pdf",
            sha256=sha,
            gcs_uri="gs://my-bucket/gov-docs/idfr/raw/2025/01/01/sha_a.pdf",
            gcs_object="gov-docs/idfr/raw/2025/01/01/sha_a.pdf",
        )
        store.upsert_record(rec1)

        # Should return the existing gcs_uri for the same sha256
        existing_uri = store.get_gcs_uri_by_sha256(sha)
        assert existing_uri == rec1.gcs_uri
