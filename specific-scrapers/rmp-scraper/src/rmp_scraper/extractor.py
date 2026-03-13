"""
RMP-specific HTML extractors for www.rmp.gov.my (Sitefinity 6 CMS).

Site overview
─────────────
RMP uses Telerik Sitefinity 6.3.5000.0 PE (ASP.NET). All content is
server-rendered — no JavaScript required for extraction. There is no
sitemap.xml; content is discovered via seeded listing URLs.

Listing page archetype – Sitefinity news listing
─────────────────────────────────────────────────
News and media statement sections render a list of items where each
article link carries a Sitefinity data attribute:

    <div class="sfnewsItem">
      <h2 class="sfnewsItemTitle">
        <a data-sf-field="Title" data-sf-ftype="ShortText"
           href="/arkib-berita/berita/2026/03/09/title-slug">
          ARTICLE TITLE
        </a>
      </h2>
      <div class="sfnewsMetaInfo">
        <ul>
          <li class="sfnewsDate">09 March 2026</li>
        </ul>
      </div>
    </div>

Pagination – Sitefinity numeric pager (/page/N path style)
───────────────────────────────────────────────────────────
    <div class="sf_pagerNumeric">
      <a class="sf_PagerCurrent"
         href="https://www.rmp.gov.my/arkib-berita/berita">1</a>
      <a href="https://www.rmp.gov.my/arkib-berita/berita/page/2">2</a>
      <a href="https://www.rmp.gov.my/arkib-berita/berita/page/3">3</a>
    </div>

    Pages are path-based (/page/N). Stops when no link with a higher
    page number than current is found.

Publications listing – Telerik RadGrid table
─────────────────────────────────────────────
Publications are rendered in a Telerik RadGrid:

    <table class="rgMasterTable">
      <tbody>
        <tr class="sfpdf">
          <td>Berita Bukit Aman Bil. 3 2025</td>
          <td>
            <a class="sfdownloadLink"
               href="/docs/default-source/Penerbitan/berita-bukit-aman-bil-3-2025.pdf?sfvrsn=2">
              Download
            </a>
          </td>
        </tr>
      </tbody>
    </table>

Article detail page
────────────────────
    <meta property="og:title" content="Article Title" />
    <!-- Date embedded in URL path: /YYYY/MM/DD/slug -->
    <div class="sfnewsMetaInfo">
      <ul>
        <li class="sfnewsDate">09 March 2026</li>
      </ul>
    </div>
    <div class="sfnewsContent">
      ...
      <a href="/docs/default-source/category/document.pdf?sfvrsn=2">Download</a>
    </div>
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

# Regex to detect a date embedded in a URL path: /YYYY/MM/DD/
_URL_DATE_RE = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/")


def _normalize_malay_months(text: str) -> str:
    """Replace Malay month names with English equivalents for dateutil."""
    for malay, english in _MALAY_MONTHS.items():
        text = text.replace(malay, english)
    return text


# ── Date parsing ───────────────────────────────────────────────────────────────


def parse_rmp_date(date_str: str) -> str:
    """
    Parse RMP date strings into ISO 8601 dates (YYYY-MM-DD).

    Input examples:
        "09 March 2026"             → "2026-03-09"
        "09 Mac 2026"               → "2026-03-09"
        "2026-03-09T00:00:00+08:00" → "2026-03-09"
        "09/03/2026"                → "2026-03-09"
        "March 9, 2026"             → "2026-03-09"

    Returns "" on failure.
    """
    if not date_str or not date_str.strip():
        return ""

    normalized = _normalize_malay_months(date_str.strip())
    cleaned = re.sub(r"^[^\d]+", "", normalized)
    if not cleaned:
        return ""

    # ISO 8601 strings start with YYYY-MM-DD; parse with dayfirst=False to
    # avoid swapping month and day. Human-readable strings ("09 March 2026",
    # "09/03/2026") need dayfirst=True.
    _ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
    use_dayfirst = not _ISO_RE.match(cleaned)

    try:
        dt = dateutil_parser.parse(cleaned, dayfirst=use_dayfirst)
        return dt.date().isoformat()
    except (ValueError, OverflowError):
        log.warning(
            {"event": "date_parse_failure", "raw": date_str, "category": "parse"}
        )
        return ""


def date_from_url(url: str) -> str:
    """
    Extract a publication date from a Sitefinity URL path.

    Sitefinity news URLs embed the date as: /YYYY/MM/DD/slug
    e.g. /arkib-berita/berita/2026/03/09/kenyataan-media → "2026-03-09"

    Returns "" if no date pattern is found.
    """
    match = _URL_DATE_RE.search(url)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month}-{day}"
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


# ── 1. Sitefinity news/media-statement listing extractor ─────────────────────


def extract_sitefinity_listing_items(html: str, source_url: str) -> list:
    """
    Extract article links from a Sitefinity news listing page.

    Used for: Berita (News) and Siaran Media (Media Statements) sections.

    Each item is identified by the data-sf-field="Title" attribute on the
    anchor tag. Falls back to any anchor inside sfnewsItem containers if
    the data-sf-field attribute is absent.

    Returns list of dicts:
        {
            "title":      str,
            "href":       str,
            "date_text":  str,   # raw date text, e.g. "09 March 2026"
            "source_url": str,
        }
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    seen_hrefs: set = set()

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
            meta_div = parent.find(
                class_=re.compile(r"\bsfnewsMetaInfo\b")
            )
            if meta_div:
                date_li = meta_div.find(
                    class_=re.compile(r"\bsfnewsDate\b")
                )
                if date_li:
                    date_text = date_li.get_text(strip=True)
                else:
                    # Any text node that looks like a date
                    date_text = meta_div.get_text(" ", strip=True)

        # Last resort: extract date from href (Sitefinity embeds /YYYY/MM/DD/)
        if not date_text:
            date_text = date_from_url(href)

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


# ── 2. Sitefinity publications grid extractor ─────────────────────────────────


def extract_sitefinity_publications(html: str, source_url: str) -> list:
    """
    Extract document download links from a Sitefinity RadGrid publications page.

    The publications section renders documents in a Telerik RadGrid table:

        <table class="rgMasterTable">
          <tbody>
            <tr class="sfpdf">
              <td>Document Title</td>
              <td>
                <a class="sfdownloadLink"
                   href="/docs/default-source/.../filename.pdf?sfvrsn=2">Download</a>
              </td>
            </tr>
          </tbody>
        </table>

    Returns list of dicts:
        {
            "title":      str,
            "href":       str,   # absolute or relative download URL
            "date_text":  str,   # "" (publications rarely show dates)
            "source_url": str,
        }
    """
    soup = BeautifulSoup(html, "lxml")
    items = []
    seen_hrefs: set = set()

    table = soup.find("table", class_=re.compile(r"\brgMasterTable\b"))
    if not table:
        log.debug(
            {
                "event": "no_publications_table",
                "source_url": source_url,
            }
        )
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
            # Skip cells that only contain the download link
            if td.find("a", class_="sfdownloadLink"):
                continue
            cell_text = td.get_text(strip=True)
            if cell_text:
                title = cell_text
                break
        if not title:
            title = dl_link.get_text(strip=True) or href.split("/")[-1].split("?")[0]

        items.append(
            {
                "title": title,
                "href": href,
                "date_text": "",
                "source_url": source_url,
            }
        )

    log.info(
        {
            "event": "publications_extracted",
            "source_url": source_url,
            "item_count": len(items),
        }
    )
    return items


# ── 3. Sitefinity pagination detection ────────────────────────────────────────


def get_next_page_url(html: str, current_url: str, current_page: int) -> Optional[str]:
    """
    Return the URL of the next page in a Sitefinity numeric pager, or None.

    Sitefinity uses path-based pagination: /page/N appended to the listing URL.
    The pager container is: <div class="sf_pagerNumeric">

    Strategy:
      1. Find the sf_pagerNumeric div.
      2. Collect all /page/N links.
      3. Return the link with page number = current_page + 1, if it exists.
    """
    soup = BeautifulSoup(html, "lxml")
    pager = soup.find(class_=re.compile(r"\bsf_pagerNumeric\b"))
    if not pager:
        return None

    next_page = current_page + 1
    for a in pager.find_all("a", href=True):
        href = a["href"]
        # Match /page/N at end of URL
        match = re.search(r"/page/(\d+)(?:[/?#]|$)", href)
        if match and int(match.group(1)) == next_page:
            return href

    return None


def has_more_pages(html: str, current_page: int) -> bool:
    """
    Check whether the Sitefinity pager has a page beyond current_page.

    Returns True if a link to page (current_page + 1) exists.
    """
    return get_next_page_url(html, "", current_page) is not None


# ── 4. Article detail page extractor ─────────────────────────────────────────


def extract_rmp_article_meta(html: str, source_url: str) -> dict:
    """
    Extract title and published date from a Sitefinity RMP article page.

    Title extraction order (highest priority first):
      1. <h1 class="sfnewsTitle"> or <h1 class="sfArticleTitle">
      2. <meta property="og:title">
      3. <title> tag (stripped of " | Polis DiRaja Malaysia" suffix)

    Published date extraction order:
      1. Date embedded in source URL (/YYYY/MM/DD/)
      2. <li class="sfnewsDate"> in sfnewsMetaInfo
      3. <meta property="article:published_time">
      4. <time datetime="...">

    Returns:
        {
            "title":        str,
            "published_at": str,   # ISO date "YYYY-MM-DD" or ""
        }
    """
    soup = BeautifulSoup(html, "lxml")

    # ── Title ─────────────────────────────────────────────────────────────────
    title = ""

    # 1. Sitefinity article title h1 variants
    for cls in ("sfnewsTitle", "sfArticleTitle", "sfContentTitle"):
        h1 = soup.find("h1", class_=re.compile(rf"\b{cls}\b"))
        if h1:
            title = h1.get_text(strip=True)
            break

    # 2. og:title
    if not title:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()

    # 3. <title> tag — strip common suffixes
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

    # 1. Date from URL path (most reliable for Sitefinity)
    published_at = date_from_url(source_url)

    # 2. sfnewsMetaInfo date element
    if not published_at:
        meta_info = soup.find(class_=re.compile(r"\bsfnewsMetaInfo\b"))
        if meta_info:
            date_el = meta_info.find(class_=re.compile(r"\bsfnewsDate\b"))
            if date_el:
                published_at = parse_rmp_date(date_el.get_text(strip=True))
            if not published_at:
                published_at = parse_rmp_date(meta_info.get_text(" ", strip=True))

    # 3. article:published_time meta
    if not published_at:
        meta = soup.find("meta", property="article:published_time")
        if meta and meta.get("content"):
            published_at = parse_rmp_date(meta["content"])

    # 4. <time datetime="...">
    if not published_at:
        time_el = soup.find("time", attrs={"datetime": True})
        if time_el:
            published_at = parse_rmp_date(time_el["datetime"])

    return {"title": title, "published_at": published_at}


# ── 5. Embedded document link extractor ───────────────────────────────────────


def extract_embedded_doc_links(html: str, base_url: str) -> list:
    """
    Find all document download links embedded in an RMP article page.

    Scopes to Sitefinity content containers (sfnewsContent, sfContentBlock,
    sfArticleContainer) to avoid navigation noise. Falls back to full document.

    Captures:
      - <a href> links ending in document extensions (.pdf, .docx, etc.)
      - Sitefinity document links under /docs/default-source/

    Returns a deduplicated list of absolute document URLs.
    Note: host allowlist filtering is done in the pipeline, not here.
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")
    seen: set = set()
    links = []

    # Scope to article body containers
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
            abs_url = make_absolute(href, base_url)
            if abs_url not in seen:
                seen.add(abs_url)
                links.append(abs_url)

    return links
