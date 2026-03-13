"""
MCMC-specific HTML extractors for mcmc.gov.my (Kentico CMS, ASP.NET).

Listing page archetypes:

1. article_list  – Press Releases, Announcements, Press Clippings
   Listing HTML:
       <div class="article-listing">
         <div class="article-list-boxes clearfix">
           <div class="article-list-box clearfix">
             <div class="article-list-content">
               <div class="date">MAR 03, 2026</div>
               <h5><a href="/en/media/press-releases/SLUG">TITLE</a></h5>
               <a class="btn btn-secondary btn-sm" href="...pdf">Download PDF</a>
             </div>
           </div>
         </div>
       </div>

2. media_box  – Publications, Reports, Guidelines, Annual Reports
   Listing HTML:
       <a class="media-box" href="/en/resources/publications/SLUG">
         <div class="media-thumb highlight-img"></div>
         <div class="media-caption"><h4>TITLE</h4></div>
       </a>

Pagination (Bootstrap, both archetypes):
    <ul class="pagination">
      <li class="page-item active"><a class="page-link" href="?page=1">1</a></li>
      <li class="page-item"><a class="page-link" href="?page=2">2</a></li>
    </ul>
    URL pattern: ?page=N

3. acts_hub  – /en/legal/acts
   No pagination; one <h2> per Act with sibling anchors:
       <h2>Communications and Multimedia Act 1998 [Act 588]</h2>
       <a href="/en/legal/acts/communications-and-multimedia-act-1998-reprint-200">More Details</a>
       <a href="/skmmgovmy/media/General/pdf/Act588bi_3.pdf">Act PDF</a>
   Each item yields a detail_href (sub-page) and zero-or-more doc_hrefs (direct PDFs).

4. static_page  – /en/legal/dispute-resolution and similar single-page content
   No listing structure; the page itself is the single record.  All embedded PDF/DOCX
   links in the body are extracted as embedded documents.

Single article detail page:
    <h1>TITLE</h1>   (or og:title)
    <div class="date">03 Mar 2026</div>
    <div class="contentZone"> ... <a href="...pdf">Download</a> ... </div>
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


# ── Date parsing ───────────────────────────────────────────────────────────────


def parse_mcmc_date(date_str: str) -> str:
    """
    Parse MCMC English date strings into ISO 8601 dates (YYYY-MM-DD).

    Input examples:
        "MAR 03, 2026"     → "2026-03-03"
        "FEB 15, 2026"     → "2026-02-15"
        "03 Mar 2026"      → "2026-03-03"
        "3 March 2026"     → "2026-03-03"
        "January 15, 2025" → "2025-01-15"

    Returns "" on failure.
    """
    if not date_str or not date_str.strip():
        return ""
    try:
        dt = dateutil_parser.parse(date_str.strip(), dayfirst=False)
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


# ── 1. article_list listing extractor ─────────────────────────────────────────


def extract_article_list_items(html: str, source_url: str) -> list[dict]:
    """
    Extract article links from an MCMC article-list-box listing page.

    Used for: Press Releases, Announcements, Press Clippings.

    Returns list of dicts:
        {
            "title":      str,
            "href":       str,
            "date_text":  str,   # raw text from div.date, e.g. "MAR 03, 2026"
            "pdf_href":   str,   # direct PDF link on listing row, or ""
            "source_url": str,
        }
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen_hrefs: set[str] = set()

    for box in soup.find_all("div", class_=re.compile(r"\barticle-list-box\b")):
        content = box.find("div", class_=re.compile(r"\barticle-list-content\b"))
        if not content:
            content = box

        # Title and article link
        a_tag = None
        heading = content.find(["h5", "h4", "h3", "h2"], recursive=False)
        if not heading:
            heading = content.find(["h5", "h4", "h3", "h2"])
        if heading:
            a_tag = heading.find("a", href=True)

        if not a_tag:
            # Broader fallback: first anchor inside this box
            a_tag = content.find("a", href=True)

        if not a_tag:
            continue

        href = a_tag["href"].strip()
        if href in seen_hrefs or href.startswith(("javascript:", "#", "mailto:")):
            continue
        seen_hrefs.add(href)

        title = a_tag.get_text(strip=True)

        # Date
        date_div = content.find("div", class_="date") or box.find("div", class_="date")
        date_text = date_div.get_text(strip=True) if date_div else ""

        # Direct PDF link on the listing row (e.g. "Download PDF" button)
        pdf_href = ""
        btn = content.find("a", class_=re.compile(r"\bbtn\b"), href=True)
        if btn:
            btn_href = btn["href"].strip().lower()
            if any(btn_href.endswith(ext) for ext in _DOC_EXTENSIONS):
                pdf_href = btn["href"].strip()

        items.append(
            {
                "title": title,
                "href": href,
                "date_text": date_text,
                "pdf_href": pdf_href,
                "source_url": source_url,
            }
        )

    log.info(
        {
            "event": "article_list_extracted",
            "source_url": source_url,
            "item_count": len(items),
        }
    )
    return items


# ── 2. media_box listing extractor ────────────────────────────────────────────


def extract_media_box_items(html: str, source_url: str) -> list[dict]:
    """
    Extract items from an MCMC media-box grid listing page.

    Used for: Publications, Reports, Guidelines, Annual Reports, Statistics.

    HTML structure:
        <a class="media-box" href="/en/resources/publications/SLUG">
          <div class="media-thumb highlight-img" style="background-image:url(...)">
          </div>
          <div class="media-caption">
            <h4>TITLE</h4>
          </div>
        </a>

    Returns list of dicts:
        {
            "title":      str,
            "href":       str,
            "date_text":  str,   # "" (date is on the detail page)
            "pdf_href":   str,   # "" (resolved on detail page)
            "source_url": str,
        }
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen_hrefs: set[str] = set()

    for a_tag in soup.find_all("a", class_=re.compile(r"\bmedia-box\b"), href=True):
        href = a_tag["href"].strip()
        if href in seen_hrefs or href.startswith(("javascript:", "#", "mailto:")):
            continue
        seen_hrefs.add(href)

        # Title from h4 inside .media-caption
        caption = a_tag.find("div", class_=re.compile(r"\bmedia-caption\b"))
        if caption:
            h_tag = caption.find(["h4", "h3", "h2"])
            title = h_tag.get_text(strip=True) if h_tag else caption.get_text(strip=True)
        else:
            title = a_tag.get_text(strip=True)

        items.append(
            {
                "title": title,
                "href": href,
                "date_text": "",
                "pdf_href": "",
                "source_url": source_url,
            }
        )

    log.info(
        {
            "event": "media_box_extracted",
            "source_url": source_url,
            "item_count": len(items),
        }
    )
    return items


# ── 3. Pagination ──────────────────────────────────────────────────────────────


def get_next_page_number(html: str) -> Optional[int]:
    """
    Detect the next page number from MCMC Bootstrap pagination.

    MCMC pagination:
        <ul class="pagination">
          <li class="page-item active"><a class="page-link" href="?page=1">1</a></li>
          <li class="page-item"><a class="page-link" href="?page=2">2</a></li>
        </ul>

    Returns the next page number integer, or None if on the last page.
    """
    soup = BeautifulSoup(html, "lxml")
    pagination = soup.find("ul", class_=re.compile(r"\bpagination\b"))
    if not pagination:
        return None

    # Find the active page item
    active_li = None
    for li in pagination.find_all("li", class_="page-item"):
        classes = li.get("class", [])
        if "active" in classes:
            active_li = li
            break

    if not active_li:
        return None

    current_a = active_li.find("a", class_="page-link")
    if not current_a:
        return None

    try:
        current_page = int(current_a.get_text(strip=True))
    except ValueError:
        return None

    next_page = current_page + 1

    # Check if next page link appears in the visible pagination
    for a in pagination.find_all("a", class_="page-link", href=True):
        href = a["href"]
        try:
            page_num = int(a.get_text(strip=True))
        except ValueError:
            continue
        if page_num == next_page:
            return next_page

    # Ellipsis / windowed pagination: an enabled "next" (» ›) button pointing
    # to a page AFTER the current one means there are more pages to fetch.
    # A disabled next-button has class "disabled" on its parent <li>.
    for li in pagination.find_all("li", class_="page-item"):
        if "disabled" in li.get("class", []):
            continue
        a = li.find("a", class_="page-link", href=True)
        if not a:
            continue
        href = a["href"]
        if href == "#":
            continue
        text = a.get_text(strip=True)
        # Only care about non-numeric links (prev/next icons, not page numbers)
        try:
            int(text)
            continue
        except ValueError:
            pass
        # Verify the link resolves to a page strictly after the current one
        if "page=" in href:
            try:
                target = int(href.split("page=")[-1].split("&")[0].split("#")[0])
                if target > current_page:
                    return next_page
            except ValueError:
                pass

    return None


# ── 4. Single article / detail page extractor ─────────────────────────────────


def extract_article_meta(html: str, source_url: str) -> dict:
    """
    Extract metadata from a single MCMC article or resource detail page.

    Extraction order (highest priority first):

    Title:
      1. <h1> inside main content area
      2. <meta property="og:title">
      3. <title> tag (stripped of " | MCMC" suffix)

    Published date:
      1. <div class="date"> text (e.g. "03 Mar 2026")
      2. <meta property="article:published_time">
      3. <meta name="date"> or <meta name="DC.date">

    Returns:
        {
            "title":        str,
            "published_at": str,   # ISO date "YYYY-MM-DD" or ""
        }
    """
    soup = BeautifulSoup(html, "lxml")

    # ── Title ─────────────────────────────────────────────────────────────────
    title = ""

    # Prefer h1 in main content area
    main_content = (
        soup.find("div", class_=re.compile(r"\bcontentZone\b|\barticle-content\b|\bcontent-area\b"))
        or soup.find("main")
        or soup
    )
    h1 = main_content.find("h1")
    if h1:
        title = h1.get_text(strip=True)

    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()

    if not title:
        title_tag = soup.find("title")
        if title_tag:
            raw = title_tag.get_text(strip=True)
            # Strip " | MCMC" or " - MCMC" suffix
            for sep in (" | ", " - ", " – "):
                if sep in raw:
                    title = raw.split(sep)[0].strip()
                    break
            else:
                title = raw

    # ── Published date ────────────────────────────────────────────────────────
    published_at = ""

    # 1. div.date (most reliable on MCMC pages)
    date_div = soup.find("div", class_="date")
    if date_div:
        published_at = parse_mcmc_date(date_div.get_text(strip=True))

    # 2. <meta property="article:published_time">
    if not published_at:
        meta_pub = soup.find("meta", property="article:published_time")
        if meta_pub and meta_pub.get("content"):
            published_at = parse_mcmc_date(meta_pub["content"])

    # 3. <meta name="date"> or <meta name="DC.date">
    if not published_at:
        for meta_name in ("date", "DC.date", "dc.date"):
            meta_date = soup.find("meta", attrs={"name": meta_name})
            if meta_date and meta_date.get("content"):
                published_at = parse_mcmc_date(meta_date["content"])
                if published_at:
                    break

    return {"title": title, "published_at": published_at}


# ── 5. Embedded document link extractor ───────────────────────────────────────


def extract_embedded_doc_links(html: str, base_url: str) -> list[str]:
    """
    Find all document download links embedded in an MCMC article page.

    Captures:
      1. Direct <a href> links ending in document extensions (.pdf, .docx, etc.)
         within the main content area.
      2. ASP.NET GetAttachment links (/getattachment/UUID/filename.aspx) which
         redirect to actual files; included regardless of extension.
      3. Direct PDF buttons (a.btn[href*=".pdf"]) anywhere on the page.

    Returns a deduplicated list of absolute document URLs.
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    links: list[str] = []

    # Scope to content area to avoid nav/sidebar noise
    content_area = (
        soup.find("div", class_=re.compile(r"\bcontentZone\b"))
        or soup.find("div", class_=re.compile(r"\barticle-content\b|\bcontent-area\b"))
        or soup
    )

    for a_tag in content_area.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue

        href_lower = href.lower()
        is_doc = any(href_lower.endswith(ext) for ext in _DOC_EXTENSIONS)
        is_attachment = "/getattachment/" in href_lower

        if not (is_doc or is_attachment):
            continue

        abs_url = make_absolute(href, base_url)
        if abs_url not in seen:
            seen.add(abs_url)
            links.append(abs_url)

    # Also capture PDF download buttons outside the main content (e.g. page header)
    for a_tag in soup.find_all("a", class_=re.compile(r"\bbtn\b"), href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith(("javascript:", "#")):
            continue
        if any(href.lower().endswith(ext) for ext in _DOC_EXTENSIONS):
            abs_url = make_absolute(href, base_url)
            if abs_url not in seen:
                seen.add(abs_url)
                links.append(abs_url)

    return links


# ── 6. Acts hub extractor ─────────────────────────────────────────────────────


def extract_acts_hub_items(html: str, source_url: str) -> list[dict]:
    """
    Extract individual Acts from the /en/legal/acts hub page.

    HTML structure (one Act = one <h2> followed by sibling <a> tags):

        <h2>Communications and Multimedia Act 1998 [Act 588]</h2>
        <a href="/en/legal/acts/communications-and-multimedia-act-1998-reprint-200">
            More Details
        </a>
        <a href="/skmmgovmy/media/General/pdf/Act588bi_3.pdf">
            Communications and Multimedia Act 1998 [Act 588]
        </a>

    The sibling anchors are collected until the next <h2> is reached.
    Anchors with a path under /en/legal/ (and not a document extension) are
    treated as the detail page link; anchors ending in a doc extension are
    captured as direct document hrefs.

    Returns list of dicts:
        {
            "title":       str,           # Act name from <h2>
            "detail_href": str,           # /en/legal/acts/SLUG or ""
            "doc_hrefs":   list[str],     # zero or more direct PDF/DOC links
            "source_url":  str,
        }
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")

    # Scope to the main content zone; fall back to whole body
    content = (
        soup.find("div", class_=re.compile(r"\bcontentZone\b"))
        or soup.find("main")
        or soup.body
        or soup
    )

    items: list[dict] = []
    seen_titles: set[str] = set()

    for h2 in content.find_all("h2"):
        title = h2.get_text(strip=True)
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)

        detail_href = ""
        doc_hrefs: list[str] = []
        seen_docs: set[str] = set()

        # Walk forward through siblings until the next <h2>
        sibling = h2.find_next_sibling()
        while sibling is not None:
            if sibling.name == "h2":
                break

            # Collect all anchors within this sibling (handles <p><a>…</a></p>)
            anchors = (
                sibling.find_all("a", href=True)
                if hasattr(sibling, "find_all")
                else []
            )
            # Also handle the sibling itself being an anchor
            if sibling.name == "a" and sibling.get("href"):
                anchors = [sibling] + list(anchors)

            for a in anchors:
                href = a.get("href", "").strip()
                if not href or href.startswith(("javascript:", "#", "mailto:")):
                    continue

                href_lower = href.lower()
                if any(href_lower.endswith(ext) for ext in _DOC_EXTENSIONS):
                    if href not in seen_docs:
                        seen_docs.add(href)
                        doc_hrefs.append(href)
                elif not detail_href and "/en/legal/" in href_lower:
                    detail_href = href

            sibling = sibling.find_next_sibling()

        if detail_href or doc_hrefs:
            items.append(
                {
                    "title": title,
                    "detail_href": detail_href,
                    "doc_hrefs": doc_hrefs,
                    "source_url": source_url,
                }
            )

    log.info(
        {
            "event": "acts_hub_extracted",
            "source_url": source_url,
            "item_count": len(items),
        }
    )
    return items
