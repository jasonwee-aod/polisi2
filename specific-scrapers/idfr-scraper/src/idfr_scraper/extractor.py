"""
IDFR-specific HTML extractors for idfr.gov.my.

The site runs Joomla 4 with the Helix Ultimate template and SP Page Builder.
No sitemaps or RSS feeds are available; all discovery is via HTML parsing.

Four page archetypes are handled:

1. Press Release Listing  (/my/media-1/press)
   Single HTML page with all press releases grouped under year headings.
   Structure:
     div[itemprop="articleBody"]
       <p><strong>2025</strong></p>   ← year header
       <ol>                           ← deeply nested lists
         ... (multiple nesting levels) ...
           <li><a href="...pdf">TITLE</a></li>   ← actual item
       <p><strong>2024</strong></p>
       <ol> ... </ol>
   Date: year only (from preceding year header); stored as "YYYY-01-01".

2. Speeches Listing  (/my/media-1/speeches and /my/media-1/speeches-YYYY)
   Single page per year with speeches in an HTML table.
   Structure:
     div[itemprop="articleBody"]
       <table>
         <tbody>
           <tr>                          ← header row (bgcolor or "No"/"Title" text)
             <td><strong>No</strong></td>
             <td><strong>Title</strong></td>
           </tr>
           <tr>                          ← data row
             <td align="center">1</td>
             <td>
               <p>
                 <a href="...pdf" target="_blank">SPEECH TITLE (DATE?)</a>
                 <img .../>
                 <br/>
                 <strong>EVENT NAME / DATE</strong>
               </p>
             </td>
           </tr>
         </tbody>
       </table>
   Date: extracted from speech title text (parenthetical) or <strong> tag;
         falls back to year from H1 "Speeches in YYYY".

3. Publications Hub  (/my/publications)
   SP Page Builder feature boxes, each linking to a PDF or sub-listing page.
   Structure:
     .sppb-addon-wrapper.addon-root-feature
       .sppb-feature-box-title > a[href]   ← title + link

4. Generic Article Body Listing  (sub-listing pages: /my/publication/newsletters, etc.)
   Joomla article pages with PDF links embedded in div[itemprop="articleBody"].
   Used for newsletters, JDFR journal, and other-publications sub-pages.
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

log = logging.getLogger(__name__)

# Document file extensions to capture.
_DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")

# Malay month names → English for date parsing.
_MALAY_MONTHS: dict[str, str] = {
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

_MALAY_MONTH_RE = re.compile(
    r"\b(" + "|".join(_MALAY_MONTHS) + r")\b",
    re.IGNORECASE,
)

# Match "DD Month YYYY" or "Month DD, YYYY"
_DATE_PATTERN = re.compile(
    r"\b(\d{1,2})\s+"
    r"(January|February|March|April|May|June|July|August"
    r"|September|October|November|December)\s+(20\d{2})\b"
    r"|"
    r"\b(January|February|March|April|May|June|July|August"
    r"|September|October|November|December)\s+(\d{1,2}),?\s+(20\d{2})\b",
    re.IGNORECASE,
)

# Match a bare 4-digit year (2000–2029).
_YEAR_ONLY_RE = re.compile(r"\b(20[0-2]\d)\b")

# Speeches page H1: "Speeches in YYYY"
_SPEECHES_YEAR_H1_RE = re.compile(r"\bin\s+(20\d{2})\b", re.IGNORECASE)

# Header cell values in speech/listing tables that identify header rows.
_TABLE_HEADER_CELLS = frozenset({"no", "title", "tajuk", "no.", "#"})


# ── Date parsing ──────────────────────────────────────────────────────────────


def _translate_malay_months(text: str) -> str:
    """Replace Malay month names in *text* with English equivalents."""
    def _sub(m: re.Match) -> str:
        return _MALAY_MONTHS[m.group(0).lower()]
    return _MALAY_MONTH_RE.sub(_sub, text)


def parse_idfr_date(date_str: str) -> str:
    """
    Parse a date string from IDFR pages into an ISO 8601 date (YYYY-MM-DD).

    Handles:
      - "25 February 2026"      → "2026-02-25"
      - "25 Februari 2026"      → "2026-02-25"  (Malay month name)
      - "February 25, 2026"     → "2026-02-25"
      - "25 Feb 2026"           → "2026-02-25"
      - "(Oct 2, 2025)"         → "2025-10-02"   (parenthetical)
      - "2025"                  → "2025-01-01"   (year only → Jan 1)

    Returns "" on failure.
    """
    if not date_str or not date_str.strip():
        return ""

    raw = date_str.strip().strip("()")
    translated = _translate_malay_months(raw)
    stripped = translated.strip()

    # Year-only check FIRST: must come before generic dateutil because
    # dateutil.parse("2025") returns today's date with year=2025.
    if re.fullmatch(r"20[0-2]\d", stripped):
        return f"{stripped}-01-01"

    # Try full date match
    m = _DATE_PATTERN.search(translated)
    if m:
        if m.group(1):
            # "DD Month YYYY"
            day, month, year = m.group(1), m.group(2), m.group(3)
        else:
            # "Month DD, YYYY"
            month, day, year = m.group(4), m.group(5), m.group(6)
        try:
            dt = dateutil_parser.parse(f"{day} {month} {year}", dayfirst=True)
            return dt.date().isoformat()
        except (ValueError, OverflowError):
            pass

    # Try generic dateutil parsing
    try:
        dt = dateutil_parser.parse(translated, dayfirst=True)
        return dt.date().isoformat()
    except (ValueError, OverflowError):
        pass

    # Year mentioned somewhere in the string but no full date found
    m_year = _YEAR_ONLY_RE.search(translated)
    if m_year and not _DATE_PATTERN.search(translated):
        return f"{m_year.group(1)}-01-01"

    log.warning(
        {"event": "idfr_date_parse_failure", "raw": date_str, "category": "parse"}
    )
    return ""


def extract_year_from_speeches_h1(html: str) -> str:
    """
    Extract the year from the H1 title of a speeches page ("Speeches in YYYY").

    Returns "YYYY" string or "" if not found.
    """
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1", attrs={"itemprop": "headline"})
    if h1:
        m = _SPEECHES_YEAR_H1_RE.search(h1.get_text())
        if m:
            return m.group(1)
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


# ── 1. Press Release Listing extractor ────────────────────────────────────────


def extract_press_listing(html: str, source_url: str) -> list[dict]:
    """
    Extract PDF document entries from the IDFR press release listing page.

    The page organizes press releases under year headings:

        div[itemprop="articleBody"]
          <p><strong>2025</strong></p>
          <ol>
            ... (deeply nested list-style-type:none lists) ...
              <li><a href="/my/images/stories/press/FILENAME.pdf">TITLE</a></li>
          <p><strong>2024</strong></p>
          <ol> ... </ol>

    Year is tracked from preceding <p><strong>YYYY</strong></p> headings.
    Date stored as "YYYY-01-01" (year start proxy since no day/month in source).

    Returns list of dicts:
        {
            "href":       str,   # absolute PDF URL
            "title":      str,   # link text
            "date_text":  str,   # "YYYY-01-01" derived from year heading
            "source_url": str,
        }
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()

    body = soup.find(attrs={"itemprop": "articleBody"})
    if not body:
        log.warning(
            {
                "event": "press_listing_body_not_found",
                "source_url": source_url,
                "category": "parse",
            }
        )
        return items

    current_year = ""

    for element in body.descendants:
        # Year header: <p><strong>2025</strong></p>
        if getattr(element, "name", None) == "p":
            strong = element.find("strong")
            if strong:
                text = strong.get_text(strip=True)
                if _YEAR_ONLY_RE.fullmatch(text):
                    current_year = text
            continue

        # PDF link: <a href="...pdf">
        if getattr(element, "name", None) == "a":
            href = element.get("href", "").strip()
            if not href:
                continue
            lower = href.lower()
            if not any(lower.endswith(ext) for ext in _DOC_EXTENSIONS):
                continue

            abs_href = make_absolute(href, source_url)
            if abs_href in seen:
                continue
            seen.add(abs_href)

            title = element.get_text(strip=True)
            date_text = f"{current_year}-01-01" if current_year else ""

            items.append(
                {
                    "href": abs_href,
                    "title": title,
                    "date_text": date_text,
                    "source_url": source_url,
                }
            )

    log.info(
        {
            "event": "press_listing_extracted",
            "source_url": source_url,
            "item_count": len(items),
        }
    )
    return items


# ── 2. Speeches Listing extractor ─────────────────────────────────────────────


def _is_speech_header_row(cells: list) -> bool:
    """
    Return True if this table row looks like a header row.

    Header rows have <strong> tags or cell text matching known header values.
    """
    if not cells:
        return False
    # First cell: check for "No" or numeric-looking text after stripping
    first_text = cells[0].get_text(strip=True).lower().rstrip(".")
    if first_text in _TABLE_HEADER_CELLS:
        return True
    # Header rows often use <strong> or bgcolor attributes
    first_cell_html = str(cells[0])
    if "<strong>" in first_cell_html and "bgcolor" not in first_cell_html:
        if first_text in _TABLE_HEADER_CELLS:
            return True
    return False


def _extract_speech_date(title: str, strong_texts: list[str], fallback_year: str) -> str:
    """
    Try to extract a date from a speech entry using multiple strategies:

    1. Parenthetical date in title: "Opening Remarks (Oct 2, 2025)"
    2. Date in <strong> text below the link
    3. Year-only fallback from the page H1 "Speeches in YYYY"
    """
    # Strategy 1: parenthetical in title
    paren_m = re.search(r"\(([^)]+)\)", title)
    if paren_m:
        candidate = parse_idfr_date(paren_m.group(1))
        if candidate:
            return candidate

    # Strategy 2: look for date patterns in strong_texts
    for strong_text in strong_texts:
        candidate = parse_idfr_date(strong_text)
        if candidate:
            return candidate

    # Strategy 3: year fallback
    if fallback_year:
        return f"{fallback_year}-01-01"

    return ""


def extract_speeches_listing(html: str, source_url: str) -> list[dict]:
    """
    Extract PDF document entries from the IDFR speeches listing page.

    The page organizes speeches in an HTML table (one table per year section):

        div[itemprop="articleBody"]
          <table border="1" ...>
            <tbody>
              <tr>
                <td bgcolor="..."><strong>No</strong></td>
                <td bgcolor="..."><strong>Title</strong></td>
              </tr>
              <tr>
                <td align="center">1</td>
                <td>
                  <p>
                    <a href="...pdf" target="_blank">SPEECH TITLE (DATE?)</a>
                    <img .../>
                    <br/>
                    <strong>EVENT NAME / DATE</strong>
                  </p>
                </td>
              </tr>
            </tbody>
          </table>

    Date extraction attempts (in order):
      1. Parenthetical date in the link text: "Remarks (Oct 2, 2025)"
      2. Date string in the <strong> tag below the link
      3. Year from H1 title "Speeches in YYYY" → "YYYY-01-01"

    Returns list of dicts:
        {
            "href":       str,   # absolute PDF URL
            "title":      str,   # speech title (link text, cleaned)
            "date_text":  str,   # ISO date string, or ""
            "source_url": str,
        }
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()

    # Get fallback year from H1
    fallback_year = extract_year_from_speeches_h1(html)

    body = soup.find(attrs={"itemprop": "articleBody"})
    if not body:
        log.warning(
            {
                "event": "speeches_listing_body_not_found",
                "source_url": source_url,
                "category": "parse",
            }
        )
        return items

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
            lower_href = href.lower()
            if not any(lower_href.endswith(ext) for ext in _DOC_EXTENSIONS):
                continue

            abs_href = make_absolute(href, source_url)
            if abs_href in seen:
                continue
            seen.add(abs_href)

            # Clean title: get link text, strip trailing whitespace
            title = a_tag.get_text(separator=" ", strip=True)

            # Collect <strong> texts for date extraction.
            # Use separator=" " so <br/> tags inside <strong> produce a space
            # rather than smashing two substrings together (e.g. "2025\n15 Jan"
            # becomes "2025 15 Jan" instead of "202515 Jan").
            strong_texts = [
                s.get_text(separator=" ", strip=True)
                for s in content_cell.find_all("strong")
                if s.get_text(strip=True)
            ]

            date_text = _extract_speech_date(title, strong_texts, fallback_year)

            items.append(
                {
                    "href": abs_href,
                    "title": title,
                    "date_text": date_text,
                    "source_url": source_url,
                }
            )

    log.info(
        {
            "event": "speeches_listing_extracted",
            "source_url": source_url,
            "item_count": len(items),
        }
    )
    return items


# ── 3. Publications Hub extractor ──────────────────────────────────────────────


def extract_publications_hub(html: str, source_url: str) -> list[dict]:
    """
    Extract document links from the IDFR publications hub page (/my/publications).

    The page uses SP Page Builder (sppb) feature boxes:

        .sppb-addon-wrapper.addon-root-feature
          .sppb-feature-box-title > a[href]

    Links are either:
      - Direct PDF files: /my/images/pdf_folder/FILENAME.pdf
      - Sub-listing pages: /my/publication/SECTION_NAME

    Returns list of dicts:
        {
            "href":       str,   # absolute URL (PDF or sub-listing)
            "title":      str,   # publication title
            "is_pdf":     bool,  # True if href is a direct PDF
            "source_url": str,
        }
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()

    # Primary selector: .sppb-feature-box-title a
    for a_tag in soup.select(".sppb-feature-box-title a[href]"):
        href = a_tag.get("href", "").strip()
        if not href or href in ("#", "javascript:void(0)"):
            continue

        abs_href = make_absolute(href, source_url)
        if abs_href in seen:
            continue
        seen.add(abs_href)

        title = a_tag.get_text(strip=True)
        lower = href.lower()
        is_pdf = any(lower.endswith(ext) for ext in _DOC_EXTENSIONS)

        items.append(
            {
                "href": abs_href,
                "title": title,
                "is_pdf": is_pdf,
                "source_url": source_url,
            }
        )

    # Fallback: scan entire article body for missed feature box links
    if not items:
        body = soup.find(attrs={"itemprop": "articleBody"})
        if body:
            for a_tag in body.find_all("a", href=True):
                href = a_tag["href"].strip()
                if not href or href in ("#", "javascript:void(0)"):
                    continue
                abs_href = make_absolute(href, source_url)
                if abs_href in seen:
                    continue
                seen.add(abs_href)
                title = a_tag.get_text(strip=True)
                lower = href.lower()
                is_pdf = any(lower.endswith(ext) for ext in _DOC_EXTENSIONS)
                items.append(
                    {
                        "href": abs_href,
                        "title": title,
                        "is_pdf": is_pdf,
                        "source_url": source_url,
                    }
                )

    log.info(
        {
            "event": "publications_hub_extracted",
            "source_url": source_url,
            "item_count": len(items),
            "pdf_count": sum(1 for i in items if i["is_pdf"]),
            "subpage_count": sum(1 for i in items if not i["is_pdf"]),
        }
    )
    return items


# ── 4. Generic Article Body Listing extractor ──────────────────────────────────


def extract_article_body_listing(html: str, source_url: str) -> list[dict]:
    """
    Extract document links from a generic Joomla article body page.

    Used for newsletter archives, JDFR journal, and other-publications sub-pages.

    Structure:
        div[itemprop="articleBody"]
          <a href="...pdf" target="_blank">DOCUMENT TITLE</a>
          ... (may be in tables, lists, or paragraphs)

    Date extraction:
      - Try to find date in link text
      - Try to find date in surrounding text (sibling <strong> or <td>)
      - Fall back to ""

    Returns list of dicts:
        {
            "href":       str,   # absolute document URL
            "title":      str,   # link text
            "date_text":  str,   # ISO date or ""
            "source_url": str,
        }
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()

    body = soup.find(attrs={"itemprop": "articleBody"})
    search_root = body if body else soup

    for a_tag in search_root.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith(("#", "javascript:")):
            continue

        lower = href.lower()
        if not any(lower.endswith(ext) for ext in _DOC_EXTENSIONS):
            continue

        abs_href = make_absolute(href, source_url)
        if abs_href in seen:
            continue
        seen.add(abs_href)

        title = a_tag.get_text(strip=True)

        # Fallback for image-based links (<a><img/></a>) where link text is empty.
        # Title lives in the grandparent <tr> as "N. Title Text -"; strip the
        # leading number prefix and trailing " -" artefact.
        if not title:
            for ancestor in a_tag.parents:
                if getattr(ancestor, "name", None) == "tr":
                    row_text = ancestor.get_text(separator=" ", strip=True)
                    row_text = re.sub(r"^\d+\.\s*", "", row_text).strip()
                    row_text = re.sub(r"\s*-\s*$", "", row_text).strip()
                    if row_text:
                        title = row_text
                    break

        # Try to find a date in the link text or neighboring sibling text
        date_text = parse_idfr_date(title)
        if not date_text:
            # Check the parent element for date hints
            parent_text = a_tag.parent.get_text(separator=" ", strip=True) if a_tag.parent else ""
            date_text = parse_idfr_date(parent_text)

        items.append(
            {
                "href": abs_href,
                "title": title,
                "date_text": date_text,
                "source_url": source_url,
            }
        )

    log.info(
        {
            "event": "article_body_listing_extracted",
            "source_url": source_url,
            "item_count": len(items),
        }
    )
    return items
