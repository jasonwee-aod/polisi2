"""Tests for the SQLite state store and deduplication logic."""
import os
import tempfile

import pytest

from kpkt_scraper.models import Record
from kpkt_scraper.state import StateStore


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_record(url: str, sha256: str, title: str = "Test doc") -> Record:
    sha_prefix = sha256[:16]
    return Record(
        record_id=f"{sha_prefix}-abcd1234",
        source_url="https://www.kpkt.gov.my/test-listing",
        canonical_url=url,
        title=title,
        published_at="2025-12-04",
        agency="Kementerian Perumahan dan Kerajaan Tempatan",
        doc_type="press_release",
        content_type="application/pdf",
        language="ms",
        sha256=sha256,
        gcs_bucket="test-bucket",
        gcs_object=f"gov-docs/kpkt/raw/2025/12/04/{sha256}_doc.pdf",
        gcs_uri=f"gs://test-bucket/gov-docs/kpkt/raw/2025/12/04/{sha256}_doc.pdf",
        http_etag='"etag-abc"',
        http_last_modified="Wed, 04 Dec 2025 00:00:00 GMT",
        fetched_at="2025-12-04T10:00:00Z",
        crawl_run_id="2025-12-04-kpkt",
    )


@pytest.fixture
def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as fh:
        db_path = fh.name
    state = StateStore(db_path)
    yield state
    state.close()
    os.unlink(db_path)


# ── get_by_url ────────────────────────────────────────────────────────────────


def test_get_by_url_miss(store):
    assert store.get_by_url("https://www.kpkt.gov.my/unknown.pdf") is None


def test_upsert_then_get_by_url(store):
    record = _make_record("https://www.kpkt.gov.my/doc1.pdf", "a" * 64)
    store.upsert_record(record)
    row = store.get_by_url("https://www.kpkt.gov.my/doc1.pdf")
    assert row is not None
    assert row["sha256"] == "a" * 64
    assert row["status"] == "active"


# ── get_gcs_uri_by_sha256 ─────────────────────────────────────────────────────


def test_get_gcs_uri_miss(store):
    assert store.get_gcs_uri_by_sha256("b" * 64) is None


def test_get_gcs_uri_hit(store):
    sha = "c" * 64
    record = _make_record("https://www.kpkt.gov.my/doc2.pdf", sha)
    store.upsert_record(record)
    result = store.get_gcs_uri_by_sha256(sha)
    assert result == record.gcs_uri


# ── upsert semantics ──────────────────────────────────────────────────────────


def test_upsert_updates_existing_url(store):
    """Second upsert with same canonical_url should update the row."""
    url = "https://www.kpkt.gov.my/doc3.pdf"
    store.upsert_record(_make_record(url, "d" * 64, "Original title"))
    store.upsert_record(_make_record(url, "e" * 64, "Updated title"))
    row = store.get_by_url(url)
    assert row["sha256"] == "e" * 64


def test_dedup_sha256_reuse(store):
    """Same sha256 should return the gcs_uri of the first stored record."""
    sha = "f" * 64
    r1 = _make_record("https://www.kpkt.gov.my/doc4.pdf", sha)
    store.upsert_record(r1)
    # A second document with the same content hash should reuse the URI
    existing_uri = store.get_gcs_uri_by_sha256(sha)
    assert existing_uri == r1.gcs_uri


# ── mark_inactive ─────────────────────────────────────────────────────────────


def test_mark_inactive(store):
    url = "https://www.kpkt.gov.my/doc5.pdf"
    store.upsert_record(_make_record(url, "g" * 64))
    store.mark_inactive(url)
    row = store.get_by_url(url)
    assert row["status"] == "inactive"


# ── save_crawl_run ────────────────────────────────────────────────────────────


def test_save_crawl_run(store):
    store.save_crawl_run(
        crawl_run_id="2025-12-04-kpkt",
        site_slug="kpkt",
        started_at="2025-12-04T10:00:00Z",
        completed_at="2025-12-04T10:05:00Z",
        new_count=10,
        changed_count=2,
        skipped_count=5,
        failed_count=1,
    )
    cur = store.conn.execute(
        "SELECT * FROM crawl_runs WHERE crawl_run_id = '2025-12-04-kpkt'"
    )
    row = cur.fetchone()
    assert row is not None
    assert row["new_count"] == 10
    assert row["failed_count"] == 1
