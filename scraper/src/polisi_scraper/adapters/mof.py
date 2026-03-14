"""MOF adapter — Ministry of Finance Malaysia (www.mof.gov.my).

Scrapes multiple sections of the MOF portal:

1. Legacy Budget Archives (/portal/arkib/)
   Static HTML hub pages linking to year sub-pages with PDF links.
   Covers: economic reports (1995-2022), expenditure estimates,
   revenue estimates, budget speeches, fiscal summaries.

2. News & Media Archives (/portal/ms/arkib3/)
   Paginated Joomla listings (siaran-media, ucapan, pengumuman).
   Individual article pages contain PDF attachments.

3. Treasury Directives (/portal/arahan-perbendaharaan)
   Table layout with direct PDF links for AP amendments.

4. Tax Documents (/portal/cukai/)
   Direct PDF links for incentives and current policies.

5. Statistics & Performance (/portal/statistik)
   Direct PDF downloads for economic and fiscal data.

6. Economic Data Index Pages (/portal/pdf/ekonomi/)
   Thumbnail-indexed pages linking to year/quarter subdirectories.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from polisi_scraper.adapters.base import BaseSiteAdapter, DiscoveredItem, DocumentCandidate
from polisi_scraper.adapters.registry import register_adapter
from polisi_scraper.core.dates import parse_iso_date
from polisi_scraper.core.urls import guess_content_type, make_absolute

log = logging.getLogger(__name__)

BASE_URL = "https://www.mof.gov.my"

_DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv")


def _is_doc_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in _DOC_EXTENSIONS)


@register_adapter
class MofAdapter(BaseSiteAdapter):
    slug = "mof"
    agency = "Kementerian Kewangan Malaysia"
    requires_browser = False

    def _base_url(self) -> str:
        return self.config.get("base_url", BASE_URL)

    def discover(self, since: date | None = None, max_pages: int = 0) -> Iterable[DiscoveredItem]:
        sections = self.config.get("sections", [])
        pages_fetched = 0

        for section in sections:
            source_type = section.get("source_type", "static")
            doc_type = section.get("doc_type", "report")
            language = section.get("language", "ms")
            section_name = section.get("name", "unknown")

            log.info("[mof] discover section=%s source_type=%s", section_name, source_type)

            if source_type == "archive_hub":
                for item in self._discover_from_archive_hub(section, doc_type, language):
                    pages_fetched += 1
                    if max_pages and pages_fetched >= max_pages:
                        return
                    yield item

            elif source_type == "listing":
                for item in self._discover_from_listing(section, doc_type, language, since):
                    pages_fetched += 1
                    if max_pages and pages_fetched >= max_pages:
                        return
                    yield item

            elif source_type == "static":
                yield from self._discover_from_static(section, doc_type, language)

            elif source_type == "index":
                for item in self._discover_from_index(section, doc_type, language):
                    pages_fetched += 1
                    if max_pages and pages_fetched >= max_pages:
                        return
                    yield item

    # -- Archive Hub: /portal/arkib/ sub-pages --

    def _discover_from_archive_hub(
        self, section: dict, doc_type: str, language: str,
    ) -> Iterable[DiscoveredItem]:
        """Crawl archive hub page -> year sub-pages -> extract PDF links."""
        hub_url = section.get("url", "")
        section_name = section.get("name", "unknown")
        base = self._base_url()

        log.info("[mof] fetch archive hub: %s", hub_url)
        try:
            resp = self.http.get(hub_url)
        except Exception as exc:
            log.error("[mof] hub fetch error %s: %s", hub_url, exc)
            return

        soup = BeautifulSoup(resp.text, "lxml")
        seen: set[str] = set()

        # Find links to year sub-pages (e.g. ek2018.html, exp2022.html)
        year_links: list[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href:
                continue
            abs_url = urljoin(hub_url, href)
            if abs_url in seen:
                continue
            # Follow links that stay within the archive section
            if "/arkib/" in abs_url and abs_url.endswith(".html"):
                seen.add(abs_url)
                year_links.append(abs_url)

        # Also extract any direct PDF links on the hub page itself
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            abs_url = urljoin(hub_url, href)
            if _is_doc_url(abs_url) and abs_url not in seen:
                seen.add(abs_url)
                title = a.get_text(strip=True) or abs_url.split("/")[-1]
                yield DiscoveredItem(
                    source_url=abs_url, title=title, doc_type=doc_type,
                    language=language, metadata={"section": section_name, "source_type": "archive_hub"},
                )

        log.info("[mof] %s: found %d year sub-pages", section_name, len(year_links))

        # Crawl each year sub-page for PDFs
        for year_url in year_links:
            log.info("[mof] fetch year page: %s", year_url)
            try:
                year_resp = self.http.get(year_url)
            except Exception as exc:
                log.error("[mof] year page error %s: %s", year_url, exc)
                continue

            year_soup = BeautifulSoup(year_resp.text, "lxml")
            for a in year_soup.find_all("a", href=True):
                href = a["href"].strip()
                abs_url = urljoin(year_url, href)
                if _is_doc_url(abs_url) and abs_url not in seen:
                    seen.add(abs_url)
                    title = a.get_text(strip=True) or abs_url.split("/")[-1]
                    yield DiscoveredItem(
                        source_url=abs_url, title=title, doc_type=doc_type,
                        language=language, metadata={"section": section_name, "source_type": "archive_hub", "year_page": year_url},
                    )

        log.info("[mof] %s: %d total documents found", section_name, len([u for u in seen if _is_doc_url(u)]))

    # -- Paginated Joomla listing --

    def _discover_from_listing(
        self, section: dict, doc_type: str, language: str, since: date | None,
    ) -> Iterable[DiscoveredItem]:
        """Walk paginated Joomla archive listings and yield article URLs."""
        listing_url = section.get("url", "")
        section_name = section.get("name", "unknown")
        page_size = section.get("page_size", 100)
        max_listing_pages = section.get("max_listing_pages", 200)

        # Use large page size to minimize requests
        base_url = f"{listing_url}?limit={page_size}"
        offset = 0

        for page_num in range(max_listing_pages):
            page_url = f"{base_url}&start={offset}"
            log.info("[mof] %s: fetch listing page %d (start=%d)", section_name, page_num + 1, offset)

            try:
                resp = self.http.get(page_url)
            except Exception as exc:
                log.error("[mof] listing fetch error %s: %s", page_url, exc)
                break

            soup = BeautifulSoup(resp.text, "lxml")
            items_found = 0

            # Joomla list items in table rows or list items
            for row in soup.find_all("tr", class_=re.compile(r"row\d|cat-list-row")):
                a = row.find("a", href=True)
                if not a:
                    continue
                href = a["href"].strip()
                if not href or href.startswith(("#", "javascript:")):
                    continue
                abs_url = urljoin(self._base_url(), href)
                title = a.get_text(strip=True)

                # Try to get date from the row
                date_td = row.find("td", class_=re.compile(r"list-date|created"))
                pub_date = ""
                if date_td:
                    pub_date = parse_iso_date(date_td.get_text(strip=True))

                items_found += 1
                yield DiscoveredItem(
                    source_url=abs_url, title=title, published_at=pub_date,
                    doc_type=doc_type, language=language,
                    metadata={"section": section_name, "source_type": "listing", "has_detail_page": True},
                )

            # Also check for simple link lists
            if items_found == 0:
                content = soup.find("div", id="sp-main-body") or soup.find("div", class_="item-page") or soup
                for a in content.find_all("a", href=True):
                    href = a["href"].strip()
                    if not href or href.startswith(("#", "javascript:")):
                        continue
                    abs_url = urljoin(self._base_url(), href)
                    if "/berita/" in abs_url or "/arkib3/" in abs_url:
                        title = a.get_text(strip=True)
                        if title and len(title) > 5:
                            items_found += 1
                            yield DiscoveredItem(
                                source_url=abs_url, title=title,
                                doc_type=doc_type, language=language,
                                metadata={"section": section_name, "source_type": "listing", "has_detail_page": True},
                            )

            log.info("[mof] %s: %d items from page %d", section_name, items_found, page_num + 1)

            if items_found == 0:
                break

            offset += page_size

    # -- Static page with direct PDF links --

    def _discover_from_static(
        self, section: dict, doc_type: str, language: str,
    ) -> Iterable[DiscoveredItem]:
        """Scrape a single page for all document links."""
        page_url = section.get("url", "")
        section_name = section.get("name", "unknown")
        base = self._base_url()

        log.info("[mof] fetch static page: %s", page_url)
        try:
            resp = self.http.get(page_url)
        except Exception as exc:
            log.error("[mof] static page error %s: %s", page_url, exc)
            return

        soup = BeautifulSoup(resp.text, "lxml")
        seen: set[str] = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            abs_url = urljoin(base, href)
            if _is_doc_url(abs_url) and abs_url not in seen:
                seen.add(abs_url)
                title = a.get_text(strip=True) or abs_url.split("/")[-1]
                yield DiscoveredItem(
                    source_url=abs_url, title=title, doc_type=doc_type,
                    language=language, metadata={"section": section_name, "source_type": "static"},
                )

        log.info("[mof] %s: %d documents found", section_name, len(seen))

    # -- Index pages with year/quarter subdirectories --

    def _discover_from_index(
        self, section: dict, doc_type: str, language: str,
    ) -> Iterable[DiscoveredItem]:
        """Crawl thumbnail index pages that link to year/quarter subdirectories."""
        index_url = section.get("url", "")
        section_name = section.get("name", "unknown")
        base = self._base_url()

        log.info("[mof] fetch index page: %s", index_url)
        try:
            resp = self.http.get(index_url)
        except Exception as exc:
            log.error("[mof] index page error %s: %s", index_url, exc)
            return

        soup = BeautifulSoup(resp.text, "lxml")
        seen: set[str] = set()
        sub_urls: list[str] = []

        # Find links to subdirectories (year/quarter folders)
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            abs_url = urljoin(index_url, href)
            if abs_url in seen:
                continue
            # Follow links to /portal/pdf/ subdirectories
            if "/portal/pdf/" in abs_url and not _is_doc_url(abs_url):
                seen.add(abs_url)
                sub_urls.append(abs_url)
            elif _is_doc_url(abs_url) and abs_url not in seen:
                seen.add(abs_url)
                title = a.get_text(strip=True) or abs_url.split("/")[-1]
                yield DiscoveredItem(
                    source_url=abs_url, title=title, doc_type=doc_type,
                    language=language, metadata={"section": section_name, "source_type": "index"},
                )

        log.info("[mof] %s: found %d subdirectories", section_name, len(sub_urls))

        # Crawl each subdirectory for PDFs
        for sub_url in sub_urls:
            log.info("[mof] fetch sub-directory: %s", sub_url)
            try:
                sub_resp = self.http.get(sub_url)
            except Exception as exc:
                log.error("[mof] sub-directory error %s: %s", sub_url, exc)
                continue

            sub_soup = BeautifulSoup(sub_resp.text, "lxml")
            for a in sub_soup.find_all("a", href=True):
                href = a["href"].strip()
                abs_url = urljoin(sub_url, href)
                if _is_doc_url(abs_url) and abs_url not in seen:
                    seen.add(abs_url)
                    title = a.get_text(strip=True) or abs_url.split("/")[-1]
                    yield DiscoveredItem(
                        source_url=abs_url, title=title, doc_type=doc_type,
                        language=language, metadata={"section": section_name, "source_type": "index", "sub_url": sub_url},
                    )

    # -- Fetch & Extract --

    def fetch_and_extract(self, item: DiscoveredItem) -> Iterable[DocumentCandidate]:
        """Yield document candidates.

        For listing items with detail pages, fetch the article HTML and
        extract embedded PDF attachments. For direct PDF URLs, yield as-is.
        """
        url = item.source_url
        has_detail = item.metadata.get("has_detail_page", False)

        # Direct document URL
        if _is_doc_url(url):
            ct = guess_content_type(url)
            yield DocumentCandidate(
                url=url, source_page_url=item.metadata.get("section", url),
                title=item.title, published_at=item.published_at,
                doc_type=item.doc_type, content_type=ct or "application/pdf",
                language=item.language,
            )
            return

        # Article detail page — fetch HTML and extract PDF attachments
        if has_detail:
            try:
                resp = self.http.get(url)
            except Exception as exc:
                log.warning("[mof] failed to fetch article %s: %s", url, exc)
                return

            # Yield the HTML page
            yield DocumentCandidate(
                url=url, source_page_url=url, title=item.title,
                published_at=item.published_at, doc_type=item.doc_type,
                content_type="text/html", language=item.language,
            )

            # Extract PDF attachments
            soup = BeautifulSoup(resp.text, "lxml")
            base = self._base_url()
            seen: set[str] = set()

            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                abs_url = urljoin(base, href)
                if _is_doc_url(abs_url) and abs_url not in seen:
                    seen.add(abs_url)
                    ct = guess_content_type(abs_url)
                    yield DocumentCandidate(
                        url=abs_url, source_page_url=url, title=item.title,
                        published_at=item.published_at, doc_type=item.doc_type,
                        content_type=ct or "application/pdf", language=item.language,
                    )
