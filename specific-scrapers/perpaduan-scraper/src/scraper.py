"""Main scraper orchestration."""
import logging
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Set
import yaml

from src.crawler import Crawler
from src.url_utils import canonicalize_url
from src.deduplication import DeduplicationStore
from src.models import ScrapedRecord, CrawlRun


logger = logging.getLogger(__name__)


class PerpaduanScraper:
    """Orchestrator for Perpaduan website scraping."""

    def __init__(
        self,
        config_path: str,
        state_db: str = ".cache/scraper_state.sqlite3",
        output_dir: str = "data/manifests/perpaduan",
        dry_run: bool = False,
    ):
        self.config = self._load_config(config_path)
        self.dedup = DeduplicationStore(state_db)
        self.crawler = Crawler(
            allowed_hosts=self.config.get("allowed_hosts", ["www.perpaduan.gov.my"]),
            user_agent=self.config.get("user_agent"),
            timeout=self.config.get("timeout", 10),
            delay=self.config.get("delay", 1.0),
        )
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.dry_run = dry_run

        # Initialize spaces if not dry-run
        self.spaces = None
        if not dry_run:
            try:
                from src.spaces import SpacesArchive
                self.spaces = SpacesArchive()
            except ValueError:
                logger.warning("Spaces not configured, will skip uploads")

        # Initialize crawl run
        self.crawl_run_id = datetime.utcnow().strftime("%Y-%m-%d") + "-perpaduan"
        self.dedup.start_crawl_run(self.crawl_run_id, "perpaduan")

        # Metrics
        self.discovered = set()
        self.fetched = 0
        self.uploaded = 0
        self.deduped = 0
        self.failed = 0
        self.records = []

    def _load_config(self, config_path: str) -> dict:
        """Load site configuration from YAML."""
        with open(config_path) as f:
            return yaml.safe_load(f)

    def run(self, max_pages: int = None) -> dict:
        """Execute scraping workflow."""
        logger.info("Starting Perpaduan scraper")

        # Discover URLs from sections
        for section in self.config.get("sections", []):
            self._crawl_section(section, max_pages)

        # Write output files
        self._write_output()

        # Finalize
        self.dedup.end_crawl_run(self.crawl_run_id)

        summary = {
            "crawl_run_id": self.crawl_run_id,
            "discovered": len(self.discovered),
            "fetched": self.fetched,
            "uploaded": self.uploaded,
            "deduped": self.deduped,
            "failed": self.failed,
            "records_written": len(self.records),
        }

        logger.info(f"Scrape complete: {summary}")
        return summary

    def _crawl_section(self, section: dict, max_pages: int = None):
        """Crawl a single section."""
        section_url = section.get("url")
        if not section_url:
            logger.warning(f"Section missing URL: {section}")
            return

        logger.info(f"Crawling section: {section.get('name')} ({section_url})")

        pages_crawled = 0
        to_visit = {canonicalize_url(section_url, self.crawler.allowed_hosts)}
        visited = set()

        while to_visit and (not max_pages or pages_crawled < max_pages):
            url = to_visit.pop()
            if url in visited:
                continue

            visited.add(url)
            pages_crawled += 1

            try:
                self._process_url(url, section)

                # Extract detail pages from listing
                if section.get("has_detail_pages"):
                    detail_selector = section.get("detail_link_selector", "a.item-link")
                    fetched = self.crawler.fetch(url)
                    if fetched:
                        soup = self.crawler.parse_html(fetched["content"])
                        if soup:
                            detail_links = self.crawler.extract_links(
                                soup, url, detail_selector
                            )
                            for link in detail_links:
                                if link not in visited:
                                    to_visit.add(link)

            except Exception as e:
                logger.error(f"Failed to process {url}: {e}")
                self.failed += 1

    def _process_url(self, url: str, section: dict):
        """Process a single URL and extract records."""
        canonical = canonicalize_url(url, self.crawler.allowed_hosts)
        if not canonical:
            return

        self.discovered.add(canonical)

        # Check if already processed
        if self.dedup.url_exists(canonical):
            logger.debug(f"URL already processed: {canonical}")
            self.deduped += 1
            return

        # Fetch
        try:
            fetched = self.crawler.fetch(canonical)
            if not fetched:
                self.failed += 1
                return
        except Exception as e:
            logger.warning(f"Fetch failed {canonical}: {e}")
            self.failed += 1
            return

        self.fetched += 1

        # Parse
        soup = self.crawler.parse_html(fetched["content"])
        if not soup:
            self.failed += 1
            return

        # Extract records from this page
        items = self._extract_items(soup, section, fetched.get("url", canonical))

        for item in items:
            record = self._create_record(item, section, fetched)
            if record:
                self.records.append(record)

                # Upload if not dry-run
                if not self.dry_run and self.spaces and item.get("file_bytes"):
                    try:
                        upload_result = self.spaces.upload_file(
                            item["file_bytes"],
                            item.get("filename", "document"),
                            item.get("content_type", "text/html"),
                        )
                        record.sha256 = upload_result["sha256"]
                        record.spaces_path = upload_result["spaces_path"]
                        record.spaces_url = upload_result["spaces_url"]
                        record.spaces_bucket = self.spaces.bucket
                        self.uploaded += 1
                    except Exception as e:
                        logger.error(f"Upload failed: {e}")

                # Store in dedup
                self.dedup.store_url(
                    record.canonical_url,
                    record.source_url,
                    etag=record.http_etag,
                    last_modified=record.http_last_modified,
                )

                if record.sha256:
                    self.dedup.store_hash(
                        record.sha256,
                        record.spaces_path,
                        record.content_type,
                    )

    def _extract_items(self, soup, section: dict, base_url: str = None) -> list:
        """Extract items from page based on section config."""
        items = []

        # List page selector
        item_selector = section.get("item_selector", "div.item")
        for elem in soup.select(item_selector):
            item = {}

            # Title
            title_selector = section.get("title_selector", "h3")
            title = self.crawler.extract_text(elem, title_selector)
            if not title:
                continue
            item["title"] = title

            # URL
            link_selector = section.get("link_selector", "a")
            link_elem = elem.select_one(link_selector)
            if link_elem:
                href = link_elem.get("href")
                if href:
                    # Convert relative URLs to absolute
                    from src.url_utils import extract_absolute_url
                    abs_url = extract_absolute_url(href, base_url or self.config.get("base_url"))
                    if abs_url:
                        item["url"] = abs_url

            # Date
            date_selector = section.get("date_selector")
            if date_selector:
                date_str = self.crawler.extract_text(elem, date_selector)
                if date_str:
                    item["published_at"] = self.crawler.extract_published_date(date_str)

            # Doc type
            item["doc_type"] = section.get("doc_type", "news")

            if item.get("url"):  # Only add if URL is valid
                items.append(item)

        return items

    def _create_record(self, item: dict, section: dict, fetched: dict) -> Optional[ScrapedRecord]:
        """Create a ScrapedRecord from extracted item."""
        if not item.get("url"):
            return None

        source_url = item["url"]
        canonical_url = canonicalize_url(
            source_url,
            self.crawler.allowed_hosts
        )

        if not canonical_url:
            return None

        # For this initial version, store HTML as content
        file_bytes = fetched.get("content", b"")
        sha256 = hashlib.sha256(file_bytes).hexdigest()

        record = ScrapedRecord(
            source_url=source_url,
            canonical_url=canonical_url,
            title=item.get("title", "Untitled"),
            published_at=item.get("published_at"),
            agency=section.get("agency", "Kementerian Perpaduan Negara"),
            doc_type=item.get("doc_type", "news"),
            content_type=fetched.get("content_type", "text/html"),
            language="ms",
            sha256=sha256,
            http_etag=fetched.get("etag"),
            http_last_modified=fetched.get("last_modified"),
            crawl_run_id=self.crawl_run_id,
        )

        return record

    def _write_output(self):
        """Write records.jsonl and crawl_runs.jsonl."""
        # Write records
        records_path = self.output_dir / "records.jsonl"
        with open(records_path, "w") as f:
            for record in self.records:
                f.write(record.to_json() + "\n")

        logger.info(f"Wrote {len(self.records)} records to {records_path}")

        # Write crawl run summary
        run_summary = CrawlRun(
            crawl_run_id=self.crawl_run_id,
            site_slug="perpaduan",
            started_at=datetime.utcnow().isoformat() + "Z",
            completed_at=datetime.utcnow().isoformat() + "Z",
            discovered=len(self.discovered),
            fetched=self.fetched,
            uploaded=self.uploaded,
            deduped=self.deduped,
            failed=self.failed,
        )

        runs_path = self.output_dir / "crawl_runs.jsonl"
        with open(runs_path, "a") as f:
            f.write(run_summary.to_json() + "\n")

        logger.info(f"Wrote crawl run summary to {runs_path}")
