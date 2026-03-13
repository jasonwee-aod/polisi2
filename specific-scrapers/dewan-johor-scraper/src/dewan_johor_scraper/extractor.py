"""
Dewan Negeri Johor-specific HTML/XML extractors.

Six page archetypes are handled:

1. Sitemap XML  (wp-sitemap.xml, wp-sitemap-posts-*.xml)
   WordPress native sitemap index + URL-set sitemaps.
   Returns a list of {url, lastmod} dicts for URL discovery.

2. Divi Theme Listing Page  (/category/pengumuman/, /download-category/*)
   Standard WordPress archive pages rendered with the Divi page builder.
   Items are <article class="et_pb_post ..."> elements.
   Date: <span class="published"> (format: "Jul 27, 2019" or "Nov 11, 2019").
   Pagination: <div class="pagination"> <div class="alignright"> <a href="...">

3. Divi Theme Single Post  (individual article URLs)
   Extracts title and published_at from post metadata.
   Also surfaces any embedded PDF/DOC links.

4. WP Download Manager (wpdmpro) Single Package Page  (/download/{slug}/)
   File download links are <a class="inddl" href="...?wpdmdl=ID&ind=TIMESTAMP">.
   Metadata (date, description) lives in the .w3eden .list-group widget.
   Following the `a.inddl` href with requests (auto-redirect) yields the actual file.

5. Embedded document link extractor  (used for both post and wpdmpro pages)
   Finds direct <a href> links to .pdf, .doc, .docx, .xlsx, .ppt, .pptx files
   plus WP Download Manager `a.inddl` download links.

6. Penyata Rasmi hub page  (/pr/)
   Single-page hub with all verbatim records embedded.  No pagination.
   Structure: h2 (Dewan level) → et_pb_accordion → et_pb_toggle (session) →
              h3 (meeting name) + table (PDF rows).
   Direct PDF links only; no WP Download Manager or iframes.
   Date extracted from document title text (Malay month names).

7. Soalan & Jawapan Lisan hub page  (/sdjl/, /sdjb/)
   Single-page Divi accordion with oral/written-question PDFs.  No top-level h2.
   Structure: et_pb_accordion → et_pb_toggle (session) →
              p>strong (meeting name) + table (1-cell rows: link text = date).
   Date extracted from link text (Malay month names, e.g. "19 Mei 2025").
   Reused for /sdjb/ (Soalan & Jawapan Bertulis) which is structurally identical.

8. Rang Undang-Undang / Enakmen hub page  (/rang-undang-undang-enakmen/)
   Single-page Divi accordion with bills/ordinances.  Has optional h2 Dewan level.
   Structure: h2 (Dewan level, optional) → et_pb_accordion → et_pb_toggle (session) →
              p>strong (meeting name) + 4-column table (Bil | Tarikh | Perkara | Muat Turun).
   Date from Tarikh column; title from Perkara column; link from Muat Turun column.
   Rows without a download link (placeholders) are skipped.
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

log = logging.getLogger(__name__)


# ── Date parsing ──────────────────────────────────────────────────────────────


def parse_divi_date(date_str: str) -> str:
    """
    Parse a Divi theme date string into an ISO 8601 date (YYYY-MM-DD).

    Input examples (English, as rendered by the Divi theme):
        "Jul 27, 2019"      → "2019-07-27"
        "Nov 11, 2019"      → "2019-11-19"
        "November 11, 2019" → "2019-11-11"
        "May 14, 2020"      → "2020-05-14"

    Returns "" on failure.
    """
    if not date_str or not date_str.strip():
        return ""
    try:
        dt = dateutil_parser.parse(date_str.strip(), dayfirst=False)
        return dt.date().isoformat()
    except (ValueError, OverflowError):
        log.warning(
            {"event": "divi_date_parse_failure", "raw": date_str, "category": "parse"}
        )
        return ""


def parse_wp_datetime(dt_str: str) -> str:
    """
    Parse a WordPress ISO 8601 datetime attribute to an ISO 8601 date string.

    Input examples:
        "2019-07-27T10:30:00+08:00"
        "2019-07-27T02:30:00+00:00"
        "2019-07-27"

    Returns "YYYY-MM-DD" on success, "" on failure.
    """
    if not dt_str or not dt_str.strip():
        return ""
    try:
        dt = dateutil_parser.isoparse(dt_str.strip())
        return dt.date().isoformat()
    except (ValueError, OverflowError):
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

    Compatible with WordPress native sitemaps (wp-sitemap.xml) which use
    the same <sitemapindex> / <urlset> structure as Yoast/RankMath sitemaps.

    Returns a list of dicts:
        {
            "url":              str,
            "lastmod":          str,   # ISO date or ""
            "is_sitemap_index": bool,  # True when the entry is itself a child sitemap
        }
    """
    soup = BeautifulSoup(xml, "lxml-xml")

    entries: list[dict] = []

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


# ── 2. Divi Theme Listing Page extractor ──────────────────────────────────────


def extract_divi_listing(html: str, source_url: str) -> list[dict]:
    """
    Extract article links from a Divi theme archive listing page.

    Works for both standard WordPress post archives (/category/pengumuman/)
    and WP Download Manager category archives (/download-category/*/).

    Divi archive HTML structure:
        <article id="post-NNN" class="et_pb_post post NNN type-post ...">
          <h2 class="entry-title">
            <a href="https://...">TITLE</a>
          </h2>
          <p class="post-meta">
            by <span class="author vcard">...</span> |
            <span class="published">Jul 27, 2019</span>
          </p>
        </article>

    Returns list of dicts:
        {
            "title":      str,
            "href":       str,   # absolute or relative URL
            "date_text":  str,   # raw published span text, e.g. "Jul 27, 2019"
            "source_url": str,
        }
    """
    soup = BeautifulSoup(html, "lxml")

    seen_hrefs: set[str] = set()
    items: list[dict] = []

    # Primary selector: <article class="et_pb_post ..."> elements
    articles = soup.find_all("article", class_=re.compile(r"\bet_pb_post\b|\bwpdmpro\b"))

    # Fallback: any <article> element
    if not articles:
        articles = soup.find_all("article")

    for article in articles:
        # Title + link: h2.entry-title > a (Divi) or h1.entry-title > a
        title_tag = article.find(["h2", "h1"], class_=re.compile(r"entry-title"))
        if not title_tag:
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

        # Date: <span class="published"> (Divi uses English month names)
        pub_span = article.find("span", class_=re.compile(r"\bpublished\b"))
        date_text = pub_span.get_text(strip=True) if pub_span else ""

        # Fallback: <time datetime="..."> (some Divi setups)
        if not date_text:
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

    log.info(
        {
            "event": "divi_listing_extracted",
            "source_url": source_url,
            "item_count": len(items),
        }
    )
    return items


def get_next_divi_page_url(html: str) -> Optional[str]:
    """
    Find the "next page" URL in a Divi theme paginated archive.

    Divi uses Bootstrap-influenced pagination:
        <div class="pagination clearfix">
          <div class="alignright">
            <a href="https://.../page/2/">Next »</a>
          </div>
        </div>

    Also handles standard WordPress ?paged=N query parameter links.

    Returns the href string, or None on the last page.
    """
    soup = BeautifulSoup(html, "lxml")

    # ── Divi: div.pagination div.alignright a ─────────────────────────────────
    pagination = soup.find("div", class_=re.compile(r"\bpagination\b"))
    if pagination:
        right_div = pagination.find("div", class_=re.compile(r"\balignright\b"))
        if right_div:
            a = right_div.find("a", href=True)
            if a and a["href"] and a["href"] != "#":
                return a["href"].strip()

    # ── WordPress standard: a.next.page-numbers ───────────────────────────────
    next_link = soup.find("a", class_=re.compile(r"\bnext\b.*page-numbers|page-numbers.*\bnext\b"))
    if next_link and next_link.get("href"):
        return next_link["href"].strip()

    return None


# ── 3. Single Post / Page metadata extractor ──────────────────────────────────


def extract_post_meta(html: str, source_url: str) -> dict:
    """
    Extract metadata from a Divi theme single post or page.

    Extraction order (highest priority first):
      Title:
        1. <h1 class="entry-title">
        2. <meta property="og:title">
        3. <title> tag (stripped of site name)

      Published date:
        1. <meta property="article:published_time">
        2. <time class="entry-date published" datetime="...">
        3. <span class="published"> in post-meta (Divi-specific)
        4. <time class="updated" datetime="...">

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
            raw = og_title["content"].strip()
            # Strip " | Site Name" suffix
            title = raw.split("|")[0].strip() if "|" in raw else raw.split("–")[0].strip()

    if not title:
        title_tag = soup.find("title")
        if title_tag:
            raw = title_tag.get_text(strip=True)
            title = raw.split("|")[0].strip() if "|" in raw else raw.split("–")[0].strip()

    # ── Published date ────────────────────────────────────────────────────────
    published_at = ""

    # 1. <meta property="article:published_time"> (most reliable)
    meta_pub = soup.find("meta", property="article:published_time")
    if meta_pub and meta_pub.get("content"):
        published_at = parse_wp_datetime(meta_pub["content"])

    # 2. <time class="entry-date published" datetime="..."> (standard WP)
    if not published_at:
        time_tag = soup.find(
            "time",
            class_=re.compile(r"entry-date.*published|published.*entry-date"),
        )
        if not time_tag:
            time_tag = soup.find("time", class_=re.compile(r"\bpublished\b"))
        if time_tag and time_tag.get("datetime"):
            published_at = parse_wp_datetime(time_tag["datetime"])

    # 3. <span class="published"> in Divi post-meta (text, not datetime attr)
    if not published_at:
        pub_span = soup.find("span", class_=re.compile(r"\bpublished\b"))
        if pub_span:
            published_at = parse_divi_date(pub_span.get_text(strip=True))

    # 4. <time class="updated"> as last resort
    if not published_at:
        updated_tag = soup.find("time", class_=re.compile(r"\bupdated\b"))
        if updated_tag and updated_tag.get("datetime"):
            published_at = parse_wp_datetime(updated_tag["datetime"])

    return {"title": title, "published_at": published_at}


# ── 4. WP Download Manager (wpdmpro) page extractor ───────────────────────────


def extract_wpdm_page_meta(html: str, source_url: str) -> dict:
    """
    Extract metadata from a WP Download Manager package page (/download/{slug}/).

    The page contains a .w3eden widget with metadata list items and a file
    download table.

    Metadata widget structure (inside .w3eden):
        <ul class="list-group">
          <li class="list-group-item"><span class="badge">31</span> Download</li>
          <li class="list-group-item"><span class="badge">216.93 KB</span> File Size</li>
          <li class="list-group-item"><span class="badge">1</span> File Count</li>
          <li class="list-group-item">
            <span class="badge">November 11, 2019</span> Create Date
          </li>
          <li class="list-group-item">
            <span class="badge">May 14, 2020</span> Last Updated
          </li>
        </ul>

    Returns:
        {
            "title":        str,
            "published_at": str,   # ISO date from "Create Date" or "Last Updated"
            "description":  str,   # package description text
        }
    """
    soup = BeautifulSoup(html, "lxml")

    # ── Title ─────────────────────────────────────────────────────────────────
    title = ""

    h1 = soup.find("h1", class_=re.compile(r"entry-title|post-title"))
    if h1:
        title = h1.get_text(strip=True)

    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            raw = og_title["content"].strip()
            title = raw.split("|")[0].strip() if "|" in raw else raw.split("–")[0].strip()

    # ── Date from WPDM metadata widget ────────────────────────────────────────
    published_at = ""

    w3eden = soup.find("div", class_="w3eden")
    if w3eden:
        list_group = w3eden.find("ul", class_="list-group")
        if list_group:
            for li in list_group.find_all("li", class_="list-group-item"):
                li_text = li.get_text(separator=" ", strip=True)
                badge = li.find("span", class_="badge")
                if not badge:
                    continue
                badge_text = badge.get_text(strip=True)
                # "Create Date" label: use as primary date
                if "Create Date" in li_text or "Tarikh Cipta" in li_text:
                    published_at = parse_divi_date(badge_text)
                    if published_at:
                        break
                # "Last Updated" label: fallback
                if (not published_at and
                        ("Last Updated" in li_text or "Tarikh Kemaskini" in li_text)):
                    published_at = parse_divi_date(badge_text)

    # Fallback: <span class="published"> in Divi post-meta
    if not published_at:
        pub_span = soup.find("span", class_=re.compile(r"\bpublished\b"))
        if pub_span:
            published_at = parse_divi_date(pub_span.get_text(strip=True))

    # ── Description ───────────────────────────────────────────────────────────
    # The first col-md-12 holds the metadata list-group; the second holds the
    # description paragraph. Search all col-md-12 divs for the first non-empty <p>.
    description = ""
    if w3eden:
        for col in w3eden.find_all("div", class_=re.compile(r"\bcol-md-12\b")):
            p = col.find("p")
            if p:
                description = p.get_text(strip=True)
                if description:
                    break

    return {"title": title, "published_at": published_at, "description": description}


def extract_wpdm_file_links(html: str, base_url: str) -> list[str]:
    """
    Extract file download links from a WP Download Manager package page.

    Two link types are present:
      1. Individual file links: <a class="inddl" href="...?wpdmdl=ID&ind=TIMESTAMP">
         These are redirect URLs – following them with requests yields the actual file.
      2. Package download button: <a class="wpdm-download-link" href="#" onclick="...">
         This uses JavaScript; we skip it.

    Returns a deduplicated list of absolute download link URLs (the ?wpdmdl= form,
    which redirect to the actual file when fetched).
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    links: list[str] = []

    # a.inddl links inside the WPDM file list table
    for a in soup.find_all("a", class_=re.compile(r"\binddl\b"), href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:")):
            continue
        if "wpdmdl" not in href:
            continue
        abs_url = make_absolute(href, base_url)
        if abs_url not in seen:
            seen.add(abs_url)
            links.append(abs_url)

    log.info(
        {
            "event": "wpdm_file_links_extracted",
            "source_url": base_url,
            "count": len(links),
        }
    )
    return links


# ── 5. Embedded document link extractor ───────────────────────────────────────


_DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")


def extract_embedded_doc_links(html: str, base_url: str) -> list[str]:
    """
    Find all document download links embedded in a post or page body.

    Two sources:
      1. Direct <a href> links to document files (.pdf, .doc, .docx, etc.)
         found inside the post content area.
      2. WP Download Manager individual file links:
             <a class="inddl" href="...?wpdmdl=ID&ind=TIMESTAMP">
         These redirect to the actual files when fetched.

    Returns a deduplicated list of absolute document URLs.
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    links: list[str] = []

    # ── Direct document links in post content ─────────────────────────────────
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

    # ── WP Download Manager inddl links ───────────────────────────────────────
    for a_tag in soup.find_all("a", class_=re.compile(r"\binddl\b"), href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith(("#", "javascript:")):
            continue
        if "wpdmdl" not in href:
            continue
        abs_url = make_absolute(href, base_url)
        if abs_url not in seen:
            seen.add(abs_url)
            links.append(abs_url)

    return links


# ── 6. Penyata Rasmi hub page (/pr/) extractor ────────────────────────────────

# Malay month name → English, used for date extraction from PR document titles.
_PR_MALAY_MONTHS: dict[str, str] = {
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

_PR_MALAY_MONTH_RE = re.compile(
    r"\b(" + "|".join(_PR_MALAY_MONTHS) + r")\b",
    re.IGNORECASE,
)

# Match: "16 hingga 26 Mei 2025" → captures start day, translated month, year
_PR_DATE_HINGGA = re.compile(
    r"\b(\d{1,2})\s+hingga\s+\d{1,2}\s+"
    r"(January|February|March|April|May|June|July|August"
    r"|September|October|November|December)\s+(20\d{2})\b",
    re.IGNORECASE,
)

# Match: "DD Month YYYY" (first occurrence in string)
_PR_DATE_SIMPLE = re.compile(
    r"\b(\d{1,2})\s+"
    r"(January|February|March|April|May|June|July|August"
    r"|September|October|November|December)\s+(20\d{2})\b",
    re.IGNORECASE,
)


def _translate_pr_malay_months(text: str) -> str:
    """Replace Malay month names in *text* with English equivalents."""
    def _sub(m: re.Match) -> str:
        return _PR_MALAY_MONTHS[m.group(0).lower()]
    return _PR_MALAY_MONTH_RE.sub(_sub, text)


def parse_pr_title_date(title: str) -> str:
    """
    Extract the start date from a Penyata Rasmi document title.

    Handles Malay month names and common date range patterns.

    Input examples:
        "Deraf Verbatim ... 16 hingga 26 Mei 2025"    → "2025-05-16"
        "Deraf Verbatim ... 11 September 2025"         → "2025-09-11"
        "Deraf Verbatim ... 21 April 2022"             → "2022-04-21"
        "Deraf Verbatim ... 21, 24, 25 November 2024"  → "2024-11-25" (nearest to month)

    Returns ISO 8601 "YYYY-MM-DD" or "" on failure.
    """
    if not title or not title.strip():
        return ""

    translated = _translate_pr_malay_months(title)

    # Try "hingga" range pattern first to capture start day
    m = _PR_DATE_HINGGA.search(translated)
    if m:
        day, month, year = m.group(1), m.group(2), m.group(3)
        try:
            dt = dateutil_parser.parse(f"{day} {month} {year}", dayfirst=True)
            return dt.date().isoformat()
        except (ValueError, OverflowError):
            pass

    # Fall back to simple "DD Month YYYY"
    m = _PR_DATE_SIMPLE.search(translated)
    if m:
        day, month, year = m.group(1), m.group(2), m.group(3)
        try:
            dt = dateutil_parser.parse(f"{day} {month} {year}", dayfirst=True)
            return dt.date().isoformat()
        except (ValueError, OverflowError):
            pass

    log.warning(
        {
            "event": "pr_title_date_parse_failure",
            "raw": title,
            "category": "parse",
        }
    )
    return ""


def extract_pr_hub(html: str, source_url: str) -> list[dict]:
    """
    Extract PDF document entries from the /pr/ Penyata Rasmi hub page.

    The page embeds all verbatim records in a single HTML document.

    Structure:
        <h2>Dewan Negeri Johor Ke-15</h2>
        <div class="et_pb_accordion">
          <div class="et_pb_toggle">
            <h5 class="et_pb_toggle_title">Penggal Persidangan Keempat</h5>
            <div class="et_pb_toggle_content clearfix">
              <h3><strong>Mesyuarat Pertama</strong></h3>
              <table>
                <tr><td>Tajuk</td><td>Muat Turun</td></tr>   ← header row (skip)
                <tr>
                  <td>Deraf Verbatim ... 16 hingga 26 Mei 2025</td>
                  <td><a href="...pdf"><strong>Download</strong></a></td>
                </tr>
              </table>
            </div>
          </div>
        </div>

    Rows without an <a href> are placeholder entries (not yet uploaded) and are
    skipped. Only rows with direct .pdf links are returned.

    Returns list of dicts:
        {
            "href":        str,   # absolute PDF URL
            "title":       str,   # document title from first table cell
            "date_text":   str,   # ISO date extracted from title, or ""
            "dewan_level": str,   # e.g. "Dewan Negeri Johor Ke-15"
            "session":     str,   # e.g. "Penggal Persidangan Keempat"
            "meeting":     str,   # e.g. "Mesyuarat Pertama"
            "source_url":  str,
        }
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()

    # Walk elements in document order to track the current h2 (Dewan level).
    # Each h2 is followed by one et_pb_accordion div.
    current_dewan = ""

    # Find all h2 tags and et_pb_accordion divs in document order
    relevant = soup.find_all(
        lambda tag: (
            tag.name == "h2"
            or (
                tag.name == "div"
                and "et_pb_accordion" in tag.get("class", [])
                and "et_pb_module" in tag.get("class", [])
            )
        )
    )

    for el in relevant:
        if el.name == "h2":
            current_dewan = el.get_text(strip=True)

        elif el.name == "div":
            # Iterate every et_pb_toggle inside this accordion
            for toggle in el.find_all("div", class_=re.compile(r"\bet_pb_toggle\b")):
                h5 = toggle.find("h5", class_=re.compile(r"\bet_pb_toggle_title\b"))
                session = h5.get_text(strip=True) if h5 else ""

                content = toggle.find(
                    "div", class_=re.compile(r"\bet_pb_toggle_content\b")
                )
                if not content:
                    continue

                # Walk direct children: h3 = meeting name, table = document rows
                current_meeting = ""
                for child in content.children:
                    if not hasattr(child, "name") or child.name is None:
                        continue

                    if child.name == "h3":
                        text = child.get_text(strip=True)
                        if text:
                            current_meeting = text

                    elif child.name == "table":
                        rows = child.find_all("tr")
                        for row in rows[1:]:  # skip header row
                            cells = row.find_all("td")
                            if len(cells) < 2:
                                continue

                            doc_title = cells[0].get_text(strip=True)
                            # Skip header rows that slipped through
                            if doc_title.lower() in ("tajuk", "title", ""):
                                continue

                            a = cells[-1].find("a", href=True)
                            if not a:
                                continue  # placeholder – not yet published

                            href = a["href"].strip()
                            if not href.lower().endswith(".pdf"):
                                continue

                            abs_href = make_absolute(href, source_url)
                            if abs_href in seen:
                                continue
                            seen.add(abs_href)

                            items.append(
                                {
                                    "href": abs_href,
                                    "title": doc_title,
                                    "date_text": parse_pr_title_date(doc_title),
                                    "dewan_level": current_dewan,
                                    "session": session,
                                    "meeting": current_meeting,
                                    "source_url": source_url,
                                }
                            )

    log.info(
        {
            "event": "pr_hub_extracted",
            "source_url": source_url,
            "item_count": len(items),
        }
    )
    return items


# ── 7. Soalan & Jawapan Lisan hub page (/sdjl/) extractor ─────────────────────


def extract_sdjl_hub(html: str, source_url: str) -> list[dict]:
    """
    Extract PDF entries from the Soalan & Jawapan Lisan hub page (/sdjl/).

    Single-page Divi accordion.  No top-level Dewan h2 (all Ke-15).

    Structure:
        <div class="et_pb_accordion et_pb_module">
          <div class="et_pb_toggle">
            <h5 class="et_pb_toggle_title">Penggal Persidangan Keempat</h5>
            <div class="et_pb_toggle_content clearfix">
              <p><strong>Mesyuarat Pertama</strong></p>
              <table>
                <tr><td><a href="...pdf">DD Bulan YYYY</a></td></tr>
                ...
              </table>
              <p><strong>Mesyuarat Kedua</strong></p>
              <table>
                ...
              </table>
            </div>
          </div>
        </div>

    The link text is the document date (Malay month names, e.g. "19 Mei 2025").
    There is no separate title column — the date IS the document label.

    Returns list of dicts:
        {
            "href":       str,   # absolute PDF URL
            "title":      str,   # link text (e.g. "19 Mei 2025")
            "date_text":  str,   # ISO date parsed from title, or ""
            "session":    str,   # e.g. "Penggal Persidangan Keempat"
            "meeting":    str,   # e.g. "Mesyuarat Pertama"
            "source_url": str,
        }
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()

    for accordion in soup.find_all(
        "div",
        class_=lambda c: c and "et_pb_accordion" in c and "et_pb_module" in c,
    ):
        for toggle in accordion.find_all(
            "div", class_=re.compile(r"\bet_pb_toggle\b")
        ):
            h5 = toggle.find("h5", class_=re.compile(r"\bet_pb_toggle_title\b"))
            session = h5.get_text(strip=True) if h5 else ""

            content = toggle.find(
                "div", class_=re.compile(r"\bet_pb_toggle_content\b")
            )
            if not content:
                continue

            # Walk direct children: p>strong = meeting header, table = doc rows
            current_meeting = ""
            for child in content.children:
                if not hasattr(child, "name") or child.name is None:
                    continue

                if child.name == "p":
                    strong = child.find("strong")
                    if strong:
                        text = strong.get_text(strip=True)
                        if text:
                            current_meeting = text

                elif child.name == "table":
                    for row in child.find_all("tr"):
                        cells = row.find_all("td")
                        if not cells:
                            continue
                        a = cells[0].find("a", href=True)
                        if not a:
                            continue
                        href = a["href"].strip()
                        if not href.lower().endswith(".pdf"):
                            continue
                        abs_href = make_absolute(href, source_url)
                        if abs_href in seen:
                            continue
                        seen.add(abs_href)
                        link_text = a.get_text(strip=True)
                        items.append(
                            {
                                "href": abs_href,
                                "title": link_text,
                                "date_text": parse_pr_title_date(link_text),
                                "session": session,
                                "meeting": current_meeting,
                                "source_url": source_url,
                            }
                        )

    log.info(
        {
            "event": "sdjl_hub_extracted",
            "source_url": source_url,
            "item_count": len(items),
        }
    )
    return items


# ── 8. Rang Undang-Undang / Enakmen hub page extractor ────────────────────────

# Header cell values that identify the table header row (skip these rows).
_RUU_HEADER_CELLS = frozenset({"bil", "no", "tarikh", "date", "perkara", "subject"})


def extract_ruu_hub(html: str, source_url: str) -> list[dict]:
    """
    Extract PDF entries from the Rang Undang-Undang / Enakmen hub page.

    The page uses a 4-column table layout inside a Divi accordion:

        <h2>Dewan Negeri Johor Ke-14</h2>          ← optional Dewan level
        <div class="et_pb_accordion et_pb_module">
          <div class="et_pb_toggle">
            <h5 class="et_pb_toggle_title">Penggal Persidangan N</h5>
            <div class="et_pb_toggle_content clearfix">
              <p><strong>Mesyuarat N</strong></p>
              <table>
                <tr><td>Bil</td><td>Tarikh</td><td>Perkara</td><td>Muat Turun</td></tr>
                <tr>
                  <td>1.</td>
                  <td>DD Bulan YYYY</td>
                  <td>Tajuk Rang Undang-Undang</td>
                  <td><a href="...pdf">Muat Turun</a></td>
                </tr>
              </table>
            </div>
          </div>
        </div>

    Rows without a link in the last column (placeholder rows) are skipped.
    Header rows where the first cell text matches known header values are also skipped.

    Returns list of dicts:
        {
            "href":        str,   # absolute PDF URL
            "title":       str,   # from Perkara column (cells[2])
            "date_text":   str,   # ISO date parsed from Tarikh column (cells[1])
            "dewan_level": str,   # e.g. "Dewan Negeri Johor Ke-14" (or "")
            "session":     str,   # e.g. "Penggal Persidangan Pertama"
            "meeting":     str,   # e.g. "Mesyuarat Pertama"
            "source_url":  str,
        }
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()
    current_dewan = ""

    # Walk h2 elements and et_pb_accordion divs in document order
    relevant = soup.find_all(
        lambda tag: (
            tag.name == "h2"
            or (
                tag.name == "div"
                and "et_pb_accordion" in tag.get("class", [])
                and "et_pb_module" in tag.get("class", [])
            )
        )
    )

    for el in relevant:
        if el.name == "h2":
            current_dewan = el.get_text(strip=True)

        elif el.name == "div":
            for toggle in el.find_all("div", class_=re.compile(r"\bet_pb_toggle\b")):
                h5 = toggle.find("h5", class_=re.compile(r"\bet_pb_toggle_title\b"))
                session = h5.get_text(strip=True) if h5 else ""

                content = toggle.find(
                    "div", class_=re.compile(r"\bet_pb_toggle_content\b")
                )
                if not content:
                    continue

                current_meeting = ""
                for child in content.children:
                    if not hasattr(child, "name") or child.name is None:
                        continue

                    if child.name == "p":
                        strong = child.find("strong")
                        if strong:
                            text = strong.get_text(strip=True)
                            if text:
                                current_meeting = text

                    elif child.name == "table":
                        for row in child.find_all("tr"):
                            cells = row.find_all("td")
                            if len(cells) < 4:
                                continue

                            # Skip header rows
                            first = cells[0].get_text(strip=True).lower().rstrip(".")
                            if first in _RUU_HEADER_CELLS:
                                continue

                            date_raw = cells[1].get_text(strip=True)
                            title = cells[2].get_text(strip=True)

                            # Last column holds the download link
                            a = cells[-1].find("a", href=True)
                            if not a:
                                continue  # placeholder – not yet published

                            href = a["href"].strip()
                            if not href.lower().endswith(".pdf"):
                                continue

                            abs_href = make_absolute(href, source_url)
                            if abs_href in seen:
                                continue
                            seen.add(abs_href)

                            items.append(
                                {
                                    "href": abs_href,
                                    "title": title,
                                    "date_text": parse_pr_title_date(date_raw),
                                    "dewan_level": current_dewan,
                                    "session": session,
                                    "meeting": current_meeting,
                                    "source_url": source_url,
                                }
                            )

    log.info(
        {
            "event": "ruu_hub_extracted",
            "source_url": source_url,
            "item_count": len(items),
        }
    )
    return items
