"""
Dewan Selangor-specific HTML/XML extractors.

Five page archetypes are handled:

1. Sitemap XML  (sitemap_index.xml, *-sitemap.xml)
   Returns a list of {url, lastmod} dicts for URL discovery.

2. WordPress Listing Page  (/berita-dewan/, /kenyataan-media/, etc.)
   Standard WordPress archive pages with <article> elements.
   Pagination: /page/N/ href in <a class="next page-numbers">.

3. WordPress Single Post  (individual article URLs)
   Extracts title, published_at from post metadata.
   Also surfaces any embedded PDF/DOC links.

4. pdfjs-viewer Embed
   Decodes PDF URLs from pdfjs-viewer-shortcode <iframe> embeds:
       /wp-content/plugins/pdfjs-viewer-shortcode/pdfjs/web/viewer.php?file=<encoded_url>

5. Penyata Rasmi (Hansard) Hub  (/penyata-rasmi/)
   3-level structure: hub index page → session pages → direct PDF files.
   Hub: .hansard-items divs with year groups and session links.
   Session: <p class="mb-2"> elements with dated PDF hrefs.

6. e-QUANS (Question archive)  (/question/, /question/page/N/)
   Bootstrap-paginated listing of oral and written assembly questions.
   Listing: div.card.question cards; pagination via li.page-item.next a.page-link.
   Single question page: title from og:title; date from .sidang-details p.lead small
   ("DD Month – DD Month YYYY"); attachments from .list-of-attachments.
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

log = logging.getLogger(__name__)

# ── Malay month translation ────────────────────────────────────────────────────

MALAY_MONTHS: dict[str, str] = {
    "januari": "January",
    "februari": "February",
    "mac": "March",
    "april": "April",
    "mei": "May",
    "jun": "June",
    "julai": "July",
    "ogos": "August",
    "september": "September",
    "oktober": "October",
    "november": "November",
    "disember": "December",
}

_MONTH_RE = re.compile(
    r"\b(" + "|".join(MALAY_MONTHS) + r")\b",
    re.IGNORECASE,
)


def translate_malay_date(text: str) -> str:
    """Replace Malay month names in *text* with English equivalents."""

    def _sub(m: re.Match) -> str:
        return MALAY_MONTHS[m.group(0).lower()]

    return _MONTH_RE.sub(_sub, text)


def parse_malay_date(date_str: str) -> str:
    """
    Parse a Malay date string into an ISO 8601 date (YYYY-MM-DD).
    Returns an empty string on failure.

    Examples:
        "4 Disember 2025"  → "2025-12-04"
        "1 Mac 2023"       → "2023-03-01"
    """
    if not date_str or not date_str.strip():
        return ""
    translated = translate_malay_date(date_str.strip())
    try:
        dt = dateutil_parser.parse(translated, dayfirst=True)
        return dt.date().isoformat()
    except (ValueError, OverflowError):
        log.warning(
            {"event": "date_parse_failure", "raw": date_str, "category": "parse"}
        )
        return ""


def parse_wp_datetime(dt_str: str) -> str:
    """
    Parse a WordPress ISO 8601 datetime attribute to an ISO 8601 date string.

    Input examples:
        "2025-01-15T10:30:00+08:00"
        "2025-01-15T02:30:00+00:00"
        "2025-01-15"

    Returns "YYYY-MM-DD" on success, "" on failure.
    """
    if not dt_str or not dt_str.strip():
        return ""
    try:
        dt = dateutil_parser.isoparse(dt_str.strip())
        return dt.date().isoformat()
    except (ValueError, OverflowError):
        # Fall back to dateutil generic parser
        try:
            dt = dateutil_parser.parse(dt_str.strip())
            return dt.date().isoformat()
        except (ValueError, OverflowError):
            log.warning(
                {
                    "event": "wp_date_parse_failure",
                    "raw": dt_str,
                    "category": "parse",
                }
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
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
    }
    for ext, mime in ext_map.items():
        if path.endswith(ext):
            return mime
    return "text/html"


# ── 1. Sitemap XML parser ──────────────────────────────────────────────────────


def parse_sitemap_xml(xml: str, source_url: str) -> list[dict]:
    """
    Parse a standard XML sitemap and return URL entries.

    Handles both sitemap index files (lists child sitemaps) and regular
    URL-set sitemaps (lists <url> entries).

    Returns a list of dicts:
        {
            "url":     str,      # <loc> value
            "lastmod": str,      # ISO date or "", from <lastmod>
            "is_sitemap_index": bool,  # True when the child is itself a sitemap
        }
    """
    # BeautifulSoup with lxml-xml parser strips namespaces cleanly.
    soup = BeautifulSoup(xml, "lxml-xml")

    entries: list[dict] = []

    # Sitemap index: <sitemapindex> → child <sitemap> elements
    sitemap_index = soup.find("sitemapindex")
    if sitemap_index:
        for sm in sitemap_index.find_all("sitemap"):
            loc = sm.find("loc")
            lastmod = sm.find("lastmod")
            if not loc:
                continue
            entries.append(
                {
                    "url": loc.get_text(strip=True),
                    "lastmod": lastmod.get_text(strip=True) if lastmod else "",
                    "is_sitemap_index": True,
                }
            )
        log.info(
            {
                "event": "sitemap_index_parsed",
                "source_url": source_url,
                "count": len(entries),
            }
        )
        return entries

    # Regular URL-set sitemap: <urlset> → <url> elements
    urlset = soup.find("urlset")
    if urlset:
        for url_tag in urlset.find_all("url"):
            loc = url_tag.find("loc")
            lastmod = url_tag.find("lastmod")
            if not loc:
                continue
            entries.append(
                {
                    "url": loc.get_text(strip=True),
                    "lastmod": lastmod.get_text(strip=True) if lastmod else "",
                    "is_sitemap_index": False,
                }
            )
        log.info(
            {
                "event": "sitemap_parsed",
                "source_url": source_url,
                "count": len(entries),
            }
        )
        return entries

    log.warning(
        {
            "event": "sitemap_parse_empty",
            "source_url": source_url,
            "category": "parse",
        }
    )
    return entries


# ── 2. WordPress Listing Page extractor ───────────────────────────────────────


def extract_wp_listing(html: str, source_url: str) -> list[dict]:
    """
    Extract article links from a WordPress archive listing page.

    WordPress archive HTML structure:
        <article id="post-NNN" class="post NNN post type-post status-publish ...">
          <header class="entry-header">
            <h2 class="entry-title">
              <a href="https://..." rel="bookmark">TITLE</a>
            </h2>
          </header>
          <footer class="entry-meta">
            <time class="entry-date published" datetime="2025-01-15T10:30:00+08:00">
              15 Januari 2025
            </time>
          </footer>
        </article>

    Returns list of dicts:
        {
            "title":      str,
            "href":       str,   # absolute or relative URL
            "date_text":  str,   # raw datetime attribute, e.g. "2025-01-15T10:30:00+08:00"
            "source_url": str,
        }
    """
    soup = BeautifulSoup(html, "lxml")

    seen_hrefs: set[str] = set()
    items: list[dict] = []

    # Find all <article> elements (standard WordPress archive markup)
    articles = soup.find_all("article")

    # Fallback: some themes use <div class="...post..."> instead
    if not articles:
        articles = soup.find_all(
            "div",
            class_=re.compile(r"\bpost\b|\btype-post\b"),
        )

    for article in articles:
        # Title + link
        title_tag = article.find(["h2", "h3"], class_=re.compile(r"entry-title"))
        if not title_tag:
            # Broader fallback: any heading with an anchor
            title_tag = article.find(["h2", "h3"])

        if not title_tag:
            continue

        a_tag = title_tag.find("a", href=True)
        if not a_tag:
            continue

        href = a_tag["href"].strip()
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        title = a_tag.get_text(strip=True)

        # Date: <time datetime="..."> inside the article
        time_tag = article.find("time", {"datetime": True})
        date_text = time_tag["datetime"].strip() if time_tag else ""

        items.append(
            {
                "title": title,
                "href": href,
                "date_text": date_text,
                "source_url": source_url,
            }
        )

    # If no articles found but there are direct anchor links for post content,
    # do a broader fallback scan for .entry-title links.
    if not items:
        for a_tag in soup.find_all("a", class_=re.compile(r"entry-title|post-title"), href=True):
            href = a_tag["href"].strip()
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            items.append(
                {
                    "title": a_tag.get_text(strip=True),
                    "href": href,
                    "date_text": "",
                    "source_url": source_url,
                }
            )

    log.info(
        {
            "event": "wp_listing_extracted",
            "source_url": source_url,
            "item_count": len(items),
        }
    )
    return items


def get_next_listing_page_url(html: str) -> Optional[str]:
    """
    Find the "next page" URL in a WordPress paginated archive.

    WordPress standard pagination:
        <a class="next page-numbers" href="https://.../page/2/">›</a>

    Returns the href string, or None if we're on the last page.
    """
    soup = BeautifulSoup(html, "lxml")
    next_link = soup.find("a", class_=re.compile(r"\bnext\b.*page-numbers|page-numbers.*\bnext\b"))
    if next_link and next_link.get("href"):
        return next_link["href"].strip()
    return None


# ── 3. WordPress Single Post extractor ────────────────────────────────────────


def extract_wp_post_meta(html: str, source_url: str) -> dict:
    """
    Extract metadata from a WordPress single post/page.

    Extraction order (highest priority first):
      Title:
        1. <h1 class="entry-title">
        2. <meta property="og:title">
        3. <title> tag (stripped of site name)

      Published date:
        1. <time class="entry-date published" datetime="...">
        2. <meta property="article:published_time">
        3. <time class="updated" datetime="...">

    Returns:
        {
            "title":        str,
            "published_at": str,   # ISO date "YYYY-MM-DD" or ""
        }
    """
    soup = BeautifulSoup(html, "lxml")

    # ── Title ─────────────────────────────────────────────────────────────────
    title = ""

    h1 = soup.find("h1", class_=re.compile(r"entry-title|post-title|page-title"))
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
            # Strip common " | Site Name" suffix
            title = raw.split("|")[0].strip() if "|" in raw else raw.split("–")[0].strip()

    # ── Published date ────────────────────────────────────────────────────────
    published_at = ""

    # 1. <time class="entry-date published" datetime="...">
    time_tag = soup.find(
        "time",
        class_=re.compile(r"entry-date.*published|published.*entry-date"),
    )
    if not time_tag:
        # Accept any <time class="published">
        time_tag = soup.find("time", class_=re.compile(r"\bpublished\b"))
    if time_tag and time_tag.get("datetime"):
        published_at = parse_wp_datetime(time_tag["datetime"])

    # 2. <meta property="article:published_time">
    if not published_at:
        meta_pub = soup.find("meta", property="article:published_time")
        if meta_pub and meta_pub.get("content"):
            published_at = parse_wp_datetime(meta_pub["content"])

    # 3. <time class="updated"> as a last resort
    if not published_at:
        updated_tag = soup.find("time", class_=re.compile(r"\bupdated\b"))
        if updated_tag and updated_tag.get("datetime"):
            published_at = parse_wp_datetime(updated_tag["datetime"])

    # 4. e-QUANS: .sidang-details p.lead small → "17 Ogos - 20 Ogos 2015"
    if not published_at:
        sidang = soup.find("div", class_="sidang-details")
        if sidang:
            lead = sidang.find("p", class_="lead")
            if lead:
                small = lead.find("small")
                if small:
                    published_at = _parse_equans_date_range(small.get_text(strip=True))

    return {"title": title, "published_at": published_at}


def _parse_equans_date_range(text: str) -> str:
    """
    Parse an e-QUANS sitting date range into the start date (ISO 8601).

    Input examples:
        "17 Ogos - 20 Ogos 2015"   → "2015-08-17"
        "3 Mac - 5 Mac 2023"        → "2023-03-03"
        "21 Oktober 2019"           → "2019-10-21"  (single date, no range)

    The year only appears in the end portion of the range, so we borrow it
    for the start date when parsing.
    """
    if not text:
        return ""
    parts = text.split(" - ")
    start_raw = parts[0].strip()
    if len(parts) >= 2:
        end_raw = parts[-1].strip()
        year_m = re.search(r"\b(20\d{2}|19\d{2})\b", end_raw)
        if year_m:
            start_raw = f"{start_raw} {year_m.group(0)}"
    return parse_malay_date(start_raw)


# ── 4. pdfjs-viewer and embedded document link extractor ──────────────────────


_PDFJS_VIEWER_RE = re.compile(
    r"pdfjs(?:-viewer-shortcode)?/pdfjs/web/viewer\.php",
    re.IGNORECASE,
)

_DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")


def extract_embedded_doc_links(html: str, base_url: str) -> list[str]:
    """
    Find all document download links embedded in a WordPress post body.

    Two sources:
      1. pdfjs-viewer <iframe>:
             <iframe src="...viewer.php?file=<URL-encoded-PDF-url>...">
         The PDF URL is extracted from the `file` query parameter.

      2. Direct <a href> links to document files (.pdf, .doc, .docx, etc.)
         found inside the post content area.

    Returns a deduplicated list of absolute document URLs.
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    links: list[str] = []

    # ── pdfjs-viewer iframes ───────────────────────────────────────────────────
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"].strip()
        if not _PDFJS_VIEWER_RE.search(src):
            continue
        # Extract the `file` query parameter
        qs = parse_qs(urlparse(src).query)
        file_vals = qs.get("file", [])
        if not file_vals:
            continue
        pdf_url = unquote(file_vals[0])
        abs_url = make_absolute(pdf_url, base_url)
        if abs_url not in seen:
            seen.add(abs_url)
            links.append(abs_url)

    # ── Direct document links in post content ─────────────────────────────────
    # Scope to the content area if possible to avoid nav/sidebar noise.
    content_area = (
        soup.find("div", class_=re.compile(r"entry-content|post-content|article-body"))
        or soup
    )

    for a_tag in content_area.find_all("a", href=True):
        href = a_tag["href"].strip()
        lower = href.lower()
        if not any(lower.endswith(ext) for ext in _DOC_EXTENSIONS):
            continue
        abs_url = make_absolute(href, base_url)
        if abs_url not in seen:
            seen.add(abs_url)
            links.append(abs_url)

    # ── e-QUANS: .list-of-attachments ─────────────────────────────────────────
    # Grab ALL hrefs from this section regardless of extension: attachments
    # include images (JPG) as well as documents. The section is explicitly
    # labelled so every link here is an intentional official attachment.
    attachments_area = soup.find("div", class_="list-of-attachments")
    if attachments_area:
        for a_tag in attachments_area.find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href or href.startswith(("javascript:", "#", "mailto:")):
                continue
            abs_url = make_absolute(href, base_url)
            if abs_url not in seen:
                seen.add(abs_url)
                links.append(abs_url)

    return links


# ── 5. Penyata Rasmi (Hansard) hub extractors ─────────────────────────────────

# Strips parenthesised day name suffix, e.g. "(SELASA)" or "(ISNIN)"
_DAY_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")


def parse_hansard_date(date_str: str) -> str:
    """
    Parse a hansard sitting date label into ISO 8601 (YYYY-MM-DD).

    Input examples:
        "18 FEB 2025 (SELASA)"    → "2025-02-18"
        "3 MAC 2025 (ISNIN)"      → "2025-03-03"
        "1 DISEMBER 2025 (SELASA)"→ "2025-12-01"

    Returns "" on failure.
    """
    if not date_str or not date_str.strip():
        return ""
    # Remove parenthesised day name suffix
    cleaned = _DAY_PAREN_RE.sub("", date_str.strip())
    # Translate Malay month abbreviations/names to English
    translated = translate_malay_date(cleaned)
    try:
        dt = dateutil_parser.parse(translated, dayfirst=True)
        return dt.date().isoformat()
    except (ValueError, OverflowError):
        log.warning(
            {
                "event": "hansard_date_parse_failure",
                "raw": date_str,
                "category": "parse",
            }
        )
        return ""


def extract_hansard_index(html: str, source_url: str) -> list[dict]:
    """
    Extract session page links from the /penyata-rasmi/ hub page.

    HTML structure:
        <div class="hansard-items">
          <div class="hansard-item">
            <div class="col-sm-2"><h4>2025</h4></div>
            <div class="col-sm-10">
              <ul class="list-unstyled list-inline list-attachment">
                <li><a href="https://dewan.selangor.gov.my/hansard/sesi-1-6/">Sesi 1</a></li>
              </ul>
            </div>
          </div>
        </div>

    Returns list of dicts:
        {"href": str, "title": str, "year": str, "source_url": str}
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()

    for item_div in soup.find_all("div", class_="hansard-item"):
        # Year label from .col-sm-2 > h4
        year_col = item_div.find("div", class_=re.compile(r"\bcol-sm-2\b"))
        year = ""
        if year_col:
            h4 = year_col.find("h4")
            if h4:
                year = h4.get_text(strip=True)

        # Session links in .col-sm-10 .list-attachment li a
        link_col = item_div.find("div", class_=re.compile(r"\bcol-sm-10\b"))
        if not link_col:
            continue

        for a in link_col.find_all("a", href=True):
            href = a["href"].strip()
            if href in seen:
                continue
            seen.add(href)
            items.append(
                {
                    "href": href,
                    "title": a.get_text(strip=True),
                    "year": year,
                    "source_url": source_url,
                }
            )

    log.info(
        {
            "event": "hansard_index_extracted",
            "source_url": source_url,
            "count": len(items),
        }
    )
    return items


def extract_hansard_session_pdfs(html: str, source_url: str, base_url: str) -> list[dict]:
    """
    Extract PDF links from a hansard session page (/hansard/sesi-N-N/).

    HTML structure:
        <p class="mb-2">
          <a href="https://.../18-FEB-2025-SELASA.pdf"
             class="float-sm-left col-sm-10 col-md-9 px-0">
            18 FEB 2025 (SELASA)
          </a>
          <span class="pull-right">261 KB</span>
        </p>

    Returns list of dicts:
        {"href": str, "title": str, "date_text": str, "source_url": str}
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()

    for p in soup.find_all("p", class_="mb-2"):
        a = p.find("a", href=True)
        if not a:
            continue
        href = a["href"].strip()
        if not href.lower().endswith(".pdf"):
            continue
        abs_href = make_absolute(href, base_url)
        if abs_href in seen:
            continue
        seen.add(abs_href)

        label = a.get_text(strip=True)
        items.append(
            {
                "href": abs_href,
                "title": label,
                "date_text": label,  # e.g. "18 FEB 2025 (SELASA)"
                "source_url": source_url,
            }
        )

    log.info(
        {
            "event": "hansard_session_pdfs_extracted",
            "source_url": source_url,
            "count": len(items),
        }
    )
    return items


# ── 6. e-QUANS (Question archive) extractors ──────────────────────────────────


def extract_equans_listing(html: str, source_url: str) -> list[dict]:
    """
    Extract question links from /question/ or /question/page/N/ listing pages.

    HTML structure:
        <div class="card mb-3 question">
          <h3 class="card-header mt-0 text-uppercase">
            <a href="https://dewan.selangor.gov.my/question/SLUG/">TITLE</a>
          </h3>
          <div class="card-body">
            <p>Tahun: 2025</p>
            <p>Sesi: 1</p>
            <p>Isu: Pendidikan</p>
            <p>Adun: Y.B. …</p>
            <p>Kategori: Mulut</p>
          </div>
        </div>

    date_text is empty; the sitting date is only on the individual question page.

    Returns list of dicts:
        {"title": str, "href": str, "date_text": str, "source_url": str}
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()

    for card in soup.find_all("div", class_="question"):
        header = card.find(["h2", "h3"], class_=re.compile(r"card-header"))
        if not header:
            continue
        a = header.find("a", href=True)
        if not a:
            continue
        href = a["href"].strip()
        if href in seen:
            continue
        seen.add(href)
        items.append(
            {
                "title": a.get_text(strip=True),
                "href": href,
                "date_text": "",
                "source_url": source_url,
            }
        )

    log.info(
        {
            "event": "equans_listing_extracted",
            "source_url": source_url,
            "item_count": len(items),
        }
    )
    return items


def get_next_equans_page_url(html: str) -> Optional[str]:
    """
    Find the "next page" URL in the Bootstrap pagination used by /question/.

    Bootstrap markup:
        <li class="page-item next">
          <a aria-label="Next" class="page-link"
             href="https://dewan.selangor.gov.my/question/page/3/">»</a>
        </li>

    Returns the href string, or None on the last page.
    """
    soup = BeautifulSoup(html, "lxml")
    for li in soup.find_all("li", class_="page-item"):
        if "next" in li.get("class", []):
            a = li.find("a", class_="page-link", href=True)
            if a and a["href"] != "#":
                return a["href"].strip()
    return None
