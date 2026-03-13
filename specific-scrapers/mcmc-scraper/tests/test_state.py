"""
Tests for the SQLite state store.
"""
import tempfile
from pathlib import Path

import pytest

from mcmc_scraper.models import Record
from mcmc_scraper.state import StateStore

PARSER_VERSION = "v1"


def _make_record(
    record_id: str = "rec001",
    canonical_url: str = "https://mcmc.gov.my/en/article/test",
    sha256: str = "abc123" * 10,
    spaces_url: str = "https://bucket.sgp1.digitaloceanspaces.com/gov-docs/mcmc/test.html",
    spaces_path: str = "gov-docs/mcmc/test.html",
) -> Record:
    return Record(
        record_id=record_id,
        source_url="https://mcmc.gov.my/en/media/press-releases",
        canonical_url=canonical_url,
        title="Test Article",
        published_at="2026-03-03",
        agency="MCMC",
        doc_type="press_release",
        content_type="text/html",
        language="en",
        sha256=sha256,
        spaces_bucket="test-bucket",
        spaces_path=spaces_path,
        spaces_url=spaces_url,
        http_etag='"abc"',
        http_last_modified="Mon, 03 Mar 2026 09:00:00 GMT",
        fetched_at="2026-03-04T00:00:00Z",
        crawl_run_id="2026-03-04-mcmc",
    )


@pytest.fixture()
def store(tmp_path: Path) -> StateStore:
    db = StateStore(tmp_path / "test.db")
    yield db
    db.close()


class TestStateStore:
    def test_get_by_url_not_found(self, store: StateStore):
        assert store.get_by_url("https://mcmc.gov.my/nonexistent") is None

    def test_upsert_and_get_by_url(self, store: StateStore):
        rec = _make_record()
        store.upsert_record(rec)
        row = store.get_by_url(rec.canonical_url)
        assert row is not None
        assert row["sha256"] == rec.sha256

    def test_get_spaces_url_by_sha256(self, store: StateStore):
        rec = _make_record()
        store.upsert_record(rec)
        result = store.get_spaces_url_by_sha256(rec.sha256)
        assert result == rec.spaces_url

    def test_get_spaces_url_by_sha256_not_found(self, store: StateStore):
        assert store.get_spaces_url_by_sha256("nonexistent") is None

    def test_get_spaces_path_by_sha256(self, store: StateStore):
        rec = _make_record()
        store.upsert_record(rec)
        result = store.get_spaces_path_by_sha256(rec.sha256)
        assert result == rec.spaces_path

    def test_upsert_updates_existing(self, store: StateStore):
        rec = _make_record()
        store.upsert_record(rec)

        updated = _make_record(sha256="def456" * 10, spaces_url="https://bucket.sgp1.digitaloceanspaces.com/gov-docs/mcmc/new.html")
        store.upsert_record(updated)

        row = store.get_by_url(rec.canonical_url)
        assert row["sha256"] == "def456" * 10

    def test_mark_inactive(self, store: StateStore):
        rec = _make_record()
        store.upsert_record(rec)
        store.mark_inactive(rec.canonical_url)
        row = store.get_by_url(rec.canonical_url)
        assert row["status"] == "inactive"

    def test_save_crawl_run(self, store: StateStore):
        store.save_crawl_run(
            crawl_run_id="2026-03-04-mcmc",
            site_slug="mcmc",
            started_at="2026-03-04T00:00:00Z",
            completed_at="2026-03-04T01:00:00Z",
            new_count=10,
            changed_count=2,
            skipped_count=5,
            failed_count=1,
        )
        cur = store.conn.execute(
            "SELECT * FROM crawl_runs WHERE crawl_run_id = ?",
            ("2026-03-04-mcmc",),
        )
        row = cur.fetchone()
        assert row is not None
        assert row["new_count"] == 10
        assert row["failed_count"] == 1

    def test_duplicate_url_raises_no_error(self, store: StateStore):
        """Upsert on duplicate canonical_url should not raise."""
        rec = _make_record()
        store.upsert_record(rec)
        store.upsert_record(rec)  # second call is idempotent
