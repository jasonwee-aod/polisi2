"""
Tests for SQLite state store: upsert, dedup, and crawl run persistence.
"""
import tempfile
from pathlib import Path

import pytest

from rmp_scraper.models import Record
from rmp_scraper.state import StateStore

PARSER_VERSION = "v1"


def _make_record(
    record_id: str = "abc123-test",
    canonical_url: str = "https://www.rmp.gov.my/arkib-berita/berita/2026/03/09/slug",
    sha256: str = "a" * 64,
    spaces_url: str = "https://bucket.sgp1.digitaloceanspaces.com/gov-docs/rmp/raw/2026/03/09/hash_slug.html",
    spaces_path: str = "gov-docs/rmp/raw/2026/03/09/hash_slug.html",
) -> Record:
    return Record(
        record_id=record_id,
        source_url="https://www.rmp.gov.my/arkib-berita/berita",
        canonical_url=canonical_url,
        title="Test Article",
        published_at="2026-03-09",
        agency="Royal Malaysia Police (Polis DiRaja Malaysia)",
        doc_type="press_release",
        content_type="text/html",
        language="ms",
        sha256=sha256,
        spaces_bucket="test-bucket",
        spaces_path=spaces_path,
        spaces_url=spaces_url,
        http_etag='"abc"',
        http_last_modified="Mon, 09 Mar 2026 00:00:00 GMT",
        fetched_at="2026-03-09T10:00:00Z",
        crawl_run_id="2026-03-09-rmp",
        parser_version=PARSER_VERSION,
    )


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "state.db"
    s = StateStore(db)
    yield s
    s.close()


class TestStateStore:
    def test_get_by_url_returns_none_initially(self, store):
        assert store.get_by_url("https://www.rmp.gov.my/unknown") is None

    def test_upsert_and_get_by_url(self, store):
        record = _make_record()
        store.upsert_record(record)
        row = store.get_by_url(record.canonical_url)
        assert row is not None
        assert row["canonical_url"] == record.canonical_url

    def test_get_spaces_url_by_sha256(self, store):
        record = _make_record()
        store.upsert_record(record)
        url = store.get_spaces_url_by_sha256(record.sha256)
        assert url == record.spaces_url

    def test_get_spaces_path_by_sha256(self, store):
        record = _make_record()
        store.upsert_record(record)
        path = store.get_spaces_path_by_sha256(record.sha256)
        assert path == record.spaces_path

    def test_unknown_sha256_returns_none(self, store):
        assert store.get_spaces_url_by_sha256("z" * 64) is None

    def test_upsert_updates_existing(self, store):
        record = _make_record()
        store.upsert_record(record)

        updated = _make_record(
            sha256="b" * 64,
            spaces_url="https://bucket.sgp1.digitaloceanspaces.com/gov-docs/rmp/raw/updated.html",
            spaces_path="gov-docs/rmp/raw/updated.html",
        )
        store.upsert_record(updated)

        row = store.get_by_url(record.canonical_url)
        assert row["sha256"] == "b" * 64

    def test_mark_inactive(self, store):
        record = _make_record()
        store.upsert_record(record)
        store.mark_inactive(record.canonical_url)
        row = store.get_by_url(record.canonical_url)
        assert row["status"] == "inactive"

    def test_two_different_urls_stored_separately(self, store):
        r1 = _make_record(
            record_id="id1",
            canonical_url="https://www.rmp.gov.my/url1",
            sha256="a" * 64,
        )
        r2 = _make_record(
            record_id="id2",
            canonical_url="https://www.rmp.gov.my/url2",
            sha256="b" * 64,
        )
        store.upsert_record(r1)
        store.upsert_record(r2)

        assert store.get_by_url(r1.canonical_url) is not None
        assert store.get_by_url(r2.canonical_url) is not None

    def test_save_and_retrieve_crawl_run(self, store):
        store.save_crawl_run(
            crawl_run_id="2026-03-09-rmp",
            site_slug="rmp",
            started_at="2026-03-09T01:00:00Z",
            completed_at="2026-03-09T01:30:00Z",
            new_count=10,
            changed_count=2,
            skipped_count=5,
            failed_count=0,
        )
        cur = store.conn.execute(
            "SELECT * FROM crawl_runs WHERE crawl_run_id = ?",
            ("2026-03-09-rmp",),
        )
        row = cur.fetchone()
        assert row is not None
        assert row["new_count"] == 10
        assert row["site_slug"] == "rmp"
