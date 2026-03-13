"""Tests for the SQLite state store."""
import tempfile
from pathlib import Path

import pytest

from dewan_johor_scraper.models import Record
from dewan_johor_scraper.state import StateStore


def _make_record(url: str, sha256: str = "abc123", gcs_uri: str = "gs://bucket/obj") -> Record:
    return Record(
        record_id=f"rec-{url[-8:]}",
        source_url="https://dewannegeri.johor.gov.my/wp-sitemap-posts-wpdmpro-1.xml",
        canonical_url=url,
        title="Test Record",
        published_at="2019-07-27",
        agency="Dewan Negeri Johor",
        doc_type="report",
        content_type="text/html",
        language="ms",
        sha256=sha256,
        gcs_bucket="test-bucket",
        gcs_object="gov-docs/dewan-johor/raw/2019/07/27/abc123_doc.html",
        gcs_uri=gcs_uri,
        http_etag='"etag123"',
        http_last_modified="Sat, 27 Jul 2019 00:30:00 GMT",
        fetched_at="2026-02-26T10:00:00Z",
        crawl_run_id="2026-02-26-dewan-johor",
    )


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "state.db"
    s = StateStore(db)
    yield s
    s.close()


class TestStateStore:
    def test_upsert_and_get_by_url(self, store):
        url = "https://dewannegeri.johor.gov.my/download/28-jun-2018/"
        rec = _make_record(url)
        store.upsert_record(rec)
        row = store.get_by_url(url)
        assert row is not None
        assert row["canonical_url"] == url

    def test_get_by_url_returns_none_for_unknown(self, store):
        assert store.get_by_url("https://dewannegeri.johor.gov.my/unknown/") is None

    def test_get_gcs_uri_by_sha256(self, store):
        url = "https://dewannegeri.johor.gov.my/download/28-jun-2018/"
        rec = _make_record(url, sha256="deadbeef", gcs_uri="gs://bucket/deadbeef_obj")
        store.upsert_record(rec)
        result = store.get_gcs_uri_by_sha256("deadbeef")
        assert result == "gs://bucket/deadbeef_obj"

    def test_get_gcs_uri_returns_none_for_unknown_sha(self, store):
        assert store.get_gcs_uri_by_sha256("nonexistent") is None

    def test_upsert_updates_existing(self, store):
        url = "https://dewannegeri.johor.gov.my/download/28-jun-2018/"
        rec1 = _make_record(url, sha256="old_sha", gcs_uri="gs://bucket/old")
        store.upsert_record(rec1)

        rec2 = _make_record(url, sha256="new_sha", gcs_uri="gs://bucket/new")
        rec2.fetched_at = "2026-03-01T10:00:00Z"
        store.upsert_record(rec2)

        row = store.get_by_url(url)
        assert row["sha256"] == "new_sha"
        assert row["gcs_uri"] == "gs://bucket/new"

    def test_mark_inactive(self, store):
        url = "https://dewannegeri.johor.gov.my/download/28-jun-2018/"
        rec = _make_record(url)
        store.upsert_record(rec)
        store.mark_inactive(url)
        row = store.get_by_url(url)
        assert row["status"] == "inactive"

    def test_save_crawl_run(self, store):
        store.save_crawl_run(
            crawl_run_id="2026-02-26-dewan-johor",
            site_slug="dewan-johor",
            started_at="2026-02-26T10:00:00Z",
            completed_at="2026-02-26T10:05:00Z",
            new_count=10,
            changed_count=2,
            skipped_count=5,
            failed_count=0,
        )
        cur = store.conn.execute(
            "SELECT * FROM crawl_runs WHERE crawl_run_id = ?",
            ("2026-02-26-dewan-johor",),
        )
        row = cur.fetchone()
        assert row is not None
        assert row["new_count"] == 10
        assert row["site_slug"] == "dewan-johor"

    def test_no_duplicate_canonical_url(self, store):
        url = "https://dewannegeri.johor.gov.my/download/28-jun-2018/"
        store.upsert_record(_make_record(url, sha256="sha1"))
        store.upsert_record(_make_record(url, sha256="sha2"))
        cur = store.conn.execute(
            "SELECT COUNT(*) as cnt FROM documents WHERE canonical_url = ?", (url,)
        )
        assert cur.fetchone()["cnt"] == 1

    def test_db_persists_across_reopen(self, tmp_path):
        db = tmp_path / "state.db"
        url = "https://dewannegeri.johor.gov.my/download/28-jun-2018/"

        s1 = StateStore(db)
        s1.upsert_record(_make_record(url))
        s1.close()

        s2 = StateStore(db)
        assert s2.get_by_url(url) is not None
        s2.close()
