"""Tests for deduplication store."""
import pytest
import tempfile
from pathlib import Path
from src.deduplication import DeduplicationStore


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite3"
        yield str(db_path)


class TestDeduplicationStore:
    def test_url_exists(self, temp_db):
        store = DeduplicationStore(temp_db)
        url = "https://perpaduan.gov.my/page1"

        # URL doesn't exist initially
        assert not store.url_exists(url)

        # Store URL
        store.store_url(url, url)

        # Now it exists
        assert store.url_exists(url)

    def test_hash_exists(self, temp_db):
        store = DeduplicationStore(temp_db)
        sha256 = "abc123def456"
        spaces_path = "gov-my/perpaduan/2026-03/abc123.pdf"

        # Hash doesn't exist
        result = store.hash_exists(sha256)
        assert result is None

        # Store hash
        store.store_hash(sha256, spaces_path, "application/pdf")

        # Now hash exists and returns spaces_path
        result = store.hash_exists(sha256)
        assert result == spaces_path

    def test_crawl_run_lifecycle(self, temp_db):
        store = DeduplicationStore(temp_db)
        crawl_id = "2026-03-09-perpaduan"

        # Start run
        store.start_crawl_run(crawl_id, "perpaduan")

        # Update metrics
        store.update_crawl_run(
            crawl_id,
            discovered=100,
            fetched=95,
            deduped=5,
        )

        # End run
        store.end_crawl_run(crawl_id)

        # Verify (basic - just check no exceptions)
        assert True

    def test_etag_tracking(self, temp_db):
        store = DeduplicationStore(temp_db)
        url = "https://perpaduan.gov.my/page"
        etag = '"abc123"'
        last_modified = "Wed, 09 Mar 2026 12:00:00 GMT"

        store.store_url(url, url, etag=etag, last_modified=last_modified)

        retrieved_etag, retrieved_lm = store.get_url_headers(url)
        assert retrieved_etag == etag
        assert retrieved_lm == last_modified
