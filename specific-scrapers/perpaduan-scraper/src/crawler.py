"""HTTP crawler and HTML parser."""
import logging
import time
from typing import Optional, Set
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential
from datetime import datetime
from dateutil import parser as date_parser

from src.url_utils import canonicalize_url, extract_absolute_url


logger = logging.getLogger(__name__)


class Crawler:
    """HTTP crawler with retry logic and HTML parsing."""

    def __init__(
        self,
        allowed_hosts: list,
        user_agent: str = None,
        timeout: int = 10,
        delay: float = 1.0,
    ):
        self.allowed_hosts = allowed_hosts
        self.user_agent = user_agent or "Mozilla/5.0 (compatible; perpaduan-scraper/0.1)"
        self.timeout = timeout
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})
        self._last_request_time = 0

    def _rate_limit(self):
        """Enforce delay between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def fetch(self, url: str) -> Optional[dict]:
        """
        Fetch URL with retry logic.
        Returns dict with status, content, etag, last_modified, or None on failure.
        """
        self._rate_limit()

        try:
            response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            response.raise_for_status()

            self._last_request_time = time.time()

            return {
                "status": response.status_code,
                "content": response.content,
                "content_type": response.headers.get("Content-Type", "text/html"),
                "url": response.url,  # Final URL after redirects
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
            }

        except requests.RequestException as e:
            logger.warning(f"Fetch failed {url}: {e}")
            raise

    def parse_html(self, html_content: bytes, encoding: str = "utf-8") -> Optional[BeautifulSoup]:
        """Parse HTML content."""
        try:
            return BeautifulSoup(html_content, "lxml", from_encoding=encoding)
        except Exception as e:
            logger.error(f"HTML parse error: {e}")
            return None

    def extract_links(
        self,
        soup: BeautifulSoup,
        base_url: str,
        selector: str = "a",
    ) -> Set[str]:
        """Extract and canonicalize links from page."""
        links = set()

        try:
            for elem in soup.select(selector):
                href = elem.get("href")
                if not href:
                    continue

                # Convert to absolute URL
                abs_url = extract_absolute_url(href, base_url)
                if not abs_url:
                    continue

                # Canonicalize
                canonical = canonicalize_url(abs_url, self.allowed_hosts)
                if canonical:
                    links.add(canonical)

        except Exception as e:
            logger.warning(f"Link extraction error: {e}")

        return links

    def extract_text(self, soup: BeautifulSoup, selector: str) -> Optional[str]:
        """Extract text from element."""
        try:
            elem = soup.select_one(selector)
            if elem:
                return elem.get_text(strip=True)
        except Exception:
            pass
        return None

    def extract_published_date(self, date_str: str) -> Optional[str]:
        """Parse published date to ISO 8601."""
        if not date_str:
            return None

        try:
            dt = date_parser.parse(date_str, fuzzy=True)
            return dt.date().isoformat()
        except Exception:
            logger.warning(f"Failed to parse date: {date_str}")
            return None
