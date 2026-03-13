"""
MOH-specific HTML extractors for www.moh.gov.my (Joomla 4 CMS).

Site overview
─────────────
MOH uses Joomla 4 with the com_content component for all news and publications.
There is no sitemap.xml; content is discovered through seeded listing URLs.

Listing page archetype – Joomla 4 category table view
──────────────────────────────────────────────────────
All supported sections render a standard Joomla category table:

    <table class="com-content-category__table category table ...">
      <thead>
        <tr>
          <th class="list-title">Tajuk</th>
          <th class="list-date">Tarikh</th>
        </tr>
      </thead>
      <tbody>
        <tr class="cat-list-row0 row-fluid">
          <td class="list-title">
            <a href="/en/media-kkm/media-statement/2026/SLUG">Title</a>
          </td>
          <td class="list-date small">23-02-2026</td>
        </tr>
        ...
      </tbody>
    </table>

Pagination – Joomla 4 offset-based (?start=N)
──────────────────────────────────────────────
    <div class="com-content-category__pagination btn-group float-end" role="group">
      <a href="/en/.../" class="btn btn-secondary active">1</a>
      <a href="/en/.../?start=10" class="btn btn-secondary">2</a>
      <a href="/en/.../?start=20" class="btn btn-secondary">3</a>
    </div>

    Offset increments by page_size (default 10). Pagination stops when the
    extracted item list is empty (one extra empty request per section).
    has_more_pages() provides an early-stop check from the pagination widget.

Article detail page (Joomla 4 microdata)
─────────────────────────────────────────
    <article>
      <h1 itemprop="headline">Title</h1>
      <div class="article-info">
        <time datetime="2026-02-23T00:00:00+08:00" itemprop="datePublished">
          23 February 2026
        </time>
      </div>
      <div itemprop="articleBody">
        ...
        <a href="/images/kenyataan-media/2026/FEB/document.pdf">Download PDF</a>
      </div>
    </article>
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

log = logging.getLogger(__name__)

_DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")

# Malay → English month name map for dateutil compatibility
_MALAY_MONTHS: dict = {
    "Januari": "January",
    "Februari": "February",
    "Mac": "March",
    "April": "April",
    "Mei": "May",
    "Jun": "June",
    "Julai": "July",
    "Ogos": "August",
    "September": "September",
    "Oktober": "October",
    "November": "November",
    "Disember": "December",
}


def _normalize_malay_months(text: str) -> str:
    """Replace Malay month names with English equivalents for dateutil."""
    for malay, english in _MALAY_MONTHS.items():
        text = text.replace(malay, english)
    return text


# ── Date parsing ───────────────────────────────────────────────────────────────


def parse_moh_date(date_str: str) -> str:
    """
    Parse MOH date strings into ISO 8601 dates (YYYY-MM-DD).

    Input examples:
        "23-02-2026"                       → "2026-02-23"
        "2026-02-23T00:00:00+08:00"        → "2026-02-23"
        "23 February 2026"                 → "2026-02-23"
        "23 Feb 2026"                      → "2026-02-23"
        "Published: 23 February 2026"      → "2026-02-23"

    Returns "" on failure.
    """
    if not date_str or not date_str.strip():
        return ""

    # Normalize Malay month names before stripping prefix
    normalized = _normalize_malay_months(date_str.strip())

    # Strip any non-digit prefix (e.g. "Published: ", "Diterbitkan: ")
    cleaned = re.sub(r"^[^\d]+", "", normalized)
    if not cleaned:
        return ""

    try:
        dt = dateutil_parser.parse(cleaned, dayfirst=True)
        return dt.date().isoformat()
    except (ValueError, OverflowError):
        log.warning(
            {"event": "date_parse_failure", "raw": date_str, "category": "parse"}
        )
        return ""


# ── Content-type inference ─────────────────────────────────────────────────────


def guess_content_type(url: str) -> str:
    """Infer MIME type from file extension in URL path."""
    path = urlparse(url).path.lower()
    ext_map = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".ppt": "application/vnd.ms-powerpoint",
        ".zip": "application/zip",
    }
    for ext, mime in ext_map.items():
        if path.endswith(ext):
            return mime
    return "text/html"


# ── 1. Joomla category listing extractor ──────────────────────────────────────


def extract_joomla_listing_items(html: str, source_url: str) -> list:
    """
    Extract article links from a Joomla 4 com_content category table page.

    Used for: Media Statements, Speech Texts, Circulars, Bulletins, and
    any other section rendered with the standard Joomla category table view.

    Returns list of dicts:
        {
            "title":      str,
            "href":       str,
            "date_text":  str,   # raw text from td.list-date, e.g. "23-02-2026"
            "source_url": str,
        }
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    seen_hrefs: set = set()

    table = soup.find("table", class_=re.compile(r"\bcom-content-category__table\b"))
    if not table:
        log.debug(
            {
                "event": "no_listing_table",
                "source_url": source_url,
            }
        )
        return []

    tbody = table.find("tbody")
    if not tbody:
        return []

    for tr in tbody.find_all("tr"):
        # First anchor in the row is the article link
        a_tag = tr.find("a", href=True)
        if not a_tag:
            continue

        href = a_tag["href"].strip()
        if href in seen_hrefs or href.startswith(("javascript:", "#", "mailto:")):
            continue
        seen_hrefs.add(href)

        title = a_tag.get_text(strip=True)

        # Date: td whose class contains "list-date"
        date_td = tr.find("td", class_=re.compile(r"\blist-date\b"))
        date_text = date_td.get_text(strip=True) if date_td else ""

        items.append(
            {
                "title": title,
                "href": href,
                "date_text": date_text,
                "source_url": source_url,
            }
        )

    log.info(
        {
            "event": "listing_extracted",
            "source_url": source_url,
            "item_count": len(items),
        }
    )
    return items


# ── 2. Pagination detection ────────────────────────────────────────────────────


def has_more_pages(html: str, current_offset: int) -> bool:
    """
    Check whether the Joomla 4 pagination widget shows a page beyond
    the current offset.

    Joomla 4 pagination container:
        <div class="com-content-category__pagination btn-group float-end">
          <a href="/en/.../" ...>1</a>
          <a href="/en/.../?start=10" ...>2</a>
          <a href="/en/.../?start=20" ...>3</a>
        </div>

    Returns True if any link has a start= value greater than current_offset.
    Returns False if no such link exists (current page is the last page).
    """
    soup = BeautifulSoup(html, "lxml")
    pag = soup.find(
        "div", class_=re.compile(r"\bcom-content-category__pagination\b")
    )
    if not pag:
        return False

    for a in pag.find_all("a", href=True):
        href = a["href"]
        if "start=" in href:
            try:
                raw = href.split("start=")[1].split("&")[0].split("#")[0]
                val = int(raw)
                if val > current_offset:
                    return True
            except (ValueError, IndexError):
                pass

    return False


# ── 3. Article detail page extractor ─────────────────────────────────────────


def extract_moh_article_meta(html: str, source_url: str) -> dict:
    """
    Extract title and published date from a Joomla 4 MOH article page.

    Title extraction order (highest priority first):
      1. <h1 itemprop="headline">
      2. <h1> or <h2> inside <article> or .item-page
      3. <meta property="og:title">
      4. <title> tag (stripped of " | MOH" / " | Kementerian" suffix)

    Published date extraction order:
      1. <time itemprop="datePublished" datetime="...">  — ISO datetime attr
      2. <time itemprop="dateModified" datetime="...">   — fallback
      3. <meta property="article:published_time">
      4. Visible text of <time itemprop="datePublished"> — parsed via dateutil

    Returns:
        {
            "title":        str,
            "published_at": str,   # ISO date "YYYY-MM-DD" or ""
        }
    """
    soup = BeautifulSoup(html, "lxml")

    # ── Title ─────────────────────────────────────────────────────────────────
    title = ""

    # 1. h1 with Joomla 4 microdata
    h1_micro = soup.find("h1", itemprop="headline")
    if h1_micro:
        title = h1_micro.get_text(strip=True)

    # 2. h1/h2 inside <article> or .item-page container
    if not title:
        container = (
            soup.find("article")
            or soup.find("div", class_=re.compile(r"\bitem-page\b"))
            or soup.find("div", class_=re.compile(r"\bcom-content-article\b"))
        )
        if container:
            h_tag = container.find(["h1", "h2"])
            if h_tag:
                title = h_tag.get_text(strip=True)

    # 3. og:title
    if not title:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()

    # 4. <title> tag — strip common suffixes
    if not title:
        tag = soup.find("title")
        if tag:
            raw = tag.get_text(strip=True)
            for sep in (" | ", " - ", " – "):
                if sep in raw:
                    title = raw.split(sep)[0].strip()
                    break
            else:
                title = raw

    # ── Published date ────────────────────────────────────────────────────────
    published_at = ""

    # 1. time[itemprop="datePublished"] — prefer datetime attribute
    time_pub = soup.find("time", itemprop="datePublished")
    if time_pub:
        dt_attr = time_pub.get("datetime", "")
        if dt_attr:
            published_at = parse_moh_date(dt_attr)
        if not published_at:
            published_at = parse_moh_date(time_pub.get_text(strip=True))

    # 2. time[itemprop="dateModified"] — fallback
    if not published_at:
        time_mod = soup.find("time", itemprop="dateModified")
        if time_mod:
            dt_attr = time_mod.get("datetime", "")
            if dt_attr:
                published_at = parse_moh_date(dt_attr)

    # 3. article:published_time meta
    if not published_at:
        meta = soup.find("meta", property="article:published_time")
        if meta and meta.get("content"):
            published_at = parse_moh_date(meta["content"])

    return {"title": title, "published_at": published_at}


# ── 4. Embedded document link extractor ───────────────────────────────────────


def extract_embedded_doc_links(html: str, base_url: str) -> list:
    """
    Find all document download links embedded in a MOH article page.

    Scopes to the article body (itemprop="articleBody", <article>, .item-page)
    to avoid navigation noise. Falls back to the full document if no body
    container is found.

    Captures:
      - <a href> links ending in document extensions (.pdf, .docx, etc.)
      - MOH PDF convention: /images/... paths with .pdf extension

    Returns a deduplicated list of absolute document URLs.
    Note: host allowlist filtering is done in the pipeline, not here.
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")
    seen: set = set()
    links = []

    # Scope to article body
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
        if any(href_lower.endswith(ext) for ext in _DOC_EXTENSIONS):
            abs_url = make_absolute(href, base_url)
            if abs_url not in seen:
                seen.add(abs_url)
                links.append(abs_url)

    return links
