"""Tests for SQLite state store deduplication logic."""
import tempfile
from pathlib import Path

import pytest

from dewan_selangor_scraper.models import Record, PARSER_VERSION
from dewan_selangor_scraper.state import StateStore

FETCHED_AT = "2025-11-13T01:30:00Z"


def _make_record(**kwargs) -> Record:
    defaults = dict(
        record_id="abc123-def456",
        source_url="https://dewan.selangor.gov.my/berita-dewan/",
        canonical_url="https://dewan.selangor.gov.my/awasi-tambah-baik/",
        title="Awasi Tambah Baik",
        published_at="2025-11-13",
        agency="Dewan Negeri Selangor",
        doc_type="press_release",
        content_type="text/html",
        language="ms",
        sha256="a" * 64,
        gcs_bucket="my-bucket",
        gcs_object="gov-docs/dewan-selangor/raw/2025/11/13/aaa_post.html",
        gcs_uri="gs://my-bucket/gov-docs/dewan-selangor/raw/2025/11/13/aaa_post.html",
        http_etag='"etag1"',
        http_last_modified="Wed, 13 Nov 2025 01:30:00 GMT",
        fetched_at=FETCHED_AT,
        crawl_run_id="2025-11-13-dewan-selangor",
    )
    defaults.update(kwargs)
    return Record(**defaults)


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_state.db"
        s = StateStore(db_path)
        yield s
        s.close()


class TestStateStore:
    def test_get_by_url_returns_none_for_unknown(self, store):
        assert store.get_by_url("https://dewan.selangor.gov.my/unknown/") is None

    def test_upsert_and_get_by_url(self, store):
        rec = _make_record()
        store.upsert_record(rec)
        row = store.get_by_url(rec.canonical_url)
        assert row is not None
        assert row["sha256"] == rec.sha256

    def test_upsert_updates_on_conflict(self, store):
        rec = _make_record()
        store.upsert_record(rec)
        updated = _make_record(sha256="b" * 64, fetched_at="2025-11-14T01:00:00Z")
        store.upsert_record(updated)
        row = store.get_by_url(rec.canonical_url)
        assert row["sha256"] == "b" * 64

    def test_get_gcs_uri_by_sha256_returns_none_unknown(self, store):
        assert store.get_gcs_uri_by_sha256("0" * 64) is None

    def test_get_gcs_uri_by_sha256_returns_existing(self, store):
        rec = _make_record()
        store.upsert_record(rec)
        uri = store.get_gcs_uri_by_sha256(rec.sha256)
        assert uri == rec.gcs_uri

    def test_dedup_by_sha256_different_urls_same_content(self, store):
        rec1 = _make_record(
            record_id="rec1",
            canonical_url="https://dewan.selangor.gov.my/page-a/",
            sha256="c" * 64,
            gcs_uri="gs://my-bucket/gov-docs/dewan-selangor/raw/c_page.html",
        )
        store.upsert_record(rec1)
        # Different URL, same sha256
        existing_uri = store.get_gcs_uri_by_sha256("c" * 64)
        assert existing_uri == rec1.gcs_uri

    def test_mark_inactive(self, store):
        rec = _make_record()
        store.upsert_record(rec)
        store.mark_inactive(rec.canonical_url)
        row = store.get_by_url(rec.canonical_url)
        assert row["status"] == "inactive"

    def test_save_crawl_run(self, store):
        store.save_crawl_run(
            crawl_run_id="2025-11-13-dewan-selangor",
            site_slug="dewan-selangor",
            started_at="2025-11-13T00:00:00Z",
            completed_at="2025-11-13T01:00:00Z",
            new_count=10,
            changed_count=2,
            skipped_count=5,
            failed_count=0,
        )
        # No assertion needed – just confirm it doesn't raise
