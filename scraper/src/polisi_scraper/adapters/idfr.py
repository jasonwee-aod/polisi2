"""IDFR adapter — Joomla 4, 4 page archetypes.

Site: https://www.idfr.gov.my
CMS:  Joomla 4 + Helix Ultimate template + SP Page Builder
No sitemap.xml or RSS feeds available — all discovery via HTML parsing.

Four page archetypes are handled:

1. Press Release Listing  (/my/media-1/press)
   Single HTML page with all press releases grouped under year headings.
   Year is tracked from preceding <p><strong>YYYY</strong></p> headings.
   Date stored as "YYYY-01-01" (year-only resolution).

2. Speeches Listing  (/my/media-1/speeches and /my/media-1/speeches-YYYY)
   One HTML table per yearly page.  Date extracted from speech title
   parenthetical, <strong> context tags, or H1 year fallback.

3. Publications Hub  (/my/publications)
   SP Page Builder feature boxes, each linking to a PDF or sub-listing page.
   Sub-listing pages are crawled automatically.

4. Generic Article Body Listing  (sub-listing pages)
   Joomla article pages with PDF links in div[itemprop="articleBody"].
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from polisi_scraper.adapters.base import (
    BaseSiteAdapter,
    DiscoveredItem,
    DocumentCandidate,
)
from polisi_scraper.adapters.registry import register_adapter
from polisi_scraper.core.dates import parse_malay_date
from polisi_scraper.core.urls import canonical_url, guess_content_type, is_allowed_host

log = logging.getLogger(__name__)

# Document file extensions to capture.
_DOC_EXTENSIONS = frozenset(
    {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip"}
)

# Match a bare 4-digit year (2000-2029).
_YEAR_ONLY_RE = re.compile(r"\b(20[0-2]\d)\b")

# Speeches page H1: "Speeches in YYYY"
_SPEECHES_YEAR_H1_RE = re.compile(r"\bin\s+(20\d{2})\b", re.IGNORECASE)

# Header cell values in speech/listing tables that identify header rows.
_TABLE_HEADER_CELLS = frozenset({"no", "title", "tajuk", "no.", "#"})


def _is_doc_link(href: str) -> bool:
    """Return True if the href points to a downloadable document."""
    lower = urlparse(href).path.lower()
    return any(lower.endswith(ext) for ext in _DOC_EXTENSIONS)


def _extract_year_from_speeches_h1(soup: BeautifulSoup) -> str:
    """Extract the year from H1 "Speeches in YYYY".  Returns "YYYY" or ""."""
    h1 = soup.find("h1", attrs={"itemprop": "headline"})
    if h1:
        m = _SPEECHES_YEAR_H1_RE.search(h1.get_text())
        if m:
            return m.group(1)
    return ""


def _extract_speech_date(
    title: str, strong_texts: list[str], fallback_year: str
) -> str:
    """Try to extract a date from a speech entry using multiple strategies.

    1. Parenthetical date in title: "Opening Remarks (Oct 2, 2025)"
    2. Date in <strong> text below the link
    3. Year-only fallback from the page H1 "Speeches in YYYY"
    """
    # Strategy 1: parenthetical in title
    paren_m = re.search(r"\(([^)]+)\)", title)
    if paren_m:
        candidate = parse_malay_date(paren_m.group(1))
        if candidate:
            return candidate

    # Strategy 2: look for date patterns in strong_texts
    for strong_text in strong_texts:
        candidate = parse_malay_date(strong_text)
        if candidate:
            return candidate

    # Strategy 3: year fallback
    if fallback_year:
        return f"{fallback_year}-01-01"

    return ""


def _is_speech_header_row(cells: list) -> bool:
    """Return True if this table row looks like a header row."""
    if not cells:
        return False
    first_text = cells[0].get_text(strip=True).lower().rstrip(".")
    if first_text in _TABLE_HEADER_CELLS:
        return True
    return False


def _since_filter(pub_date: str, since: date | None) -> bool:
    """Return True if the item should be SKIPPED (published before since)."""
    if not since or not pub_date:
        return False
    try:
        return date.fromisoformat(pub_date) < since
    except ValueError:
        return False


# ---------------------------------------------------------------------------


@register_adapter
class IdfrAdapter(BaseSiteAdapter):
    slug = "idfr"
    agency = "Institut Diplomasi dan Hubungan Luar Negeri (IDFR)"
    requires_browser = False

    # ── discover() ────────────────────────────────────────────────────────

    def discover(
        self, since: date | None = None, max_pages: int = 0
    ) -> Iterable[DiscoveredItem]:
        """Yield discovered items from all config sections."""
        allowed = self._allowed_hosts()

        for section in self.config.get("sections", []):
            source_type = section.get("source_type", "article_body_listing")
            section_name = section.get("name", "unknown")
            doc_type = section.get("doc_type", "other")
            language = section.get("language", "ms")

            log.info(
                "[idfr] discover section=%s source_type=%s",
                section_name,
                source_type,
            )

            if source_type == "press_listing":
                yield from self._discover_press_listing(
                    section, doc_type, language, since, allowed
                )

            elif source_type == "speeches_listing":
                yield from self._discover_speeches_listing(
                    section, doc_type, language, since, allowed
                )

            elif source_type == "publications_hub":
                yield from self._discover_publications_hub(
                    section, doc_type, language, since, allowed
                )

            else:  # article_body_listing (default)
                yield from self._discover_article_body(
                    section, doc_type, language, since, allowed
                )

    # ── fetch_and_extract() ───────────────────────────────────────────────

    def fetch_and_extract(
        self, item: DiscoveredItem
    ) -> Iterable[DocumentCandidate]:
        """IDFR items discovered are direct document URLs — no page fetch needed."""
        ct = guess_content_type(item.source_url)
        yield DocumentCandidate(
            url=item.source_url,
            source_page_url=item.metadata.get("listing_url", item.source_url),
            title=item.title,
            published_at=item.published_at,
            doc_type=item.doc_type,
            content_type=ct,
            language=item.language,
        )

    # ── Internal: allowed hosts ───────────────────────────────────────────

    def _allowed_hosts(self) -> frozenset[str]:
        hosts = self.config.get("allowed_hosts", [])
        return frozenset(hosts) if hosts else frozenset()

    # ── Internal: Press Release Listing ───────────────────────────────────

    def _discover_press_listing(
        self,
        section: dict,
        doc_type: str,
        language: str,
        since: date | None,
        allowed_hosts: frozenset[str],
    ) -> Iterable[DiscoveredItem]:
        """Parse the press release listing page.

        Structure:
            div[itemprop="articleBody"]
              <p><strong>2025</strong></p>   <- year header
              <ol>
                <li><a href="...pdf">TITLE</a></li>
              </ol>
        """
        listing_url = section.get("listing_url", "")
        if not listing_url:
            log.warning("[idfr] press section missing listing_url")
            return

        html = self._fetch_html(listing_url)
        if html is None:
            return

        soup = BeautifulSoup(html, "lxml")
        body = soup.find(attrs={"itemprop": "articleBody"})
        if not body:
            log.warning("[idfr] press listing: articleBody not found on %s", listing_url)
            return

        seen: set[str] = set()
        current_year = ""
        count = 0

        for element in body.descendants:
            tag_name = getattr(element, "name", None)

            # Year header: <p><strong>YYYY</strong></p>
            if tag_name == "p":
                strong = element.find("strong")
                if strong:
                    text = strong.get_text(strip=True)
                    if _YEAR_ONLY_RE.fullmatch(text):
                        current_year = text
                continue

            # PDF link inside a list item
            if tag_name == "a":
                href = element.get("href", "").strip()
                if not href or not _is_doc_link(href):
                    continue

                abs_href = urljoin(listing_url, href)

                # Host check
                if allowed_hosts and not is_allowed_host(abs_href, allowed_hosts):
                    continue

                if abs_href in seen:
                    continue
                seen.add(abs_href)

                title = element.get_text(strip=True)
                pub_date = f"{current_year}-01-01" if current_year else ""

                if _since_filter(pub_date, since):
                    continue

                count += 1
                yield DiscoveredItem(
                    source_url=abs_href,
                    title=title,
                    published_at=pub_date,
                    doc_type=doc_type,
                    language=language,
                    metadata={"listing_url": listing_url, "section": "press"},
                )

        log.info("[idfr] press listing: discovered %d items from %s", count, listing_url)

    # ── Internal: Speeches Listing ────────────────────────────────────────

    def _discover_speeches_listing(
        self,
        section: dict,
        doc_type: str,
        language: str,
        since: date | None,
        allowed_hosts: frozenset[str],
    ) -> Iterable[DiscoveredItem]:
        """Parse speech listing pages (one HTML table per year page).

        Structure:
            div[itemprop="articleBody"]
              <table>
                <tr>  <- header row (No / Title)
                <tr>  <- data row
                  <td align="center">1</td>
                  <td>
                    <a href="...pdf">SPEECH TITLE (DATE?)</a>
                    <strong>EVENT / DATE</strong>
                  </td>
                </tr>
              </table>
        """
        listing_urls = section.get("listing_urls", [])
        if not listing_urls and section.get("listing_url"):
            listing_urls = [section["listing_url"]]
        if not listing_urls:
            log.warning("[idfr] speeches section missing listing_urls")
            return

        for listing_url in listing_urls:
            yield from self._discover_speeches_page(
                listing_url, doc_type, language, since, allowed_hosts
            )

    def _discover_speeches_page(
        self,
        listing_url: str,
        doc_type: str,
        language: str,
        since: date | None,
        allowed_hosts: frozenset[str],
    ) -> Iterable[DiscoveredItem]:
        """Extract speech entries from a single speeches page."""
        html = self._fetch_html(listing_url)
        if html is None:
            return

        soup = BeautifulSoup(html, "lxml")
        fallback_year = _extract_year_from_speeches_h1(soup)

        body = soup.find(attrs={"itemprop": "articleBody"})
        if not body:
            log.warning(
                "[idfr] speeches listing: articleBody not found on %s", listing_url
            )
            return

        seen: set[str] = set()
        count = 0

        for table in body.find_all("table"):
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue

                # Skip header rows
                if _is_speech_header_row(cells):
                    continue

                # Second cell contains the speech link and metadata
                content_cell = cells[1]
                a_tag = content_cell.find("a", href=True)
                if not a_tag:
                    continue

                href = a_tag["href"].strip()
                if not _is_doc_link(href):
                    continue

                abs_href = urljoin(listing_url, href)

                if allowed_hosts and not is_allowed_host(abs_href, allowed_hosts):
                    continue

                if abs_href in seen:
                    continue
                seen.add(abs_href)

                title = a_tag.get_text(separator=" ", strip=True)

                # Collect <strong> texts for date extraction
                strong_texts = [
                    s.get_text(separator=" ", strip=True)
                    for s in content_cell.find_all("strong")
                    if s.get_text(strip=True)
                ]

                pub_date = _extract_speech_date(title, strong_texts, fallback_year)

                if _since_filter(pub_date, since):
                    continue

                count += 1
                yield DiscoveredItem(
                    source_url=abs_href,
                    title=title,
                    published_at=pub_date,
                    doc_type=doc_type,
                    language=language,
                    metadata={"listing_url": listing_url, "section": "speeches"},
                )

        log.info(
            "[idfr] speeches listing: discovered %d items from %s", count, listing_url
        )

    # ── Internal: Publications Hub ────────────────────────────────────────

    def _discover_publications_hub(
        self,
        section: dict,
        doc_type: str,
        language: str,
        since: date | None,
        allowed_hosts: frozenset[str],
    ) -> Iterable[DiscoveredItem]:
        """Parse the SP Page Builder publications hub.

        Structure:
            .sppb-addon-wrapper.addon-root-feature
              .sppb-feature-box-title > a[href]

        Direct PDF links are yielded immediately.
        Sub-listing page links are fetched and their PDFs are also yielded.
        """
        hub_url = section.get("hub_url", "")
        if not hub_url:
            log.warning("[idfr] publications section missing hub_url")
            return

        html = self._fetch_html(hub_url)
        if html is None:
            return

        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        direct_count = 0
        sub_pages: list[tuple[str, str]] = []  # (url, title)

        # Primary selector: .sppb-feature-box-title a
        anchors = soup.select(".sppb-feature-box-title a[href]")

        # Fallback: scan entire article body if no feature-box links found
        if not anchors:
            body = soup.find(attrs={"itemprop": "articleBody"})
            if body:
                anchors = body.find_all("a", href=True)

        for a_tag in anchors:
            href = a_tag.get("href", "").strip()
            if not href or href in ("#", "javascript:void(0)"):
                continue

            abs_href = urljoin(hub_url, href)

            if allowed_hosts and not is_allowed_host(abs_href, allowed_hosts):
                continue

            if abs_href in seen:
                continue
            seen.add(abs_href)

            title = a_tag.get_text(strip=True)

            if _is_doc_link(href):
                # Direct PDF/document link
                direct_count += 1
                yield DiscoveredItem(
                    source_url=abs_href,
                    title=title,
                    published_at="",
                    doc_type=doc_type,
                    language=language,
                    metadata={"listing_url": hub_url, "section": "publications"},
                )
            else:
                # Sub-listing page — queue for further crawling
                sub_pages.append((abs_href, title))

        log.info(
            "[idfr] publications hub: %d direct docs, %d sub-pages from %s",
            direct_count,
            len(sub_pages),
            hub_url,
        )

        # Crawl sub-listing pages using the article body extractor
        for sub_url, _sub_title in sub_pages:
            yield from self._discover_article_body_from_url(
                sub_url, doc_type, language, since, allowed_hosts,
                parent_listing=hub_url,
            )

    # ── Internal: Generic Article Body Listing ────────────────────────────

    def _discover_article_body(
        self,
        section: dict,
        doc_type: str,
        language: str,
        since: date | None,
        allowed_hosts: frozenset[str],
    ) -> Iterable[DiscoveredItem]:
        """Entry point for article_body_listing sections from config."""
        listing_url = section.get("listing_url", "")
        if not listing_url:
            log.warning("[idfr] article_body section missing listing_url")
            return

        yield from self._discover_article_body_from_url(
            listing_url, doc_type, language, since, allowed_hosts,
            parent_listing=listing_url,
        )

    def _discover_article_body_from_url(
        self,
        listing_url: str,
        doc_type: str,
        language: str,
        since: date | None,
        allowed_hosts: frozenset[str],
        parent_listing: str = "",
    ) -> Iterable[DiscoveredItem]:
        """Extract document links from a generic Joomla article body page.

        Used for newsletter archives, JDFR journal, other-publications,
        and any sub-listing pages discovered via the publications hub.

        Structure:
            div[itemprop="articleBody"]
              <a href="...pdf" target="_blank">DOCUMENT TITLE</a>
        """
        if allowed_hosts and not is_allowed_host(listing_url, allowed_hosts):
            log.warning("[idfr] skipping disallowed host: %s", listing_url)
            return

        html = self._fetch_html(listing_url)
        if html is None:
            return

        soup = BeautifulSoup(html, "lxml")
        body = soup.find(attrs={"itemprop": "articleBody"})
        search_root = body if body else soup

        seen: set[str] = set()
        count = 0

        for a_tag in search_root.find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href or href.startswith(("#", "javascript:")):
                continue

            if not _is_doc_link(href):
                continue

            abs_href = urljoin(listing_url, href)

            if allowed_hosts and not is_allowed_host(abs_href, allowed_hosts):
                continue

            if abs_href in seen:
                continue
            seen.add(abs_href)

            title = a_tag.get_text(strip=True)

            # Fallback for image-based links (<a><img/></a>) with empty text:
            # look for title in the grandparent <tr>.
            if not title:
                for ancestor in a_tag.parents:
                    if getattr(ancestor, "name", None) == "tr":
                        row_text = ancestor.get_text(separator=" ", strip=True)
                        row_text = re.sub(r"^\d+\.\s*", "", row_text).strip()
                        row_text = re.sub(r"\s*-\s*$", "", row_text).strip()
                        if row_text:
                            title = row_text
                        break

            # Try to find a date in the link text or parent context
            pub_date = parse_malay_date(title)
            if not pub_date and a_tag.parent:
                parent_text = a_tag.parent.get_text(separator=" ", strip=True)
                pub_date = parse_malay_date(parent_text)

            if _since_filter(pub_date, since):
                continue

            count += 1
            yield DiscoveredItem(
                source_url=abs_href,
                title=title,
                published_at=pub_date,
                doc_type=doc_type,
                language=language,
                metadata={
                    "listing_url": parent_listing or listing_url,
                    "section": "article_body",
                },
            )

        log.info(
            "[idfr] article body listing: discovered %d items from %s",
            count,
            listing_url,
        )

    # ── Internal: HTTP helper ─────────────────────────────────────────────

    def _fetch_html(self, url: str) -> str | None:
        """Fetch a URL and return HTML text, or None on failure."""
        try:
            resp = self.http.get(url)
            return resp.text
        except Exception as e:
            log.warning("[idfr] failed to fetch %s: %s", url, e)
            return None
