"""Main web crawler for MOHE documents and announcements."""

import hashlib
import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tenacity import retry, stop_after_attempt, wait_exponential

from mohe_scraper.models import ScraperRecord, CrawlRun, StateRecord, generate_record_id, generate_gcs_path
from mohe_scraper.url_utils import URLNormalizer, URLExtractor
from mohe_scraper.state_manager import StateManager
from mohe_scraper.storage import StorageFactory, StorageBackend
from mohe_scraper.parsers import RSSParser, HTMLParser, DateParser

logger = logging.getLogger(__name__)


class MOHECrawler:
    """Main crawler for MOHE website."""

    def __init__(
        self,
        config: dict,
        state_manager: StateManager,
        storage: StorageBackend,
        dry_run: bool = False,
    ):
        """
        Initialize crawler.

        Args:
            config: Site configuration dict
            state_manager: StateManager instance for dedup
            storage: StorageBackend instance for file storage
            dry_run: If True, don't write files
        """
        self.config = config
        self.state_manager = state_manager
        self.storage = storage
        self.dry_run = dry_run

        self.url_normalizer = URLNormalizer(config["site"]["allowed_hosts"])
        self.session = self._create_session(config["crawl"])

        # Initialize crawl run tracking
        now = datetime.utcnow()
        self.crawl_run_id = f"{now.strftime('%Y-%m-%d')}-{config['site']['slug']}"
        self.crawl_run = CrawlRun(
            crawl_run_id=self.crawl_run_id,
            site_slug=config["site"]["slug"],
            started_at=now.isoformat() + "Z",
            dry_run=dry_run,
        )

    @staticmethod
    def _create_session(crawl_config: dict) -> requests.Session:
        """Create requests session with retry strategy."""
        session = requests.Session()

        # Configure retry strategy
        retry_strategy = Retry(
            total=crawl_config["max_retries"],
            backoff_factor=crawl_config["retry_backoff_factor"],
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        session.headers.update({
            "User-Agent": crawl_config["user_agent"]
        })

        return session

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _fetch_url(self, url: str) -> Optional[tuple]:
        """
        Fetch URL with retry logic.

        Args:
            url: URL to fetch

        Returns:
            Tuple of (content, headers) or None if failed
        """
        try:
            response = self.session.get(
                url,
                timeout=self.config["crawl"]["request_timeout"],
                allow_redirects=True
            )
            response.raise_for_status()

            # Only process text content for HTML/XML, binary for files
            if "text" in response.headers.get("Content-Type", ""):
                return response.text, response.headers
            else:
                return response.content, response.headers

        except requests.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            self.crawl_run.total_items_failed += 1
            self.crawl_run.errors.append({"url": url, "error": str(e), "type": "network"})
            raise

    def crawl_rss_feeds(self) -> List[ScraperRecord]:
        """
        Crawl RSS feeds (preferred machine-readable source).

        Returns:
            List of ScraperRecord objects
        """
        records = []
        languages = ["en", "ms"]  # Both languages

        for feed in self.config["rss_feeds"]:
            for lang in languages:
                feed_url_key = f"url_{lang}"
                if feed_url_key not in feed:
                    continue

                feed_url = feed[feed_url_key]
                logger.info(f"Crawling RSS feed: {feed_url}")

                try:
                    content, headers = self._fetch_url(feed_url)
                    self.crawl_run.total_urls_discovered += 1

                    # Parse RSS feed
                    items = RSSParser.parse_feed(content)

                    for item in items:
                        try:
                            record = self._create_record_from_rss_item(
                                item, feed, lang, feed_url
                            )
                            if record:
                                records.append(record)
                                self.crawl_run.total_items_fetched += 1
                        except Exception as e:
                            logger.warning(f"Failed to create record from RSS item: {e}")
                            self.crawl_run.total_items_failed += 1

                except Exception as e:
                    logger.error(f"Failed to crawl RSS feed {feed_url}: {e}")
                    self.crawl_run.errors.append({
                        "url": feed_url,
                        "error": str(e),
                        "type": "rss_parse"
                    })

        return records

    def _create_record_from_rss_item(
        self, item: dict, feed_config: dict, language: str, feed_url: str
    ) -> Optional[ScraperRecord]:
        """
        Create ScraperRecord from RSS item.

        Args:
            item: RSS item dict
            feed_config: Feed configuration
            language: Language code
            feed_url: The feed URL (for tracking)

        Returns:
            ScraperRecord or None
        """
        source_url = item.get("link")
        if not source_url:
            return None

        # Resolve relative URLs
        source_url = urljoin(self.config["site"]["base_url"], source_url)

        # Canonicalize URL
        canonical_url = self.url_normalizer.canonicalize(source_url)
        if not canonical_url:
            logger.warning(f"URL not in allowed hosts: {source_url}")
            return None

        # Check for duplicate by URL
        existing = self.state_manager.check_url_exists(canonical_url)
        if existing:
            logger.debug(f"URL already exists (skipping): {canonical_url}")
            self.crawl_run.total_items_deduped += 1
            return None

        # Fetch the actual document/page content
        try:
            content, headers = self._fetch_url(source_url)
        except Exception as e:
            logger.warning(f"Failed to fetch document: {source_url}: {e}")
            return None

        # Compute hash
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = content

        sha256 = hashlib.sha256(content_bytes).hexdigest()

        # Check for duplicate by hash (content dedup)
        existing_hash = self.state_manager.check_hash_exists(sha256)
        if existing_hash:
            logger.debug(f"Content hash already exists: {sha256}, reusing {existing_hash.gcs_uri}")
            self.crawl_run.total_items_deduped += 1
            # Return record with existing GCS URI
            return self._create_record_with_existing_gcs(
                existing_hash, source_url, canonical_url, item, feed_config, language
            )

        # Parse publication date
        pub_date = RSSParser.parse_date(item.get("pubDate"))

        # Determine content type
        content_type = headers.get("Content-Type", "text/html").split(";")[0]

        # Create record
        record_id = generate_record_id(canonical_url, language)
        now = datetime.utcnow()
        fetched_at = now.isoformat() + "Z"

        # Store original file if not dry_run
        gcs_uri = None
        gcs_object = None
        if not self.dry_run:
            filename = URLExtractor.extract_filename_from_url(source_url)
            gcs_object = generate_gcs_path(self.config["site"]["slug"], sha256, filename)
            gcs_uri = self.storage.store(content_bytes, gcs_object)
            self.crawl_run.total_items_uploaded += 1

        # Extract ETag and Last-Modified
        etag = headers.get("ETag")
        last_modified = headers.get("Last-Modified")

        record = ScraperRecord(
            record_id=record_id,
            source_url=source_url,
            canonical_url=canonical_url,
            title=item.get("title", "Untitled").strip(),
            published_at=pub_date,
            agency=self.config["metadata"]["agency"],
            doc_type=feed_config["doc_type"],
            content_type=content_type,
            language=language,
            sha256=sha256,
            fetched_at=fetched_at,
            http_etag=etag,
            http_last_modified=last_modified,
            gcs_bucket=self.storage.bucket_name if hasattr(self.storage, 'bucket_name') else None,
            gcs_object=gcs_object,
            gcs_uri=gcs_uri,
            crawl_run_id=self.crawl_run_id,
        )

        # Save to state
        state_record = StateRecord(
            canonical_url=canonical_url,
            sha256=sha256,
            http_etag=etag,
            http_last_modified=last_modified,
            gcs_uri=gcs_uri,
            last_seen_at=fetched_at,
            doc_type=feed_config["doc_type"],
            title=item.get("title", "Untitled").strip(),
        )
        self.state_manager.save_record(state_record)

        return record

    def _create_record_with_existing_gcs(
        self,
        existing: StateRecord,
        source_url: str,
        canonical_url: str,
        item: dict,
        feed_config: dict,
        language: str,
    ) -> ScraperRecord:
        """Create record reusing existing GCS URI."""
        record_id = generate_record_id(canonical_url, language)
        now = datetime.utcnow()
        fetched_at = now.isoformat() + "Z"

        pub_date = RSSParser.parse_date(item.get("pubDate"))

        return ScraperRecord(
            record_id=record_id,
            source_url=source_url,
            canonical_url=canonical_url,
            title=item.get("title", "Untitled").strip(),
            published_at=pub_date,
            agency=self.config["metadata"]["agency"],
            doc_type=feed_config["doc_type"],
            content_type="text/html",
            language=language,
            sha256=existing.sha256,
            fetched_at=fetched_at,
            http_etag=existing.http_etag,
            http_last_modified=existing.http_last_modified,
            gcs_bucket=existing.gcs_uri.split("/")[2] if existing.gcs_uri else None,
            gcs_object=None,
            gcs_uri=existing.gcs_uri,
            crawl_run_id=self.crawl_run_id,
        )

    def crawl_html_listing_pages(self) -> List[ScraperRecord]:
        """
        Crawl HTML listing pages for staff downloads (DOCman, no RSS available).

        Returns:
            List of ScraperRecord objects
        """
        records = []
        listing_pages = self.config.get("listing_pages", [])

        for page_config in listing_pages:
            # Build (url, language) pairs from whichever URL keys are present
            urls_to_crawl = []
            if "url_ms" in page_config:
                urls_to_crawl.append((page_config["url_ms"], "ms"))
            if "url_en" in page_config:
                urls_to_crawl.append((page_config["url_en"], "en"))

            for listing_url, lang in urls_to_crawl:
                # Skip JS-rendered pages until Playwright support is added
                if page_config.get("playwright_required", False):
                    logger.warning(
                        f"Skipping JS-rendered page (playwright_required=true): {listing_url}"
                    )
                    continue

                logger.info(f"Crawling HTML listing page: {listing_url}")

                try:
                    content, headers = self._fetch_url(listing_url)
                    self.crawl_run.total_urls_discovered += 1
                except Exception as e:
                    logger.error(f"Failed to fetch listing page {listing_url}: {e}")
                    self.crawl_run.errors.append({
                        "url": listing_url,
                        "error": str(e),
                        "type": "html_listing_fetch",
                    })
                    continue

                items = HTMLParser.parse_listing_page(content, page_config["selectors"])

                for item in items:
                    try:
                        record = self._create_record_from_html_item(
                            item, page_config, lang, listing_url
                        )
                        if record:
                            records.append(record)
                            self.crawl_run.total_items_fetched += 1
                    except Exception as e:
                        logger.warning(
                            f"Failed to create record from HTML item "
                            f"'{item.get('title', '?')}': {e}"
                        )
                        self.crawl_run.total_items_failed += 1

        return records

    def _create_record_from_html_item(
        self,
        item: dict,
        page_config: dict,
        language: str,
        listing_url: str,
    ) -> Optional[ScraperRecord]:
        """
        Create ScraperRecord from a parsed HTML listing item (DOCman).

        For DOCman pages the item link IS the binary file endpoint (/file suffix),
        so we fetch it directly — there is no intermediate HTML detail page.

        Args:
            item: Parsed HTML item dict (title, link, published_date, is_file_download)
            page_config: Listing page configuration entry
            language: Language code ('ms' or 'en')
            listing_url: Parent listing page URL (for logging context)

        Returns:
            ScraperRecord or None if skipped/failed
        """
        raw_link = item.get("link")
        if not raw_link:
            return None

        # Resolve relative URL against site base_url
        source_url = urljoin(self.config["site"]["base_url"], raw_link)

        # Canonicalize and validate host
        canonical_url = self.url_normalizer.canonicalize(source_url)
        if not canonical_url:
            logger.warning(f"URL not in allowed hosts: {source_url}")
            return None

        # Dedup by canonical URL
        if self.state_manager.check_url_exists(canonical_url):
            logger.debug(f"URL already exists (skipping): {canonical_url}")
            self.crawl_run.total_items_deduped += 1
            return None

        # Fetch the file (binary PDF/DOC or text HTML)
        try:
            content, headers = self._fetch_url(source_url)
        except Exception as e:
            logger.warning(f"Failed to fetch document {source_url}: {e}")
            return None

        # Normalise to bytes for hashing and storage
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = content

        sha256 = hashlib.sha256(content_bytes).hexdigest()

        # Dedup by content hash — reuse existing storage if same bytes seen before
        existing_hash = self.state_manager.check_hash_exists(sha256)
        if existing_hash:
            logger.debug(f"Content hash already exists: {sha256}")
            self.crawl_run.total_items_deduped += 1
            record_id = generate_record_id(canonical_url, language)
            now = datetime.utcnow()
            fetched_at = now.isoformat() + "Z"
            pub_date = DateParser.parse(item.get("published_date"), language=language)
            content_type = headers.get("Content-Type", "application/octet-stream").split(";")[0]
            return ScraperRecord(
                record_id=record_id,
                source_url=source_url,
                canonical_url=canonical_url,
                title=item.get("title", "Untitled").strip(),
                published_at=pub_date,
                agency=self.config["metadata"]["agency"],
                doc_type=page_config["doc_type"],
                content_type=content_type,
                language=language,
                sha256=sha256,
                fetched_at=fetched_at,
                http_etag=existing_hash.http_etag,
                http_last_modified=existing_hash.http_last_modified,
                gcs_bucket=existing_hash.gcs_uri.split("/")[2] if existing_hash.gcs_uri else None,
                gcs_object=None,
                gcs_uri=existing_hash.gcs_uri,
                crawl_run_id=self.crawl_run_id,
            )

        # Parse date with Malay-aware parser
        pub_date = DateParser.parse(item.get("published_date"), language=language)

        # Prefer HTTP Content-Type header; fall back to URL-based inference
        raw_ct = headers.get("Content-Type", "")
        content_type = raw_ct.split(";")[0] if raw_ct else URLExtractor.get_content_type_from_url(source_url)

        record_id = generate_record_id(canonical_url, language)
        now = datetime.utcnow()
        fetched_at = now.isoformat() + "Z"
        etag = headers.get("ETag")
        last_modified = headers.get("Last-Modified")

        # Store file unless dry-run
        gcs_uri = None
        gcs_object = None
        if not self.dry_run:
            filename = URLExtractor.extract_filename_from_url(source_url)
            gcs_object = generate_gcs_path(self.config["site"]["slug"], sha256, filename)
            gcs_uri = self.storage.store(content_bytes, gcs_object)
            self.crawl_run.total_items_uploaded += 1

        record = ScraperRecord(
            record_id=record_id,
            source_url=source_url,
            canonical_url=canonical_url,
            title=item.get("title", "Untitled").strip(),
            published_at=pub_date,
            agency=self.config["metadata"]["agency"],
            doc_type=page_config["doc_type"],
            content_type=content_type,
            language=language,
            sha256=sha256,
            fetched_at=fetched_at,
            http_etag=etag,
            http_last_modified=last_modified,
            gcs_bucket=self.storage.bucket_name if hasattr(self.storage, "bucket_name") else None,
            gcs_object=gcs_object,
            gcs_uri=gcs_uri,
            crawl_run_id=self.crawl_run_id,
        )

        self.state_manager.save_record(StateRecord(
            canonical_url=canonical_url,
            sha256=sha256,
            http_etag=etag,
            http_last_modified=last_modified,
            gcs_uri=gcs_uri,
            last_seen_at=fetched_at,
            doc_type=page_config["doc_type"],
            title=item.get("title", "Untitled").strip(),
        ))

        return record

    def finalize_crawl_run(self):
        """Finalize the crawl run with completion stats."""
        now = datetime.utcnow()
        self.crawl_run.completed_at = now.isoformat() + "Z"
        self.crawl_run.status = "completed"

    def get_crawl_run_summary(self) -> dict:
        """Get summary statistics of crawl run."""
        return {
            "crawl_run_id": self.crawl_run.crawl_run_id,
            "site_slug": self.crawl_run.site_slug,
            "started_at": self.crawl_run.started_at,
            "completed_at": self.crawl_run.completed_at,
            "status": self.crawl_run.status,
            "total_urls_discovered": self.crawl_run.total_urls_discovered,
            "total_items_fetched": self.crawl_run.total_items_fetched,
            "total_items_uploaded": self.crawl_run.total_items_uploaded,
            "total_items_deduped": self.crawl_run.total_items_deduped,
            "total_items_failed": self.crawl_run.total_items_failed,
            "dry_run": self.crawl_run.dry_run,
            "errors": self.crawl_run.errors[:10],  # First 10 errors
        }
