"""RMP adapter — Sitefinity, path-based pagination (/page/N).

Site overview
-------------
www.rmp.gov.my runs Telerik Sitefinity 6.3.5000.0 PE (ASP.NET).  All content
is server-rendered -- no JavaScript required.  There is no usable sitemap.xml;
discovery uses seeded listing URLs.

Two source types:
  listing      -- Sitefinity news widget with data-sf-field="Title" anchors.
                  Each item is an HTML article page that may embed PDF/DOCX links.
  publications -- Telerik RadGrid table (rgMasterTable) with sfdownloadLink anchors.
                  Each item is a direct file download.

Pagination: path-based /page/N appended to the listing URL.
  Page 1: base listing URL (no /page/1).
  Page 2: <listing_url>/page/2
  Stops when no sf_pagerNumeric link to the next page exists or items are empty.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from polisi_scraper.adapters.base import BaseSiteAdapter, DiscoveredItem, DocumentCandidate
from polisi_scraper.adapters.registry import register_adapter
from polisi_scraper.core.dates import parse_malay_date
from polisi_scraper.core.urls import canonical_url, guess_content_type
from polisi_scraper.core.extractors import extract_document_links, DownloadLink

log = logging.getLogger(__name__)

# Regex to detect a date embedded in a Sitefinity URL path: /YYYY/MM/DD/
_URL_DATE_RE = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/")

# Document file extensions for direct-download detection
_DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")

BASE_URL = "https://www.rmp.gov.my"

# Default section definitions matching the original rmp.yaml config
_DEFAULT_SECTIONS = [
    {
        "name": "berita",
        "label": "News (Berita)",
        "doc_type": "press_release",
        "language": "ms",
        "source_type": "listing",
        "listing_url": "https://www.rmp.gov.my/arkib-berita/berita",
    },
    {
        "name": "siaran_media",
        "label": "Media Statements (Siaran Media)",
        "doc_type": "statement",
        "language": "ms",
        "source_type": "listing",
        "listing_url": "https://www.rmp.gov.my/arkib-berita/siaran-media",
    },
    {
        "name": "penerbitan",
        "label": "Publications (Penerbitan)",
        "doc_type": "report",
        "language": "ms",
        "source_type": "publications",
        "listing_url": "https://www.rmp.gov.my/laman-utama/penerbitan",
    },
]


# ---------------------------------------------------------------------------
# Sitefinity HTML extraction helpers
# ---------------------------------------------------------------------------

def _date_from_url(url: str) -> str:
    """Extract a publication date from a Sitefinity URL path (/YYYY/MM/DD/).

    Returns ISO date string or empty string.
    """
    match = _URL_DATE_RE.search(url)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month}-{day}"
    return ""


def _extract_listing_items(html: str, source_url: str) -> list[dict]:
    """Extract article links from a Sitefinity news listing page.

    Each item is identified by the data-sf-field="Title" attribute on the
    anchor tag.  Falls back to any anchor inside sfnewsItem containers.

    Returns list of dicts with keys: title, href, date_text, source_url.
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen_hrefs: set[str] = set()

    # Primary: anchors with Sitefinity Title field attribute
    anchors = soup.find_all("a", attrs={"data-sf-field": "Title"})

    # Fallback: any anchor inside sfnewsItem or sfnewsItemTitle containers
    if not anchors:
        for container in soup.find_all(
            class_=re.compile(r"\b(sfnewsItem|sfnewsItemTitle)\b")
        ):
            a = container.find("a", href=True)
            if a:
                anchors.append(a)

    for a_tag in anchors:
        href = a_tag.get("href", "").strip()
        if not href or href in seen_hrefs:
            continue
        if href.startswith(("javascript:", "#", "mailto:")):
            continue
        seen_hrefs.add(href)

        title = a_tag.get_text(strip=True)

        # Date: look in nearest sfnewsMetaInfo sibling or parent container
        date_text = ""
        parent = a_tag.find_parent(class_=re.compile(r"\bsfnewsItem\b"))
        if not parent:
            parent = a_tag.find_parent(["div", "li", "article"])
        if parent:
            meta_div = parent.find(class_=re.compile(r"\bsfnewsMetaInfo\b"))
            if meta_div:
                date_li = meta_div.find(class_=re.compile(r"\bsfnewsDate\b"))
                if date_li:
                    date_text = date_li.get_text(strip=True)
                else:
                    date_text = meta_div.get_text(" ", strip=True)

        # Last resort: extract date from href (Sitefinity embeds /YYYY/MM/DD/)
        if not date_text:
            date_text = _date_from_url(href)

        items.append({
            "title": title,
            "href": href,
            "date_text": date_text,
            "source_url": source_url,
        })

    log.debug("listing_extracted source_url=%s item_count=%d", source_url, len(items))
    return items


def _extract_publications(html: str, source_url: str) -> list[dict]:
    """Extract document download links from a Sitefinity RadGrid table.

    Looks for <table class="rgMasterTable"> with <a class="sfdownloadLink">
    or links to /docs/default-source/.

    Returns list of dicts with keys: title, href, date_text, source_url.
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen_hrefs: set[str] = set()

    table = soup.find("table", class_=re.compile(r"\brgMasterTable\b"))
    if not table:
        log.debug("no_publications_table source_url=%s", source_url)
        return []

    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")

    for tr in rows:
        # Download link: prefer sfdownloadLink class, then any /docs/ href
        dl_link = tr.find("a", class_="sfdownloadLink")
        if not dl_link:
            dl_link = tr.find("a", href=re.compile(r"/docs/default-source/", re.I))
        if not dl_link:
            continue

        href = dl_link.get("href", "").strip()
        if not href or href in seen_hrefs:
            continue
        if href.startswith(("javascript:", "#", "mailto:")):
            continue
        seen_hrefs.add(href)

        # Title: text of first non-link cell, or anchor text as fallback
        cells = tr.find_all("td")
        title = ""
        for td in cells:
            if td.find("a", class_="sfdownloadLink"):
                continue
            cell_text = td.get_text(strip=True)
            if cell_text:
                title = cell_text
                break
        if not title:
            title = dl_link.get_text(strip=True) or href.split("/")[-1].split("?")[0]

        items.append({
            "title": title,
            "href": href,
            "date_text": "",
            "source_url": source_url,
        })

    log.debug("publications_extracted source_url=%s item_count=%d", source_url, len(items))
    return items


def _get_next_page_url(html: str, current_page: int) -> str | None:
    """Return the URL of the next page in a Sitefinity sf_pagerNumeric div.

    Searches for a link whose /page/N path segment equals current_page + 1.
    Returns None when no such link exists (end of pagination).
    """
    soup = BeautifulSoup(html, "lxml")
    pager = soup.find(class_=re.compile(r"\bsf_pagerNumeric\b"))
    if not pager:
        return None

    next_page = current_page + 1
    for a in pager.find_all("a", href=True):
        href = a["href"]
        match = re.search(r"/page/(\d+)(?:[/?#]|$)", href)
        if match and int(match.group(1)) == next_page:
            return href

    return None


def _extract_article_meta(html: str, source_url: str) -> dict:
    """Extract title and published date from a Sitefinity article detail page.

    Title priority: sfnewsTitle/sfArticleTitle h1 > og:title > <title> tag.
    Date priority:  URL-embedded date > sfnewsDate > article:published_time > <time>.

    Returns dict with keys: title, published_at.
    """
    soup = BeautifulSoup(html, "lxml")

    # -- Title --
    title = ""
    for cls in ("sfnewsTitle", "sfArticleTitle", "sfContentTitle"):
        h1 = soup.find("h1", class_=re.compile(rf"\b{cls}\b"))
        if h1:
            title = h1.get_text(strip=True)
            break

    if not title:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()

    if not title:
        tag = soup.find("title")
        if tag:
            raw = tag.get_text(strip=True)
            for sep in (" | ", " - ", " \u2013 "):
                if sep in raw:
                    title = raw.split(sep)[0].strip()
                    break
            else:
                title = raw

    # -- Published date --
    published_at = _date_from_url(source_url)

    if not published_at:
        meta_info = soup.find(class_=re.compile(r"\bsfnewsMetaInfo\b"))
        if meta_info:
            date_el = meta_info.find(class_=re.compile(r"\bsfnewsDate\b"))
            if date_el:
                published_at = parse_malay_date(date_el.get_text(strip=True))
            if not published_at:
                published_at = parse_malay_date(meta_info.get_text(" ", strip=True))

    if not published_at:
        meta = soup.find("meta", property="article:published_time")
        if meta and meta.get("content"):
            published_at = parse_malay_date(meta["content"])

    if not published_at:
        time_el = soup.find("time", attrs={"datetime": True})
        if time_el:
            published_at = parse_malay_date(time_el["datetime"])

    return {"title": title, "published_at": published_at}


def _extract_embedded_doc_links(html: str, base_url: str) -> list[str]:
    """Find document download links embedded in a Sitefinity article body.

    Scopes to Sitefinity content containers (sfnewsContent, sfContentBlock,
    sfArticleContainer) to avoid navigation noise.

    Returns a deduplicated list of absolute document URLs.
    """
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    links: list[str] = []

    content = (
        soup.find(class_=re.compile(r"\bsfnewsContent\b"))
        or soup.find(class_=re.compile(r"\bsfContentBlock\b"))
        or soup.find(class_=re.compile(r"\bsfArticleContainer\b"))
        or soup.find("article")
        or soup
    )

    for a_tag in content.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue

        href_lower = href.lower().split("?")[0]
        if any(href_lower.endswith(ext) for ext in _DOC_EXTENSIONS):
            abs_url = urljoin(base_url, href)
            if abs_url not in seen:
                seen.add(abs_url)
                links.append(abs_url)

    return links


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@register_adapter
class RmpAdapter(BaseSiteAdapter):
    """Adapter for www.rmp.gov.my (Sitefinity CMS, path-based pagination)."""

    slug = "rmp"
    agency = "Polis Diraja Malaysia (RMP)"
    requires_browser = False

    @property
    def _base_url(self) -> str:
        return self.config.get("base_url", BASE_URL)

    @property
    def _sections(self) -> list[dict]:
        return self.config.get("sections", _DEFAULT_SECTIONS)

    # ------------------------------------------------------------------
    # discover()
    # ------------------------------------------------------------------

    def discover(
        self, since: date | None = None, max_pages: int = 0
    ) -> Iterable[DiscoveredItem]:
        """Yield DiscoveredItems from all configured sections.

        Walks each section's listing URL through Sitefinity /page/N pagination.
        For *listing* sections, each item points to an HTML article page.
        For *publications* sections, each item points to a direct file download.
        """
        for section in self._sections:
            source_type = section.get("source_type", "listing")
            listing_url = section.get("listing_url", "")
            doc_type = section.get("doc_type", "other")
            language = section.get("language", "ms")
            section_name = section.get("name", "")

            if not listing_url:
                log.warning("[rmp] Section %r has no listing_url, skipping", section_name)
                continue

            if source_type == "listing":
                yield from self._discover_listing(
                    listing_url, doc_type, language, section_name, since, max_pages,
                )
            elif source_type == "publications":
                yield from self._discover_publications(
                    listing_url, doc_type, language, section_name, since, max_pages,
                )
            else:
                log.warning("[rmp] Unknown source_type %r in section %r", source_type, section_name)

    # ------------------------------------------------------------------
    # Listing discovery (news / media statements)
    # ------------------------------------------------------------------

    def _discover_listing(
        self,
        seed_url: str,
        doc_type: str,
        language: str,
        section_name: str,
        since: date | None,
        max_pages: int,
    ) -> Iterable[DiscoveredItem]:
        """Paginate a Sitefinity news listing and yield article DiscoveredItems."""
        current_url = seed_url
        current_page = 1
        pages_fetched = 0

        while True:
            if max_pages and pages_fetched >= max_pages:
                log.info("[rmp:%s] max_pages=%d reached", section_name, max_pages)
                return

            log.info("[rmp:%s] Fetching listing page %d: %s", section_name, current_page, current_url)

            try:
                resp = self.http.get(current_url)
            except Exception as exc:
                log.error("[rmp:%s] Failed to fetch listing %s: %s", section_name, current_url, exc)
                break

            html = resp.text
            items = _extract_listing_items(html, current_url)

            if not items:
                log.info("[rmp:%s] No items on page %d, stopping", section_name, current_page)
                break

            pages_fetched += 1

            for item in items:
                href = urljoin(self._base_url, item["href"])
                date_text = item.get("date_text", "")

                # Parse date from listing metadata or URL
                pub_date = parse_malay_date(date_text) if date_text else ""
                if not pub_date:
                    pub_date = _date_from_url(href)

                # Apply --since filter early
                if since and pub_date:
                    try:
                        if date.fromisoformat(pub_date) < since:
                            continue
                    except ValueError:
                        pass

                yield DiscoveredItem(
                    source_url=href,
                    title=item.get("title", ""),
                    published_at=pub_date,
                    doc_type=doc_type,
                    language=language,
                    metadata={
                        "section": section_name,
                        "source_type": "listing",
                        "listing_page_url": current_url,
                    },
                )

            # Follow Sitefinity sf_pagerNumeric to next page
            next_url = _get_next_page_url(html, current_page)
            if not next_url:
                log.info("[rmp:%s] No next page after page %d, stopping", section_name, current_page)
                break

            current_url = urljoin(self._base_url, next_url)
            current_page += 1

    # ------------------------------------------------------------------
    # Publications discovery (RadGrid document table)
    # ------------------------------------------------------------------

    def _discover_publications(
        self,
        seed_url: str,
        doc_type: str,
        language: str,
        section_name: str,
        since: date | None,
        max_pages: int,
    ) -> Iterable[DiscoveredItem]:
        """Paginate a Sitefinity RadGrid publications table and yield file DiscoveredItems."""
        current_url = seed_url
        current_page = 1
        pages_fetched = 0

        while True:
            if max_pages and pages_fetched >= max_pages:
                log.info("[rmp:%s] max_pages=%d reached", section_name, max_pages)
                return

            log.info("[rmp:%s] Fetching publications page %d: %s", section_name, current_page, current_url)

            try:
                resp = self.http.get(current_url)
            except Exception as exc:
                log.error("[rmp:%s] Failed to fetch publications %s: %s", section_name, current_url, exc)
                break

            html = resp.text
            items = _extract_publications(html, current_url)

            if not items:
                log.info("[rmp:%s] No publications on page %d, stopping", section_name, current_page)
                break

            pages_fetched += 1

            for item in items:
                href = urljoin(self._base_url, item["href"])

                yield DiscoveredItem(
                    source_url=href,
                    title=item.get("title", ""),
                    published_at="",  # publications rarely show dates
                    doc_type=doc_type,
                    language=language,
                    metadata={
                        "section": section_name,
                        "source_type": "publications",
                        "listing_page_url": current_url,
                        "_direct_file": True,
                    },
                )

            # Follow sf_pagerNumeric to next page
            next_url = _get_next_page_url(html, current_page)
            if not next_url:
                log.info("[rmp:%s] No next publications page after %d, stopping", section_name, current_page)
                break

            current_url = urljoin(self._base_url, next_url)
            current_page += 1

    # ------------------------------------------------------------------
    # fetch_and_extract()
    # ------------------------------------------------------------------

    def fetch_and_extract(self, item: DiscoveredItem) -> Iterable[DocumentCandidate]:
        """Fetch a discovered item and extract downloadable documents.

        For publications (direct file downloads): yield a single DocumentCandidate
        pointing at the file URL -- no HTML fetch needed.

        For listing items (article pages): fetch the article HTML, extract
        metadata (title, date), yield the HTML page itself as a candidate, then
        yield any embedded document links found in the article body.
        """
        is_direct_file = item.metadata.get("_direct_file", False)

        if is_direct_file:
            ct = guess_content_type(item.source_url)
            yield DocumentCandidate(
                url=item.source_url,
                source_page_url=item.metadata.get("listing_page_url", item.source_url),
                title=item.title,
                published_at=item.published_at,
                doc_type=item.doc_type,
                content_type=ct,
                language=item.language,
            )
            return

        # Check if the discovered URL is itself a document (e.g. listing that
        # directly links a PDF rather than an article page)
        url_lower = item.source_url.lower().split("?")[0]
        if any(url_lower.endswith(ext) for ext in _DOC_EXTENSIONS):
            ct = guess_content_type(item.source_url)
            yield DocumentCandidate(
                url=item.source_url,
                source_page_url=item.metadata.get("listing_page_url", item.source_url),
                title=item.title,
                published_at=item.published_at,
                doc_type=item.doc_type,
                content_type=ct,
                language=item.language,
            )
            return

        # Fetch article HTML page
        try:
            resp = self.http.get(item.source_url)
            html = resp.text
        except Exception as e:
            log.warning("[rmp] Failed to fetch article %s: %s", item.source_url, e)
            return

        # Extract richer metadata from the article page
        meta = _extract_article_meta(html, item.source_url)
        title = meta.get("title") or item.title
        published_at = meta.get("published_at") or item.published_at

        # Yield the HTML article page itself
        yield DocumentCandidate(
            url=item.source_url,
            source_page_url=item.metadata.get("listing_page_url", item.source_url),
            title=title,
            published_at=published_at,
            doc_type=item.doc_type,
            content_type="text/html",
            language=item.language,
        )

        # Extract and yield embedded document links from the article body
        embedded_urls = _extract_embedded_doc_links(html, self._base_url)
        for doc_url in embedded_urls:
            ct = guess_content_type(doc_url)
            yield DocumentCandidate(
                url=doc_url,
                source_page_url=item.source_url,
                title=title,
                published_at=published_at,
                doc_type=item.doc_type,
                content_type=ct,
                language=item.language,
            )

    # ------------------------------------------------------------------
    # extract_downloads() -- override for Sitefinity-specific patterns
    # ------------------------------------------------------------------

    def extract_downloads(self, html: str, base_url: str) -> list[DownloadLink]:
        """Extract download links with Sitefinity-aware logic.

        In addition to the default document link scanner, this also picks up
        sfdownloadLink anchors and /docs/default-source/ URLs that the generic
        scanner might miss.
        """
        # Start with the generic scanner
        links = extract_document_links(html, base_url)
        seen = {dl.url for dl in links}

        soup = BeautifulSoup(html, "lxml")

        # Sitefinity sfdownloadLink class
        for a in soup.find_all("a", class_="sfdownloadLink", href=True):
            abs_url = urljoin(base_url, a["href"].strip())
            if abs_url not in seen and abs_url.startswith("http"):
                seen.add(abs_url)
                label = a.get_text(strip=True) or abs_url.split("/")[-1].split("?")[0]
                links.append(DownloadLink(url=abs_url, label=label))

        # /docs/default-source/ pattern (Sitefinity document library)
        for a in soup.find_all("a", href=re.compile(r"/docs/default-source/", re.I)):
            abs_url = urljoin(base_url, a["href"].strip())
            if abs_url not in seen and abs_url.startswith("http"):
                seen.add(abs_url)
                label = a.get_text(strip=True) or abs_url.split("/")[-1].split("?")[0]
                links.append(DownloadLink(url=abs_url, label=label))

        return links
