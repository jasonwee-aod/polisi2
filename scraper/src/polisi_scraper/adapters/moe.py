"""MOE adapter — DataTables listing, discovery.py pattern.

Ministry of Education (www.moe.gov.my) uses server-side rendered DataTables
with ``<table id="example">`` on each section listing page.  Each row has two
cells: a title link (``<td><a href="...">Title</a></td>``) and a date string
(``<td>12 Feb 2026</td>``).

The adapter fetches each configured section URL, parses the DataTables rows
with BeautifulSoup, and yields :class:`DiscoveredItem` objects.  The detail
page is then fetched by the default ``fetch_and_extract`` pipeline to pick up
any embedded PDF/document links.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from polisi_scraper.adapters.base import (
    BaseSiteAdapter,
    DiscoveredItem,
    DocumentCandidate,
)
from polisi_scraper.adapters.registry import register_adapter
from polisi_scraper.core.dates import parse_malay_date
from polisi_scraper.core.extractors import extract_document_links
from polisi_scraper.core.urls import canonical_url, guess_content_type, is_allowed_host

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Generic title prefixes that the MOE CMS emits — strip to get a meaningful
# fallback when the listing row title is empty.
# ---------------------------------------------------------------------------
_TITLE_PREFIXES = ("kpm | ", "kementerian pendidikan malaysia | ")

# ---------------------------------------------------------------------------
# Document-type inference from URL / title text
# ---------------------------------------------------------------------------
_DOC_TYPE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("press_release", ("kenyataan media", "press release", "media release")),
    ("statement", ("surat siaran", "statement", "siaran")),
    ("report", ("laporan", "report")),
    ("notice", ("pekeliling", "circular", "pengumuman", "notice", "iklan", "arahan")),
    ("speech", ("ucapan", "speech")),
]


def _guess_doc_type(url: str, title: str, fallback: str = "other") -> str:
    """Classify a document based on keywords in *url* and *title*."""
    text = f"{url} {title}".lower()
    for doc_type, keywords in _DOC_TYPE_RULES:
        if any(kw in text for kw in keywords):
            return doc_type
    return fallback


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _strip_cms_title_prefix(raw_title: str) -> str:
    """Remove generic CMS title prefixes such as 'KPM | '."""
    lower = raw_title.lower()
    for prefix in _TITLE_PREFIXES:
        if lower.startswith(prefix):
            return raw_title[len(prefix):]
    return raw_title


# ---------------------------------------------------------------------------
# DataTables row parser
# ---------------------------------------------------------------------------

def _parse_listing_table(html: str, page_url: str) -> list[dict]:
    """Extract items from the ``<table id="example">`` DataTables listing.

    Returns a list of dicts with keys ``url``, ``title``, and ``date_str``.
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []

    for row in soup.select("table#example tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        anchor = cells[0].find("a", href=True)
        if not anchor:
            continue

        href = anchor.get("href", "").strip()
        if not href:
            continue

        url = urljoin(page_url, href)
        if not url.startswith("http"):
            continue

        title = _normalize_whitespace(anchor.get_text())
        date_str = _normalize_whitespace(cells[1].get_text()) if len(cells) > 1 else ""

        items.append({
            "url": url,
            "title": title or "Untitled",
            "date_str": date_str,
        })

    return items


# ---------------------------------------------------------------------------
# Detail-page title fallback
# ---------------------------------------------------------------------------

def _extract_detail_title(html: str) -> str:
    """Try to extract a title from the MOE detail page HTML.

    MOE detail pages often have an empty ``<h1>`` and a generic ``<title>``
    tag.  Walk h1 -> h2 -> h3 for the first non-empty heading, falling back
    to the ``<title>`` tag with CMS prefix stripped.
    """
    soup = BeautifulSoup(html, "lxml")
    for tag_name in ("h1", "h2", "h3"):
        for heading in soup.find_all(tag_name):
            text = _normalize_whitespace(heading.get_text())
            if text:
                return text

    if soup.title and soup.title.text:
        return _strip_cms_title_prefix(_normalize_whitespace(soup.title.text))

    return ""


# ===================================================================
# Adapter
# ===================================================================

@register_adapter
class MoeAdapter(BaseSiteAdapter):
    """Scraper adapter for www.moe.gov.my — DataTables listing pages."""

    slug = "moe"
    agency = "Kementerian Pendidikan Malaysia (MOE)"
    requires_browser = False

    # ----- discovery -------------------------------------------------------

    def discover(
        self,
        since: date | None = None,
        max_pages: int = 0,
    ) -> Iterable[DiscoveredItem]:
        """Fetch each section listing page and yield discovered items.

        Config shape::

            {
              "base_url": "https://www.moe.gov.my",
              "allowed_hosts": ["www.moe.gov.my", "moe.gov.my"],
              "sections": [
                {
                  "url": "https://www.moe.gov.my/pekeliling",
                  "doc_type": "notice",
                  "language": "ms"
                },
                ...
              ],
              "max_pages_default": 500
            }
        """
        sections = self.config.get("sections", [])
        allowed_hosts = set(self.config.get("allowed_hosts", []))
        total_yielded = 0
        seen: set[str] = set()

        for section in sections:
            section_url = section.get("url", "")
            doc_type_override = section.get("doc_type", "")
            language = section.get("language", "ms")

            if not section_url:
                continue

            try:
                resp = self.http.get(section_url)
                html = resp.text
            except Exception as exc:
                log.warning("[moe] Failed to fetch %s: %s", section_url, exc)
                continue

            items = _parse_listing_table(html, section_url)
            log.info(
                "[moe] Parsed %d items from %s", len(items), section_url,
            )

            for item in items:
                url = item["url"]
                c_url = canonical_url(url)

                # Dedup within this crawl
                if c_url in seen:
                    continue
                seen.add(c_url)

                # Host allowlist
                if allowed_hosts and not is_allowed_host(url, allowed_hosts):
                    continue

                # Parse date from listing row
                pub_date = parse_malay_date(item["date_str"]) if item["date_str"] else ""

                # Since-date filtering
                if since and pub_date:
                    try:
                        if date.fromisoformat(pub_date) < since:
                            continue
                    except ValueError:
                        pass

                title = item["title"]
                doc_type = doc_type_override or _guess_doc_type(url, title)

                yield DiscoveredItem(
                    source_url=url,
                    title=title,
                    published_at=pub_date,
                    doc_type=doc_type,
                    language=language,
                    metadata={
                        "section_url": section_url,
                        "date_raw": item["date_str"],
                    },
                )

                total_yielded += 1
                if max_pages and total_yielded >= max_pages:
                    return

    # ----- fetch + extract -------------------------------------------------

    def fetch_and_extract(
        self, item: DiscoveredItem,
    ) -> Iterable[DocumentCandidate]:
        """Fetch the MOE detail page and extract document download links.

        MOE detail pages often have an empty ``<h1>`` and a generic
        ``<title>`` tag.  The listing-row title (already in *item.title*) is
        more reliable, so we prefer it and only fall back to the detail page
        heading when the listing title is missing.

        Yields the HTML page itself and any embedded document links (PDFs, etc.).
        """
        try:
            resp = self.http.get(item.source_url)
            html = resp.text
        except Exception as exc:
            log.warning("[moe] Failed to fetch detail %s: %s", item.source_url, exc)
            return

        # Prefer listing-row title; fall back to detail page heading
        title = item.title
        if not title or title == "Untitled":
            detail_title = _extract_detail_title(html)
            if detail_title:
                title = detail_title

        # Yield the HTML detail page itself
        yield DocumentCandidate(
            url=item.source_url,
            source_page_url=item.source_url,
            title=title,
            published_at=item.published_at,
            doc_type=item.doc_type,
            content_type="text/html",
            language=item.language,
        )

        # Extract embedded document links (PDFs, DOC, etc.)
        downloads = extract_document_links(html, item.source_url)
        for dl in downloads:
            ct = guess_content_type(dl.url) if dl.url else ""
            yield DocumentCandidate(
                url=dl.url,
                source_page_url=item.source_url,
                title=title,
                published_at=item.published_at,
                doc_type=item.doc_type,
                content_type=ct,
                language=item.language,
            )
