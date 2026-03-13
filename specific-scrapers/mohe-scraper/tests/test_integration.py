"""Integration tests for the complete crawl pipeline."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from mohe_scraper.crawler import MOHECrawler
from mohe_scraper.state_manager import StateManager
from mohe_scraper.storage import LocalStorageBackend
from tests.fixtures import SAMPLE_RSS_FEED, SAMPLE_RSS_FEED_MS


@pytest.fixture
def config():
    """Base site configuration for testing."""
    return {
        "site": {
            "name": "Ministry of Higher Education Malaysia",
            "slug": "mohe",
            "domain": "www.mohe.gov.my",
            "base_url": "https://www.mohe.gov.my",
            "allowed_hosts": ["www.mohe.gov.my", "mohe.gov.my"],
        },
        "rss_feeds": [
            {
                "name": "announcements",
                "url_en": "https://www.mohe.gov.my/en/broadcast/announcements?format=feed&type=rss",
                "url_ms": "https://www.mohe.gov.my/ms/broadcast/announcements?format=feed&type=rss",
                "doc_type": "announcement",
            }
        ],
        "metadata": {
            "agency": "Ministry of Higher Education (MOHE)",
            "language_map": {"en": "en", "ms": "ms"},
        },
        "crawl": {
            "request_timeout": 30,
            "max_retries": 3,
            "retry_backoff_factor": 2,
            "batch_size": 50,
            "respect_robots_txt": True,
            "user_agent": "MOHEScraper/1.0 (test)",
        },
    }


@pytest.fixture
def temp_storage_dir():
    """Create temporary storage directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def temp_db(temp_storage_dir):
    """Create temporary state database."""
    return str(Path(temp_storage_dir) / "test_state.db")


class TestCrawlerIntegration:
    """Integration tests for crawler."""

    def test_crawl_rss_feeds_with_mocked_requests(self, config, temp_db, temp_storage_dir):
        """Test complete crawl pipeline with mocked HTTP requests."""
        # Setup
        state_manager = StateManager(temp_db)
        storage = LocalStorageBackend(temp_storage_dir)

        # Mock the _fetch_url method
        mock_response_headers = {
            "Content-Type": "application/rss+xml",
            "ETag": '"test-etag"',
            "Last-Modified": "Thu, 27 Feb 2026 10:00:00 GMT",
        }

        with patch.object(
            MOHECrawler,
            "_fetch_url",
            side_effect=[
                # English RSS feed, then its 2 article content fetches
                (SAMPLE_RSS_FEED, mock_response_headers),
                ("<html><body>Content 1</body></html>", {"Content-Type": "text/html"}),
                ("<html><body>Content 2</body></html>", {"Content-Type": "text/html"}),
                # Malay RSS feed, then its 1 article content fetch
                (SAMPLE_RSS_FEED_MS, mock_response_headers),
                ("<html><body>Content 3</body></html>", {"Content-Type": "text/html"}),
            ]
        ):
            crawler = MOHECrawler(config, state_manager, storage, dry_run=False)
            records = crawler.crawl_rss_feeds()

            # Verify results
            assert len(records) >= 3, "Should have created at least 3 records"

            # Check record fields
            for record in records:
                assert record.record_id
                assert record.source_url
                assert record.canonical_url
                assert record.title
                assert record.agency == "Ministry of Higher Education (MOHE)"
                assert record.doc_type == "announcement"
                assert record.language in ["en", "ms"]
                assert record.sha256
                assert record.fetched_at
                assert record.crawl_run_id

            # Check crawl run stats
            assert crawler.crawl_run.total_items_fetched >= 3
            assert crawler.crawl_run.total_urls_discovered >= 2

    def test_deduplication_by_url(self, config, temp_db, temp_storage_dir):
        """Test that duplicate URLs are skipped."""
        state_manager = StateManager(temp_db)
        storage = LocalStorageBackend(temp_storage_dir)

        mock_headers = {
            "Content-Type": "application/rss+xml",
            "ETag": '"test-etag"',
        }

        with patch.object(
            MOHECrawler,
            "_fetch_url",
            side_effect=[
                # First crawl: EN RSS + 2 content fetches + MS RSS + 1 content fetch
                (SAMPLE_RSS_FEED, mock_headers),
                ("<html>Content</html>", {"Content-Type": "text/html"}),
                ("<html>Content</html>", {"Content-Type": "text/html"}),
                (SAMPLE_RSS_FEED_MS, mock_headers),
                ("<html>Content</html>", {"Content-Type": "text/html"}),
                # Second crawl: EN RSS + MS RSS (all items deduped, no content fetches)
                (SAMPLE_RSS_FEED, mock_headers),
                (SAMPLE_RSS_FEED_MS, mock_headers),
            ]
        ):
            # First crawl
            crawler1 = MOHECrawler(config, state_manager, storage, dry_run=False)
            records1 = crawler1.crawl_rss_feeds()
            count1 = len(records1)

            # Second crawl (should see dedup)
            crawler2 = MOHECrawler(config, state_manager, storage, dry_run=False)
            records2 = crawler2.crawl_rss_feeds()

            # Second crawl should have deduped records
            assert crawler2.crawl_run.total_items_deduped > 0

    def test_dry_run_mode(self, config, temp_db, temp_storage_dir):
        """Test that dry-run mode doesn't store files."""
        state_manager = StateManager(temp_db)
        storage = LocalStorageBackend(temp_storage_dir)

        mock_headers = {
            "Content-Type": "application/rss+xml",
            "ETag": '"test-etag"',
        }

        with patch.object(
            MOHECrawler,
            "_fetch_url",
            side_effect=[
                (SAMPLE_RSS_FEED, mock_headers),
                ("<html>Content</html>", {"Content-Type": "text/html"}),
            ]
        ):
            crawler = MOHECrawler(config, state_manager, storage, dry_run=True)
            records = crawler.crawl_rss_feeds()

            # In dry-run, records should have no GCS URIs
            for record in records:
                assert record.gcs_uri is None
                assert record.gcs_object is None

            # But metadata should still be collected
            assert len(records) > 0

    def test_output_record_schema(self, config, temp_db, temp_storage_dir):
        """Test that output records match required schema."""
        state_manager = StateManager(temp_db)
        storage = LocalStorageBackend(temp_storage_dir)

        mock_headers = {
            "Content-Type": "text/html",
            "ETag": '"abc123"',
            "Last-Modified": "Thu, 27 Feb 2026 10:00:00 GMT",
        }

        with patch.object(
            MOHECrawler,
            "_fetch_url",
            side_effect=[
                (SAMPLE_RSS_FEED, mock_headers),
                ("<html>Content</html>", {"Content-Type": "text/html"}),
                ("<html>Content</html>", {"Content-Type": "text/html"}),
            ]
        ):
            crawler = MOHECrawler(config, state_manager, storage, dry_run=False)
            records = crawler.crawl_rss_feeds()

            # Check schema
            for record in records[:1]:  # Check first record
                required_fields = [
                    "record_id", "source_url", "canonical_url",
                    "title", "published_at", "agency", "doc_type",
                    "content_type", "language", "sha256", "fetched_at"
                ]
                for field in required_fields:
                    assert hasattr(record, field), f"Missing field: {field}"
                    assert getattr(record, field) is not None, f"Field {field} is None"

    def test_language_separation(self, config, temp_db, temp_storage_dir):
        """Test that English and Malay content are kept separate."""
        state_manager = StateManager(temp_db)
        storage = LocalStorageBackend(temp_storage_dir)

        mock_headers = {
            "Content-Type": "text/html",
            "ETag": '"test"',
        }

        with patch.object(
            MOHECrawler,
            "_fetch_url",
            side_effect=[
                # EN RSS feed, then its 2 article content fetches
                (SAMPLE_RSS_FEED, mock_headers),
                ("<html>Content EN</html>", {"Content-Type": "text/html"}),
                ("<html>Content EN</html>", {"Content-Type": "text/html"}),
                # MS RSS feed, then its 1 article content fetch
                (SAMPLE_RSS_FEED_MS, mock_headers),
                ("<html>Content MS</html>", {"Content-Type": "text/html"}),
            ]
        ):
            crawler = MOHECrawler(config, state_manager, storage, dry_run=False)
            records = crawler.crawl_rss_feeds()

            en_records = [r for r in records if r.language == "en"]
            ms_records = [r for r in records if r.language == "ms"]

            assert len(en_records) > 0, "Should have English records"
            assert len(ms_records) > 0, "Should have Malay records"

    def test_crawl_run_completion(self, config, temp_db, temp_storage_dir):
        """Test that crawl run is properly finalized."""
        state_manager = StateManager(temp_db)
        storage = LocalStorageBackend(temp_storage_dir)

        mock_headers = {"Content-Type": "text/html"}

        with patch.object(
            MOHECrawler,
            "_fetch_url",
            side_effect=[
                (SAMPLE_RSS_FEED, mock_headers),
                ("<html>Content</html>", mock_headers),
                ("<html>Content</html>", mock_headers),
            ]
        ):
            crawler = MOHECrawler(config, state_manager, storage, dry_run=True)
            records = crawler.crawl_rss_feeds()
            crawler.finalize_crawl_run()

            summary = crawler.get_crawl_run_summary()

            # Check summary fields
            assert summary["status"] == "completed"
            assert summary["started_at"]
            assert summary["completed_at"]
            assert summary["total_urls_discovered"] >= 0
            assert summary["total_items_fetched"] >= 0
            assert summary["crawl_run_id"]
