"""Perpaduan adapter — CSS selector-driven HTML scraping."""

from __future__ import annotations

import logging
from datetime import date
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from polisi_scraper.adapters.base import BaseSiteAdapter, DiscoveredItem, DocumentCandidate
from polisi_scraper.adapters.registry import register_adapter
from polisi_scraper.core.dates import parse_malay_date
from polisi_scraper.core.urls import canonical_url, guess_content_type

log = logging.getLogger(__name__)


@register_adapter
class PerpaduanAdapter(BaseSiteAdapter):
    slug = "perpaduan"
    agency = "Kementerian Perpaduan Negara"
    requires_browser = False

    def discover(self, since: date | None = None, max_pages: int = 0) -> Iterable[DiscoveredItem]:
        sections = self.config.get("sections", [])

        for section in sections:
            url = section.get("url", "")
            doc_type = section.get("doc_type", "other")
            item_selector = section.get("item_selector", "")
            title_selector = section.get("title_selector", "")
            link_selector = section.get("link_selector", "a")
            date_selector = section.get("date_selector", "")

            if not url:
                continue

            try:
                resp = self.http.get(url)
                html = resp.text
            except Exception as e:
                log.warning(f"[perpaduan] Failed to fetch {url}: {e}")
                continue

            soup = BeautifulSoup(html, "lxml")
            items = soup.select(item_selector) if item_selector else [soup]

            for item_el in items:
                # Extract title
                title = ""
                if title_selector:
                    title_el = item_el.select_one(title_selector)
                    title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    title = item_el.get_text(strip=True)[:200]

                # Extract link
                link_el = item_el.select_one(link_selector) if link_selector else item_el.find("a", href=True)
                if not link_el or not link_el.get("href"):
                    continue
                href = urljoin(url, link_el["href"].strip())

                # Extract date
                pub_date = ""
                if date_selector:
                    date_el = item_el.select_one(date_selector)
                    if date_el:
                        pub_date = parse_malay_date(date_el.get_text(strip=True))

                if since and pub_date:
                    try:
                        if date.fromisoformat(pub_date) < since:
                            continue
                    except ValueError:
                        pass

                yield DiscoveredItem(
                    source_url=href,
                    title=title,
                    published_at=pub_date,
                    doc_type=doc_type,
                    language="ms",
                )

    def fetch_and_extract(self, item: DiscoveredItem) -> Iterable[DocumentCandidate]:
        """Perpaduan is HTML-only archival — yield the page itself."""
        yield DocumentCandidate(
            url=item.source_url,
            source_page_url=item.source_url,
            title=item.title,
            published_at=item.published_at,
            doc_type=item.doc_type,
            content_type="text/html",
            language=item.language,
        )
