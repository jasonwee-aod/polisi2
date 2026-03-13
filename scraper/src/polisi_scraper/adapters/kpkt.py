"""KPKT adapter — Custom Joomla, hex-obfuscated downloads.

Site: https://www.kpkt.gov.my
CMS:  Custom Joomla with jQuery UI Accordion and hex-obfuscated /index.php/dl/ links.

Three page archetypes are handled:

1. Siaran Media (press releases)
   jQuery UI Accordion with month headers.
   Pattern A: <p><strong>DATE</strong><br/><a href>TITLE</a></p>
   Pattern B: <a href>DATE\\nTITLE</a>

2. Downloads Hub  (/index.php/pages/view/1026)
   Accordion where each panel links to a sub-page, not a document.
   Sub-page URLs are followed automatically (hub-and-spoke navigation).

3. Container Attachments  (.container_attachments table)
   Used by legislation, forms, and quality-management pages.
   Both direct links (/kpkt/resources/...) and obfuscated
   /index.php/dl/<HEX> links are resolved.

   /index.php/dl/ URL scheme:
       hex_string  ->  hex-decode  ->  base64 string
       base64 string  ->  base64-decode  ->  file path suffix
       full URL = https://www.kpkt.gov.my/kpkt/resources/<suffix>
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
from datetime import date
from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from polisi_scraper.adapters.base import (
    BaseSiteAdapter,
    DiscoveredItem,
    DocumentCandidate,
)
from polisi_scraper.adapters.registry import register_adapter
from polisi_scraper.core.dates import parse_malay_date
from polisi_scraper.core.extractors import DownloadLink, extract_document_links
from polisi_scraper.core.urls import canonical_url, guess_content_type, make_absolute

log = logging.getLogger(__name__)

BASE_URL = "https://www.kpkt.gov.my"

# Document file extensions to capture.
_DOC_EXTENSIONS = frozenset(
    {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip"}
)

# Regex for /index.php/dl/<HEX> obfuscated download paths.
_DL_PATH_RE = re.compile(r"^/index\.php/dl/([0-9a-fA-F]+)$")

# Base URL for resolved resource paths.
_KPKT_RESOURCES_BASE = "https://www.kpkt.gov.my/kpkt/resources/"

# Match a bare 4-digit year (2000-2029).
_YEAR_RE = re.compile(r"\b20\d{2}\b")

# Malay month pattern (for date/title splitting in Pattern B links).
_MONTH_RE = re.compile(
    r"\b(januari|februari|mac|april|mei|jun|julai|ogos|september|oktober|november|disember)\b",
    re.IGNORECASE,
)

# Date extraction from title text patterns (statistics/reports).
_SEHINGGA_RE = re.compile(
    r"sehingga\s+(\d{1,2}\s+\w+\s+\d{4})",
    re.IGNORECASE,
)
_BULAN_RE = re.compile(
    r"(?:bagi\s+)?bulan\s+(\w+\s+\d{4})",
    re.IGNORECASE,
)
_MONTH_YEAR_RE = re.compile(
    r"\b(januari|februari|mac|april|mei|jun|julai|ogos|september|oktober|november|disember)"
    r"\s+(\d{4})\b",
    re.IGNORECASE,
)
_YEAR_ONLY_RE = re.compile(r"\b(20\d{2})\b")


# ---------------------------------------------------------------------------
# Hex-obfuscated download URL resolution
# ---------------------------------------------------------------------------


def resolve_dl_url(href: str) -> str:
    """Resolve an obfuscated /index.php/dl/<HEX> link to a direct resource URL.

    Encoding scheme (confirmed by decoding live site links):
        hex_decode(HEX)  ->  base64_string
        base64_decode(base64_string)  ->  path under /kpkt/resources/

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
        log.warning("[kpkt] dl_url_decode_failure href=%s", href)
        return href


def is_dl_url(href: str) -> bool:
    """Return True if the href is an obfuscated /index.php/dl/ link."""
    return bool(_DL_PATH_RE.match(href))


def _is_doc_link(href: str) -> bool:
    """Return True if the href points to a downloadable document."""
    lower = urlparse(href).path.lower()
    return any(lower.endswith(ext) for ext in _DOC_EXTENSIONS)


# ---------------------------------------------------------------------------
# Date extraction from title text (statistics/reports)
# ---------------------------------------------------------------------------


def _extract_date_from_title(title: str) -> str:
    """Attempt to parse a date from a document title string.

    Strategy (highest specificity first):
      1. "Sehingga DD Month YYYY"  -> full date
      2. "Bulan Month YYYY" or bare "Month YYYY"  -> first day of month
      3. Standalone 4-digit year  -> January 1 of that year
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


# ---------------------------------------------------------------------------
# Date/title splitting for Pattern B (combined link text)
# ---------------------------------------------------------------------------


def _split_date_and_title(raw_text: str) -> tuple[str, str]:
    """Split a combined "DATE\\nTITLE" link-text (Pattern B) into its parts.

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


# ---------------------------------------------------------------------------
# Nearest label helper (for container_attachments)
# ---------------------------------------------------------------------------


def _nearest_label(a_tag) -> str:
    """Find a meaningful text label for an attachment link.

    Checks in order of specificity:
      1. Sibling <td> in the same <tr> that contains descriptive text
      2. Full text of the containing <li>
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

    # 2. Containing <li> text
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


# ---------------------------------------------------------------------------
# Since-date filter helper
# ---------------------------------------------------------------------------


def _since_filter(pub_date: str, since: date | None) -> bool:
    """Return True if the item should be SKIPPED (published before since)."""
    if not since or not pub_date:
        return False
    try:
        return date.fromisoformat(pub_date) < since
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Siaran Media (press release) accordion extractor
# ---------------------------------------------------------------------------


def _extract_siaran_media(html: str, source_url: str) -> list[dict]:
    """Extract press-release items from a KPKT Siaran Media listing page.

    Handles Pattern A (strong date + separate anchor) and
    Pattern B (date embedded in anchor text).

    Returns a list of dicts:
        {
            "title":      str,
            "date_text":  str,
            "href":       str,   # absolute URL
            "source_url": str,
        }
    """
    soup = BeautifulSoup(html, "lxml")

    accordion = soup.find(
        "div",
        attrs={"id": re.compile(r"^accordion_\d+$")},
    )
    if not accordion:
        log.warning("[kpkt] no accordion found on %s", source_url)
        return []

    seen_hrefs: set[str] = set()
    items: list[dict] = []

    for h3 in accordion.find_all("h3"):
        section_div = h3.find_next_sibling("div")
        if not section_div:
            continue

        # Pattern A: <p><strong>DATE</strong><br/><a href>TITLE</a></p>
        for p_tag in section_div.find_all("p"):
            strong = p_tag.find("strong")
            a_tag = p_tag.find("a", href=True)
            if strong and a_tag:
                href = a_tag["href"].strip()
                abs_href = make_absolute(href, source_url)
                if abs_href in seen_hrefs:
                    continue
                seen_hrefs.add(abs_href)
                items.append(
                    {
                        "title": a_tag.get_text(strip=True),
                        "date_text": strong.get_text(strip=True),
                        "href": abs_href,
                        "source_url": source_url,
                    }
                )

        # Pattern B: <a href>DATE\nTITLE</a>
        for a_tag in section_div.find_all("a", href=True):
            parent_p = a_tag.find_parent("p")
            if parent_p and parent_p.find("strong"):
                continue

            href = a_tag["href"].strip()
            abs_href = make_absolute(href, source_url)
            if abs_href in seen_hrefs:
                continue
            seen_hrefs.add(abs_href)

            raw_text = a_tag.get_text(separator="\n")
            date_text, title = _split_date_and_title(raw_text)
            items.append(
                {
                    "title": title or a_tag.get_text(strip=True),
                    "date_text": date_text,
                    "href": abs_href,
                    "source_url": source_url,
                }
            )

    log.info("[kpkt] siaran_media extracted %d items from %s", len(items), source_url)
    return items


# ---------------------------------------------------------------------------
# Downloads Hub extractor (hub-and-spoke navigation)
# ---------------------------------------------------------------------------


def _extract_downloads_hub(html: str, source_url: str) -> list[str]:
    """Extract sub-page URLs from the KPKT Downloads Hub accordion.

    Returns a list of absolute URLs to follow (sub-pages, not documents).
    """
    soup = BeautifulSoup(html, "lxml")
    accordion = soup.find("div", attrs={"id": re.compile(r"^accordion_\d+$")})
    if not accordion:
        log.warning("[kpkt] hub: no accordion found on %s", source_url)
        return []

    sub_urls: list[str] = []
    seen: set[str] = set()

    for a_tag in accordion.find_all("a", href=True):
        href = a_tag["href"].strip()
        if "/pages/view/" not in href:
            continue
        abs_url = make_absolute(href, source_url)
        if abs_url not in seen:
            seen.add(abs_url)
            sub_urls.append(abs_url)

    log.info("[kpkt] hub: %d sub-pages from %s", len(sub_urls), source_url)
    return sub_urls


# ---------------------------------------------------------------------------
# Container Attachments extractor
# ---------------------------------------------------------------------------


def _extract_container_attachments(
    html: str,
    source_url: str,
    doc_type: str = "other",
) -> list[dict]:
    """Extract downloadable file records from .container_attachments pages.

    Handles both direct (/kpkt/resources/...) and obfuscated
    (/index.php/dl/<HEX>) download links.

    Returns list of dicts:
        {
            "title":      str,
            "date_text":  str,
            "href":       str,   # resolved absolute URL (dl/ links decoded)
            "source_url": str,
            "doc_type":   str,
        }
    """
    soup = BeautifulSoup(html, "lxml")

    containers = soup.find_all("div", class_="container_attachments")
    if not containers:
        # Fallback: search the whole page for attachment links
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
                resolved = make_absolute(href, source_url)

            if resolved in seen_hrefs:
                continue
            seen_hrefs.add(resolved)

            title = _nearest_label(a_tag)
            date_from_title = _extract_date_from_title(title)

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
        "[kpkt] container_attachments extracted %d items from %s",
        len(items),
        source_url,
    )
    return items


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@register_adapter
class KpktAdapter(BaseSiteAdapter):
    """KPKT adapter — Custom Joomla with hex-obfuscated downloads."""

    slug = "kpkt"
    agency = "Kementerian Pembangunan Kerajaan Tempatan (KPKT)"
    requires_browser = False

    def _base_url(self) -> str:
        return self.config.get("base_url", BASE_URL)

    # --- discover() ---------------------------------------------------------

    def discover(
        self, since: date | None = None, max_pages: int = 0
    ) -> Iterable[DiscoveredItem]:
        """Walk all configured sections and yield DiscoveredItems.

        Sections from the config mirror kpkt.yaml and are routed to the
        correct extractor based on page_type / doc_type:
          - siaran_media  -> accordion press-release extraction
          - hub           -> follow accordion sub-page links, then extract attachments
          - attachments   -> container_attachments extraction
        """
        sections = self.config.get("sections", [])
        page_count = 0

        for section in sections:
            section_name = section.get("name", "unknown")
            page_type = section.get("page_type", "")
            doc_type = section.get("doc_type", "other")
            language = section.get("language", "ms")

            log.info(
                "[kpkt] discover section=%s page_type=%s doc_type=%s",
                section_name,
                page_type,
                doc_type,
            )

            for listing in section.get("listing_pages", []):
                if max_pages and page_count >= max_pages:
                    log.info("[kpkt] max_pages=%d reached, stopping", max_pages)
                    return

                url = listing.get("url", "")
                if not url:
                    continue

                if page_type == "hub":
                    yield from self._discover_hub(
                        url, doc_type, language, since,
                    )
                elif doc_type == "press_release":
                    yield from self._discover_siaran_media(
                        url, doc_type, language, since,
                    )
                else:
                    # Default: container_attachments / generic page
                    yield from self._discover_attachments(
                        url, doc_type, language, since,
                    )

                page_count += 1

    # --- Siaran Media (press releases) discovery ----------------------------

    def _discover_siaran_media(
        self,
        listing_url: str,
        doc_type: str,
        language: str,
        since: date | None,
    ) -> Iterable[DiscoveredItem]:
        """Fetch a Siaran Media listing page and yield press-release items."""
        html = self._fetch_html(listing_url)
        if html is None:
            return

        items = _extract_siaran_media(html, listing_url)

        for item in items:
            pub_date = parse_malay_date(item.get("date_text", ""))

            if _since_filter(pub_date, since):
                continue

            yield DiscoveredItem(
                source_url=item["href"],
                title=item.get("title", ""),
                published_at=pub_date,
                doc_type=doc_type,
                language=language,
                metadata={
                    "listing_url": listing_url,
                    "section": "siaran_media",
                    "date_text": item.get("date_text", ""),
                },
            )

    # --- Hub (downloads hub with sub-pages) discovery -----------------------

    def _discover_hub(
        self,
        hub_url: str,
        doc_type: str,
        language: str,
        since: date | None,
    ) -> Iterable[DiscoveredItem]:
        """Fetch the downloads hub page and follow sub-page links."""
        html = self._fetch_html(hub_url)
        if html is None:
            return

        sub_urls = _extract_downloads_hub(html, hub_url)

        for sub_url in sub_urls:
            yield from self._discover_attachments(
                sub_url, doc_type, language, since,
            )

    # --- Container Attachments discovery ------------------------------------

    def _discover_attachments(
        self,
        page_url: str,
        doc_type: str,
        language: str,
        since: date | None,
    ) -> Iterable[DiscoveredItem]:
        """Fetch an attachments page and yield document items."""
        html = self._fetch_html(page_url)
        if html is None:
            return

        items = _extract_container_attachments(html, page_url, doc_type)

        for item in items:
            pub_date = item.get("date_text", "")
            effective_doc_type = item.get("doc_type", doc_type)

            if _since_filter(pub_date, since):
                continue

            yield DiscoveredItem(
                source_url=item["href"],
                title=item.get("title", ""),
                published_at=pub_date,
                doc_type=effective_doc_type,
                language=language,
                metadata={
                    "listing_url": page_url,
                    "section": "attachments",
                },
            )

    # --- fetch_and_extract() ------------------------------------------------

    def fetch_and_extract(
        self, item: DiscoveredItem
    ) -> Iterable[DocumentCandidate]:
        """KPKT discovered items are direct document URLs — yield as-is.

        Handles three cases:
        1. Direct document URL (PDF/DOC/etc.) — yield without HTML fetch.
        2. Resolved hex-obfuscated URL (already decoded to direct resource) — yield.
        3. HTML page URL (press release article) — yield the page itself.
        """
        url = item.source_url
        url_lower = url.lower().split("?")[0]

        # Direct document URL
        if any(url_lower.endswith(ext) for ext in _DOC_EXTENSIONS):
            ct = guess_content_type(url)
            yield DocumentCandidate(
                url=url,
                source_page_url=item.metadata.get("listing_url", url),
                title=item.title,
                published_at=item.published_at,
                doc_type=item.doc_type,
                content_type=ct,
                language=item.language,
            )
            return

        # HTML page (e.g. press release article pages)
        try:
            resp = self.http.get(url)
            html = resp.text
        except Exception as e:
            log.warning("[kpkt] Failed to fetch %s: %s", url, e)
            return

        # Yield the HTML page itself
        yield DocumentCandidate(
            url=url,
            source_page_url=item.metadata.get("listing_url", url),
            title=item.title,
            published_at=item.published_at,
            doc_type=item.doc_type,
            content_type="text/html",
            language=item.language,
        )

        # Also extract any embedded document links from the page
        downloads = self.extract_downloads(html, url)
        for dl in downloads:
            ct = guess_content_type(dl.url) if dl.url else ""
            yield DocumentCandidate(
                url=dl.url,
                source_page_url=url,
                title=item.title,
                published_at=item.published_at,
                doc_type=item.doc_type,
                content_type=ct,
                language=item.language,
            )

    # --- extract_downloads() override for hex-encoded links -----------------

    def extract_downloads(self, html: str, base_url: str) -> list[DownloadLink]:
        """Extract downloadable document links, resolving hex-obfuscated URLs.

        Extends the generic extractor to handle KPKT's /index.php/dl/<HEX>
        download links by decoding them to direct resource URLs.
        """
        # Start with the generic extractor
        links = extract_document_links(html, base_url)
        seen_urls = {dl.url for dl in links}

        # Scan for KPKT-specific hex-obfuscated /index.php/dl/ links
        soup = BeautifulSoup(html, "lxml")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            parsed_path = urlparse(href).path if href.startswith("http") else href

            if not is_dl_url(parsed_path):
                continue

            resolved = resolve_dl_url(parsed_path)
            abs_url = make_absolute(resolved, base_url) if not resolved.startswith("http") else resolved

            if abs_url not in seen_urls:
                seen_urls.add(abs_url)
                label = a_tag.get_text(strip=True) or href
                links.append(DownloadLink(url=abs_url, label=label))

        return links

    # --- Internal: HTTP helper ----------------------------------------------

    def _fetch_html(self, url: str) -> str | None:
        """Fetch a URL and return HTML text, or None on failure."""
        try:
            resp = self.http.get(url)
            return resp.text
        except Exception as e:
            log.warning("[kpkt] Failed to fetch %s: %s", url, e)
            return None
