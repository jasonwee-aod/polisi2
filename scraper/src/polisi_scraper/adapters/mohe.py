"""MOHE adapter — RSS feeds + DOCman tables.

Ministry of Higher Education (Kementerian Pengajian Tinggi) uses Joomla with
DOCman for staff downloads.  Public-facing content is exposed via 8 bilingual
RSS feeds (EN + MS), while internal circulars, manuals, and forms live on
DOCman listing pages rendered as ``<table class="k-js-documents-table">``.

Discovery strategy
------------------
1. **RSS feeds** — Parse each feed's XML, extract ``<item>`` elements.  The
   article ``<link>`` is the source URL; ``<pubDate>`` provides the date.
2. **DOCman listing pages** — Fetch HTML, select rows from
   ``.k-js-documents-table``, extract ``<a href="…/file">`` download links and
   the date cell.  DOCman links ending in ``/file`` point directly to binary
   PDF/DOC downloads with no intermediate detail page.

Pages that require Playwright (``playwright_required: true``) are skipped
unless the adapter's ``requires_browser`` flag is enabled at runtime.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Iterable
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from polisi_scraper.adapters.base import (
    BaseSiteAdapter,
    DiscoveredItem,
    DocumentCandidate,
)
from polisi_scraper.adapters.registry import register_adapter
from polisi_scraper.core.dates import parse_malay_date
from polisi_scraper.core.urls import canonical_url, guess_content_type
from polisi_scraper.core.extractors import extract_document_links, DownloadLink

log = logging.getLogger(__name__)

_BASE_URL = "https://www.mohe.gov.my"

# ---- RSS feed definitions (embedded defaults) --------------------------------
# Each tuple: (name, EN URL, MS URL, doc_type)
_DEFAULT_RSS_FEEDS: list[dict] = [
    {
        "name": "announcements",
        "url_en": "https://www.mohe.gov.my/en/broadcast/announcements?format=feed&type=rss",
        "url_ms": "https://www.mohe.gov.my/hebahan/pengumuman?format=feed&type=rss",
        "doc_type": "announcement",
    },
    {
        "name": "media_statements",
        "url_en": "https://www.mohe.gov.my/en/broadcast/media-statements?format=feed&type=rss",
        "url_ms": "https://www.mohe.gov.my/hebahan/kenyataan-media?format=feed&type=rss",
        "doc_type": "press_release",
    },
    {
        "name": "activities",
        "url_en": "https://www.mohe.gov.my/en/broadcast/activities?format=feed&type=rss",
        "url_ms": "https://www.mohe.gov.my/hebahan/sorotan-aktiviti?format=feed&type=rss",
        "doc_type": "announcement",
    },
    {
        "name": "media_coverage",
        "url_en": "https://www.mohe.gov.my/en/broadcast/media-coverage?format=feed&type=rss",
        "url_ms": "https://www.mohe.gov.my/hebahan/liputan-media?format=feed&type=rss",
        "doc_type": "report",
    },
    {
        "name": "infographics",
        "url_en": "https://www.mohe.gov.my/en/broadcast/infographics?format=feed&type=rss",
        "url_ms": "https://www.mohe.gov.my/hebahan/infografik?format=feed&type=rss",
        "doc_type": "report",
    },
    {
        "name": "speeches",
        "url_en": "https://www.mohe.gov.my/en/broadcast/speeches?format=feed&type=rss",
        "url_ms": "https://www.mohe.gov.my/hebahan/teks-ucapan?format=feed&type=rss",
        "doc_type": "speech",
    },
    {
        "name": "faq",
        "url_en": "https://www.mohe.gov.my/en/broadcast/faq?format=feed&type=rss",
        "url_ms": "https://www.mohe.gov.my/hebahan/soalan-lazim?format=feed&type=rss",
        "doc_type": "other",
    },
    {
        "name": "job_tender",
        "url_en": "https://www.mohe.gov.my/en/broadcast/job-tender?format=feed&type=rss",
        "url_ms": "https://www.mohe.gov.my/hebahan/tender-kerja?format=feed&type=rss",
        "doc_type": "notice",
    },
]

# ---- DOCman listing page definitions (embedded defaults) ---------------------
_DEFAULT_LISTING_PAGES: list[dict] = [
    {
        "name": "circulars_arahan_pentadbiran",
        "url_ms": "https://www.mohe.gov.my/warga/muat-turun/pekeliling/arahan-pentadbiran",
        "url_en": "https://www.mohe.gov.my/en/staff/downloads/circular",
        "doc_type": "circular",
        "playwright_required": False,
    },
    {
        "name": "circulars_data",
        "url_ms": "https://www.mohe.gov.my/warga/muat-turun/pekeliling/data",
        "doc_type": "circular",
        "playwright_required": False,
    },
    {
        "name": "circulars_ict",
        "url_ms": "https://www.mohe.gov.my/warga/muat-turun/pekeliling/ict",
        "doc_type": "circular",
        "playwright_required": False,
    },
    {
        "name": "circulars_kewangan",
        "url_ms": "https://www.mohe.gov.my/warga/muat-turun/pekeliling/kewangan",
        "doc_type": "circular",
        "playwright_required": False,
    },
    {
        "name": "circulars_pengurusan_rekod",
        "url_ms": "https://www.mohe.gov.my/warga/muat-turun/pekeliling/pengurusan-rekod",
        "doc_type": "circular",
        "playwright_required": False,
    },
    {
        "name": "forms",
        "url_ms": "https://www.mohe.gov.my/warga/muat-turun/borang",
        "url_en": "https://www.mohe.gov.my/en/staff/downloads/forms",
        "doc_type": "form",
        "playwright_required": True,
    },
    {
        "name": "broadcasts",
        "url_ms": "https://www.mohe.gov.my/warga/muat-turun/hebahan-warga",
        "url_en": "https://www.mohe.gov.my/en/staff/downloads/broadcasts",
        "doc_type": "announcement",
        "playwright_required": False,
    },
    {
        "name": "manuals_guidelines",
        "url_ms": "https://www.mohe.gov.my/warga/muat-turun/manual-dan-garis-panduan",
        "url_en": "https://www.mohe.gov.my/en/staff/downloads/manuals-and-guidelines",
        "doc_type": "manual",
        "playwright_required": False,
    },
    {
        "name": "faq_downloads",
        "url_ms": "https://www.mohe.gov.my/warga/muat-turun/soalan-lazim",
        "url_en": "https://www.mohe.gov.my/en/staff/downloads/faq",
        "doc_type": "other",
        "playwright_required": False,
    },
]


# ---------------------------------------------------------------------------
# RSS parsing helpers
# ---------------------------------------------------------------------------

def _parse_rss_feed(xml_content: str) -> list[dict]:
    """Parse an RSS 2.0 XML string and return item dicts.

    Each dict contains: title, link, description, pub_date (raw string).
    Items without a ``<link>`` element are silently dropped.
    """
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        log.warning(f"[mohe] Failed to parse RSS XML: {exc}")
        return []

    items: list[dict] = []
    for item_el in root.findall(".//item"):
        title_el = item_el.find("title")
        link_el = item_el.find("link")
        desc_el = item_el.find("description")
        pubdate_el = item_el.find("pubDate")

        link = link_el.text.strip() if link_el is not None and link_el.text else ""
        if not link:
            continue

        items.append({
            "title": title_el.text.strip() if title_el is not None and title_el.text else "Untitled",
            "link": link,
            "description": desc_el.text.strip() if desc_el is not None and desc_el.text else "",
            "pub_date": pubdate_el.text.strip() if pubdate_el is not None and pubdate_el.text else "",
        })

    return items


def _parse_rss_date(raw: str) -> str:
    """Parse an RSS pubDate string to YYYY-MM-DD using the shared Malay parser.

    RSS feeds may use RFC 2822 (``Thu, 27 Feb 2026 10:00:00 GMT``) or
    Malay dates (``27 Februari 2026 10:00:00 GMT``).  ``parse_malay_date``
    handles both.
    """
    return parse_malay_date(raw)


# ---------------------------------------------------------------------------
# DOCman HTML helpers
# ---------------------------------------------------------------------------

def _extract_docman_items(html: str, base_url: str) -> list[dict]:
    """Extract items from a DOCman ``k-js-documents-table`` HTML page.

    Returns list of dicts with keys: title, href, date_text, source_url.
    Only rows containing an ``<a>`` whose ``href`` includes ``/file`` are
    considered (header rows and non-download rows are excluded).
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one(".k-js-documents-table")
    if not table:
        log.debug(f"[mohe] No DOCman table found on page")
        return []

    items: list[dict] = []
    for row in table.select("tr"):
        # Find the download anchor — must contain /file in href
        anchor = row.select_one("a[href*='/file']")
        if not anchor:
            continue

        raw_href = anchor.get("href", "").strip()
        if not raw_href:
            continue

        title = anchor.get_text(strip=True)

        # Date is typically in the second <td> cell
        date_text = ""
        cells = row.find_all("td")
        if len(cells) >= 2:
            date_text = cells[1].get_text(strip=True)

        items.append({
            "title": title or "Untitled",
            "href": raw_href,
            "date_text": date_text,
            "source_url": base_url,
        })

    log.info(f"[mohe] Extracted {len(items)} DOCman items from {base_url}")
    return items


def _is_docman_file_url(url: str) -> bool:
    """Return True if the URL is a DOCman /file binary download endpoint."""
    return url.rstrip("/").endswith("/file")


# ---------------------------------------------------------------------------
# Joomla article helpers (for RSS-discovered HTML pages)
# ---------------------------------------------------------------------------

def _extract_article_meta(html: str) -> dict:
    """Extract title and published date from a Joomla article detail page.

    Returns ``{"title": str, "published_at": str}``.
    """
    soup = BeautifulSoup(html, "lxml")
    title = ""
    published_at = ""

    # Title: <h1 itemprop="headline">, then <article> > h1/h2, then og:title
    h1 = soup.find("h1", itemprop="headline")
    if h1:
        title = h1.get_text(strip=True)

    if not title:
        container = soup.find("article") or soup.find("div", class_=re.compile(r"\bitem-page\b"))
        if container:
            h_tag = container.find(["h1", "h2"])
            if h_tag:
                title = h_tag.get_text(strip=True)

    if not title:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()

    # Date: time[itemprop="datePublished"], article:published_time meta
    time_pub = soup.find("time", itemprop="datePublished")
    if time_pub:
        dt_attr = time_pub.get("datetime", "")
        if dt_attr:
            published_at = parse_malay_date(dt_attr)
        if not published_at:
            published_at = parse_malay_date(time_pub.get_text(strip=True))

    if not published_at:
        meta = soup.find("meta", property="article:published_time")
        if meta and meta.get("content"):
            published_at = parse_malay_date(meta["content"])

    return {"title": title, "published_at": published_at}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@register_adapter
class MoheAdapter(BaseSiteAdapter):
    """Adapter for the Ministry of Higher Education (MOHE) website.

    Combines two discovery strategies:

    * RSS feeds — 8 bilingual feeds covering announcements, media statements,
      activities, media coverage, infographics, speeches, FAQs, and tenders.
    * DOCman listing pages — staff download sections for circulars, forms,
      manuals, guidelines, broadcasts, and FAQ documents.
    """

    slug = "mohe"
    agency = "Kementerian Pengajian Tinggi (MOHE)"
    requires_browser = False  # DOCman tables are server-rendered HTML

    # -- HOOK 1: Discovery --------------------------------------------------

    def discover(
        self, since: date | None = None, max_pages: int = 0
    ) -> Iterable[DiscoveredItem]:
        """Yield DiscoveredItems from RSS feeds and DOCman listing pages."""
        yield from self._discover_rss_feeds(since=since)
        yield from self._discover_docman_pages(since=since, max_pages=max_pages)

    # -- RSS discovery ------------------------------------------------------

    def _discover_rss_feeds(
        self, since: date | None = None
    ) -> Iterable[DiscoveredItem]:
        """Crawl all configured RSS feeds and yield DiscoveredItems."""
        base_url = self.config.get("base_url", _BASE_URL)
        feeds = self.config.get("rss_feeds", _DEFAULT_RSS_FEEDS)

        for feed in feeds:
            feed_name = feed.get("name", "unknown")

            for lang in ("en", "ms"):
                url_key = f"url_{lang}"
                feed_url = feed.get(url_key)
                if not feed_url:
                    continue

                log.info(f"[mohe] Fetching RSS feed: {feed_name} ({lang}) {feed_url}")

                try:
                    resp = self.http.get(feed_url)
                    xml_text = resp.text
                except Exception as exc:
                    log.warning(f"[mohe] Failed to fetch RSS feed {feed_url}: {exc}")
                    continue

                items = _parse_rss_feed(xml_text)
                log.info(f"[mohe] Parsed {len(items)} items from {feed_name} ({lang})")

                for item in items:
                    # Resolve relative link against base URL
                    source_url = urljoin(base_url, item["link"])

                    # Parse date
                    pub_date = _parse_rss_date(item["pub_date"])

                    # Apply --since filter
                    if since and pub_date:
                        try:
                            if date.fromisoformat(pub_date) < since:
                                continue
                        except ValueError:
                            pass

                    yield DiscoveredItem(
                        source_url=source_url,
                        title=item["title"],
                        published_at=pub_date,
                        doc_type=feed.get("doc_type", "other"),
                        language=lang,
                        metadata={
                            "feed_name": feed_name,
                            "feed_url": feed_url,
                            "description": item.get("description", ""),
                        },
                    )

    # -- DOCman discovery ---------------------------------------------------

    def _discover_docman_pages(
        self, since: date | None = None, max_pages: int = 0
    ) -> Iterable[DiscoveredItem]:
        """Crawl DOCman listing pages and yield DiscoveredItems for /file links."""
        base_url = self.config.get("base_url", _BASE_URL)
        listing_pages = self.config.get("listing_pages", _DEFAULT_LISTING_PAGES)
        pages_fetched = 0

        for page_cfg in listing_pages:
            page_name = page_cfg.get("name", "unknown")

            # Skip JS-rendered pages unless browser is available
            if page_cfg.get("playwright_required", False) and not self.requires_browser:
                log.info(
                    f"[mohe] Skipping JS-rendered DOCman page (playwright_required): "
                    f"{page_name}"
                )
                continue

            # Build (url, language) pairs
            urls_to_crawl: list[tuple[str, str]] = []
            if "url_ms" in page_cfg:
                urls_to_crawl.append((page_cfg["url_ms"], "ms"))
            if "url_en" in page_cfg:
                urls_to_crawl.append((page_cfg["url_en"], "en"))

            for listing_url, lang in urls_to_crawl:
                if max_pages and pages_fetched >= max_pages:
                    log.info(f"[mohe] max_pages={max_pages} reached, stopping DOCman discovery")
                    return

                log.info(f"[mohe] Fetching DOCman page: {page_name} ({lang}) {listing_url}")

                try:
                    resp = self.http.get(listing_url)
                    html = resp.text
                except Exception as exc:
                    log.warning(
                        f"[mohe] Failed to fetch DOCman page {listing_url}: {exc}"
                    )
                    continue

                pages_fetched += 1
                items = _extract_docman_items(html, listing_url)

                for item in items:
                    href = urljoin(base_url, item["href"])

                    # Parse Malay date
                    pub_date = parse_malay_date(item["date_text"]) if item["date_text"] else ""

                    # Apply --since filter
                    if since and pub_date:
                        try:
                            if date.fromisoformat(pub_date) < since:
                                continue
                        except ValueError:
                            pass

                    yield DiscoveredItem(
                        source_url=href,
                        title=item["title"],
                        published_at=pub_date,
                        doc_type=page_cfg.get("doc_type", "other"),
                        language=lang,
                        metadata={
                            "listing_page": page_name,
                            "listing_url": listing_url,
                            "date_text": item["date_text"],
                            "is_file_download": _is_docman_file_url(href),
                        },
                    )

    # -- HOOK 2: Fetch + Extract Downloads ----------------------------------

    def fetch_and_extract(self, item: DiscoveredItem) -> Iterable[DocumentCandidate]:
        """Given a discovered item, yield DocumentCandidates for download.

        Two code-paths:

        1. **DOCman /file links** — the source URL *is* the binary download.
           Yield a single DocumentCandidate pointing directly at the file.
        2. **RSS article pages** — fetch the Joomla HTML article, enrich title
           and date from the page metadata, yield the HTML page itself plus any
           embedded PDF/DOC links found in the article body.
        """
        source_url = item.source_url

        # Path 1: DOCman /file endpoint — direct binary download
        if item.metadata.get("is_file_download") or _is_docman_file_url(source_url):
            # DOCman files are typically PDF; guess from URL
            ct = guess_content_type(source_url)
            # DOCman /file URLs do not have a file extension, default to PDF
            if ct == "application/octet-stream":
                ct = "application/pdf"

            yield DocumentCandidate(
                url=source_url,
                source_page_url=item.metadata.get("listing_url", source_url),
                title=item.title,
                published_at=item.published_at,
                doc_type=item.doc_type,
                content_type=ct,
                language=item.language,
            )
            return

        # Path 2: Direct document link (PDF etc. from RSS description)
        url_lower = source_url.lower().split("?")[0]
        doc_extensions = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")
        if any(url_lower.endswith(ext) for ext in doc_extensions):
            yield DocumentCandidate(
                url=source_url,
                source_page_url=item.metadata.get("feed_url", source_url),
                title=item.title,
                published_at=item.published_at,
                doc_type=item.doc_type,
                content_type=guess_content_type(source_url),
                language=item.language,
            )
            return

        # Path 3: Joomla HTML article page (RSS items)
        try:
            resp = self.http.get(source_url)
            html = resp.text
        except Exception as exc:
            log.warning(f"[mohe] Failed to fetch article {source_url}: {exc}")
            return

        # Enrich metadata from the article detail page
        meta = _extract_article_meta(html)
        title = meta.get("title") or item.title
        published_at = meta.get("published_at") or item.published_at

        # Yield the HTML page itself
        yield DocumentCandidate(
            url=source_url,
            source_page_url=item.metadata.get("feed_url", source_url),
            title=title,
            published_at=published_at,
            doc_type=item.doc_type,
            content_type="text/html",
            language=item.language,
        )

        # Extract and yield embedded document links from article body
        base_url = self.config.get("base_url", _BASE_URL)
        embedded_links = self._extract_article_doc_links(html, base_url)

        for dl in embedded_links:
            ct = guess_content_type(dl.url)
            yield DocumentCandidate(
                url=dl.url,
                source_page_url=source_url,
                title=title,
                published_at=published_at,
                doc_type=item.doc_type,
                content_type=ct,
                language=item.language,
            )

    # -- HOOK 3: Download Link Extraction (override) ------------------------

    def extract_downloads(self, html: str, base_url: str) -> list[DownloadLink]:
        """MOHE-specific download extraction.

        First tries scoped article-body extraction, then falls back to the
        generic extractor.
        """
        links = self._extract_article_doc_links(html, base_url)
        if links:
            return links
        return extract_document_links(html, base_url)

    @staticmethod
    def _extract_article_doc_links(html: str, base_url: str) -> list[DownloadLink]:
        """Find document download links within a Joomla article body.

        Scopes to ``itemprop="articleBody"``, ``<article>``, or
        ``.item-page`` container to avoid navigation noise.
        """
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        links: list[DownloadLink] = []

        doc_extensions = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")

        # Scope to article body container
        content = (
            soup.find(itemprop="articleBody")
            or soup.find(attrs={"itemprop": "articleBody"})
            or soup.find("article")
            or soup.find("div", class_=re.compile(r"\bitem-page\b"))
            or soup
        )

        for a_tag in content.find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href or href.startswith(("javascript:", "#", "mailto:")):
                continue

            href_lower = href.lower().split("?")[0]

            # Document extension match
            is_doc = any(href_lower.endswith(ext) for ext in doc_extensions)
            # DOCman /file endpoint match
            is_docman = href_lower.rstrip("/").endswith("/file")

            if is_doc or is_docman:
                abs_url = urljoin(base_url, href)
                if abs_url not in seen:
                    seen.add(abs_url)
                    label = a_tag.get_text(strip=True) or href
                    links.append(DownloadLink(url=abs_url, label=label))

        return links
