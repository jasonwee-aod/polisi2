"""
KPKT-specific HTML extractors.

Three page archetypes are handled:

1. Siaran Media accordion (press releases)
   Pattern A: <p><strong>DATE</strong><br/><a href>TITLE</a></p>
   Pattern B: <a href>DATE\\nTITLE</a>

2. Downloads Hub  (/index.php/pages/view/1026)
   Accordion where each panel links to a sub-page, not a document.
   `extract_downloads_hub` returns the sub-page URLs to follow.

3. Container Attachments  (.container_attachments table)
   Used by legislation, forms, and quality-management pages.
   Both direct links (/kpkt/resources/...) and obfuscated
   /index.php/dl/<HEX> links are resolved.

   /index.php/dl/ URL scheme:
       hex_string  →  hex-decode  →  base64 string
       base64 string  →  base64-decode  →  file path suffix
       full URL = https://www.kpkt.gov.my/kpkt/resources/<suffix>
"""
from __future__ import annotations

import base64
import binascii
import logging
import re
from typing import Optional
from urllib.parse import urlparse

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

_YEAR_RE = re.compile(r"\b20\d{2}\b")


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
        log.warning({"event": "date_parse_failure", "raw": date_str, "category": "parse"})
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
    }
    for ext, mime in ext_map.items():
        if path.endswith(ext):
            return mime
    return "text/html"


# ── Date extraction from title text ──────────────────────────────────────────
#
# Statistics and periodic report pages encode the covered period inside the
# document title rather than as a standalone date field.  Examples:
#
#   "Statistik Terpilih KPKT Sehingga 31 Mac 2022"   → 2022-03-31
#   "Pencapaian Piagam Pelanggan bagi Bulan Januari 2026"  → 2026-01-01
#   "Bilangan transaksi online bagi Oktober 2021"     → 2021-10-01
#   "Statistik KPKT 2024 (Tahunan)"                  → 2024-01-01  (year only)


_SEHINGGA_RE = re.compile(
    r"sehingga\s+(\d{1,2}\s+\w+\s+\d{4})",
    re.IGNORECASE,
)
_BULAN_RE = re.compile(
    r"(?:bagi\s+)?bulan\s+(\w+\s+\d{4})",
    re.IGNORECASE,
)
_MONTH_YEAR_RE = re.compile(
    r"\b(" + "|".join(MALAY_MONTHS) + r")\s+(\d{4})\b",
    re.IGNORECASE,
)
_YEAR_ONLY_RE = re.compile(r"\b(20\d{2})\b")


def extract_date_from_title(title: str) -> str:
    """
    Attempt to parse a date from a document title string.

    Strategy (highest specificity first):
      1. "Sehingga DD Month YYYY"  → full date
      2. "Bulan Month YYYY" or bare "Month YYYY"  → first day of month
      3. Standalone 4-digit year  → January 1 of that year
    Returns ISO 8601 string or "" on failure.
    """
    if not title:
        return ""

    # 1. "Sehingga DD Month YYYY"
    m = _SEHINGGA_RE.search(title)
    if m:
        result = parse_malay_date(m.group(1))
        if result:
            return result

    # 2. "Bulan Month YYYY" or just "Month YYYY"
    m = _BULAN_RE.search(title)
    if m:
        result = parse_malay_date(m.group(1))
        if result:
            return result

    m = _MONTH_YEAR_RE.search(title)
    if m:
        result = parse_malay_date(f"1 {m.group(1)} {m.group(2)}")
        if result:
            return result

    # 3. Year only
    m = _YEAR_ONLY_RE.search(title)
    if m:
        return f"{m.group(1)}-01-01"

    return ""


# ── Date/title splitting for Pattern B ────────────────────────────────────────


def _split_date_and_title(raw_text: str) -> tuple[str, str]:
    """
    Split a combined "DATE\\nTITLE" link-text (Pattern B) into its parts.

    Heuristic: the first line that contains a 4-digit year AND a Malay month
    name is treated as the date.  Everything else is the title.
    """
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if not lines:
        return "", ""

    for i, line in enumerate(lines):
        if _YEAR_RE.search(line) and _MONTH_RE.search(line):
            date_str = line
            title_parts = [ln for j, ln in enumerate(lines) if j != i]
            return date_str, " ".join(title_parts).strip()

    # Fallback: first line is date, remainder is title
    return lines[0], " ".join(lines[1:]).strip()


# ── Main extractor ────────────────────────────────────────────────────────────


def extract_siaran_media(html: str, source_url: str) -> list[dict]:
    """
    Extract press-release items from a KPKT Siaran Media listing page.

    Handles Pattern A (strong date + separate anchor) and
    Pattern B (date embedded in anchor text).

    Returns a list of dicts:
        {
            "title":      str,
            "date_text":  str,   # raw Malay date, e.g. "4 Disember 2025"
            "href":       str,   # raw href (may be relative)
            "source_url": str,   # URL of the listing page
        }
    """
    soup = BeautifulSoup(html, "lxml")

    # The accordion container has id="accordion_<N>"
    accordion = soup.find(
        "div",
        attrs={"id": re.compile(r"^accordion_\d+$")},
    )
    if not accordion:
        log.warning(
            {"event": "no_accordion_found", "url": source_url, "category": "parse"}
        )
        return []

    seen_hrefs: set[str] = set()
    items: list[dict] = []

    for h3 in accordion.find_all("h3"):
        section_div = h3.find_next_sibling("div")
        if not section_div:
            continue

        # ── Pattern A ─────────────────────────────────────────────────────────
        # <p><strong>DATE</strong><br/><a href="...">TITLE</a></p>
        for p_tag in section_div.find_all("p"):
            strong = p_tag.find("strong")
            a_tag = p_tag.find("a", href=True)
            if strong and a_tag:
                href = a_tag["href"].strip()
                if href in seen_hrefs:
                    continue
                seen_hrefs.add(href)
                items.append(
                    {
                        "title": a_tag.get_text(strip=True),
                        "date_text": strong.get_text(strip=True),
                        "href": href,
                        "source_url": source_url,
                    }
                )

        # ── Pattern B ─────────────────────────────────────────────────────────
        # <a href="...">DATE\nTITLE</a>  (date and title combined in link text)
        for a_tag in section_div.find_all("a", href=True):
            # Skip links already captured by Pattern A
            parent_p = a_tag.find_parent("p")
            if parent_p and parent_p.find("strong"):
                continue

            href = a_tag["href"].strip()
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            raw_text = a_tag.get_text(separator="\n")
            date_text, title = _split_date_and_title(raw_text)
            items.append(
                {
                    "title": title or a_tag.get_text(strip=True),
                    "date_text": date_text,
                    "href": href,
                    "source_url": source_url,
                }
            )

    log.info(
        {
            "event": "extraction_complete",
            "url": source_url,
            "item_count": len(items),
        }
    )
    return items


# ── /index.php/dl/ URL resolver ───────────────────────────────────────────────

_DL_PATH_RE = re.compile(r"^/index\.php/dl/([0-9a-fA-F]+)$")
_KPKT_RESOURCES_BASE = "https://www.kpkt.gov.my/kpkt/resources/"


def resolve_dl_url(href: str) -> str:
    """
    Resolve an obfuscated /index.php/dl/<HEX> link to a direct resource URL.

    Encoding scheme (confirmed by decoding live site links):
        hex_decode(HEX)  →  base64_string
        base64_decode(base64_string)  →  path under /kpkt/resources/

    Returns the resolved URL, or the original href if it cannot be decoded.
    """
    m = _DL_PATH_RE.match(href)
    if not m:
        return href
    try:
        b64_bytes = binascii.unhexlify(m.group(1))
        path = base64.b64decode(b64_bytes).decode("utf-8")
        return _KPKT_RESOURCES_BASE + path
    except Exception:
        log.warning({"event": "dl_url_decode_failure", "href": href, "category": "parse"})
        return href


def is_dl_url(href: str) -> bool:
    """Return True if the href is an obfuscated /index.php/dl/ link."""
    return bool(_DL_PATH_RE.match(href))


# ── Downloads Hub extractor ───────────────────────────────────────────────────


def extract_downloads_hub(html: str, source_url: str, base_url: str) -> list[str]:
    """
    Extract sub-page URLs from a KPKT Downloads Hub page
    (e.g. /index.php/pages/view/1026 – "Muat Turun").

    The hub uses a jQuery UI Accordion where each panel contains a link to
    a sub-page (not a direct document link).  Returns a list of absolute URLs
    to follow.
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")
    accordion = soup.find("div", attrs={"id": re.compile(r"^accordion_\d+$")})
    if not accordion:
        log.warning({"event": "hub_no_accordion", "url": source_url, "category": "parse"})
        return []

    sub_urls: list[str] = []
    seen: set[str] = set()

    for a_tag in accordion.find_all("a", href=True):
        href = a_tag["href"].strip()
        # Only follow /index.php/pages/view/ links (sub-pages, not documents)
        if "/pages/view/" not in href:
            continue
        abs_url = make_absolute(href, base_url)
        if abs_url not in seen:
            seen.add(abs_url)
            sub_urls.append(abs_url)

    log.info(
        {
            "event": "hub_extraction_complete",
            "url": source_url,
            "sub_page_count": len(sub_urls),
        }
    )
    return sub_urls


# ── Container Attachments extractor ──────────────────────────────────────────


def extract_container_attachments(
    html: str,
    source_url: str,
    base_url: str,
    doc_type: str = "other",
) -> list[dict]:
    """
    Extract downloadable file records from a .container_attachments table page.

    Used by:
      - Senarai Perundangan (legislation)        → doc_type="legislation"
      - Borang Tribunal (tribunal forms)         → doc_type="form"
      - Borang Kredit Komuniti (BKK/PPG/PPW)     → doc_type="form"
      - Pengurusan Kualiti (quality management)  → doc_type="report"

    Handles both direct (/kpkt/resources/...) and obfuscated
    (/index.php/dl/<HEX>) download links.

    Returns list of dicts:
        {
            "title":      str,
            "date_text":  str,   # usually "" (standing documents have no date)
            "href":       str,   # resolved absolute URL (dl/ links are decoded)
            "source_url": str,
            "doc_type":   str,
        }
    """
    from .crawler import make_absolute

    soup = BeautifulSoup(html, "lxml")

    # Gather all download links across ALL .container_attachments containers
    # (some pages have multiple).
    containers = soup.find_all("div", class_="container_attachments")
    if not containers:
        # Fallback: search the whole page for the attachment table
        containers = [soup]

    seen_hrefs: set[str] = set()
    items: list[dict] = []

    for container in containers:
        for a_tag in container.find_all("a", href=True):
            href = a_tag["href"].strip()

            # Only capture document links (PDF, DOC, DOCX, XLS, ZIP, or dl/)
            is_doc = any(
                href.lower().endswith(ext)
                for ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")
            )
            if not is_doc and not is_dl_url(href):
                continue

            # Resolve obfuscated dl/ links
            if is_dl_url(href):
                resolved = resolve_dl_url(href)
            else:
                resolved = make_absolute(href, base_url)

            if resolved in seen_hrefs:
                continue
            seen_hrefs.add(resolved)

            # Title: table row label → <li> text → link text fallback
            title = _nearest_label(a_tag)

            # Try to extract a date from the title (works for periodic/statistical
            # reports where the covered period is embedded in the document name).
            date_from_title = extract_date_from_title(title)

            items.append(
                {
                    "title": title,
                    "date_text": date_from_title,
                    "href": resolved,
                    "source_url": source_url,
                    "doc_type": doc_type,
                }
            )

    log.info(
        {
            "event": "attachment_extraction_complete",
            "url": source_url,
            "item_count": len(items),
        }
    )
    return items


def _nearest_label(a_tag) -> str:
    """
    Find a meaningful text label for an attachment link.

    Checks in order of specificity:
      1. Sibling <td> in the same <tr> that contains descriptive text
         (table layout – Senarai Perundangan, BKK forms, etc.)
      2. Full text of the containing <li>
         (list layout – Piagam Pelanggan, Statistik Online, etc.)
      3. Link's own text (image alt text excluded)
      4. Raw href tail as last resort
    """
    link_text = a_tag.get_text(strip=True)

    # 1. Sibling <td> in same <tr>
    parent_tr = a_tag.find_parent("tr")
    if parent_tr:
        for cell in parent_tr.find_all("td"):
            text = cell.get_text(strip=True)
            if text and a_tag not in cell.find_all("a"):
                return text

    # 2. Containing <li> text (strip the link text to avoid duplication)
    parent_li = a_tag.find_parent("li")
    if parent_li:
        li_text = parent_li.get_text(separator=" ", strip=True)
        if li_text and li_text != link_text:
            return li_text

    # 3. Link's own visible text
    if link_text:
        return link_text

    # 4. Filename from href
    return a_tag.get("href", "")[:80]
