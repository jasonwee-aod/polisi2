"""Dewan Selangor adapter — WordPress + pdfjs-viewer + e-QUANS.

Site: https://dewan.selangor.gov.my
CMS:  WordPress with pdfjs-viewer-shortcode plugin

Six page archetypes are handled:

1. Sitemap XML  (sitemap_index.xml, *-sitemap.xml)
   Standard XML sitemaps for URL discovery of custom post types
   (ucapan, statement, hansard, urusan-mesyuarat, sidang).

2. WordPress Listing Page  (/berita-dewan/, /kenyataan-media/, etc.)
   Standard WordPress archive pages with <article> elements.
   Pagination: /page/N/ href in <a class="next page-numbers">.

3. WordPress Single Post  (individual article URLs)
   Extracts title, published_at from post metadata.
   Surfaces embedded PDF/DOC links via pdfjs-viewer iframes and direct <a> links.

4. pdfjs-viewer Embed
   Decodes PDF URLs from pdfjs-viewer-shortcode <iframe> embeds:
       /wp-content/plugins/pdfjs-viewer-shortcode/pdfjs/web/viewer.php?file=<encoded_url>

5. Penyata Rasmi (Hansard) Hub  (/penyata-rasmi/)
   3-level structure: hub index page -> session pages -> direct PDF files.
   Hub: .hansard-item divs with year groups and session links.
   Session: <p class="mb-2"> elements with dated PDF hrefs.

6. e-QUANS (Question archive)  (/question/, /question/page/N/)
   Bootstrap-paginated listing of oral and written assembly questions.
   Listing: div.card.question cards; pagination via li.page-item.next a.page-link.
   Single question page: title from og:title; date from .sidang-details p.lead small;
   attachments from .list-of-attachments.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Iterable, Optional
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from polisi_scraper.adapters.base import BaseSiteAdapter, DiscoveredItem, DocumentCandidate
from polisi_scraper.adapters.registry import register_adapter
from polisi_scraper.core.dates import parse_iso_date, parse_malay_date
from polisi_scraper.core.extractors import DownloadLink, extract_document_links
from polisi_scraper.core.urls import canonical_url, guess_content_type, make_absolute

log = logging.getLogger(__name__)

BASE_URL = "https://dewan.selangor.gov.my"

_DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")

# Regex to match pdfjs-viewer-shortcode iframe src URLs
_PDFJS_VIEWER_RE = re.compile(
    r"pdfjs(?:-viewer-shortcode)?/pdfjs/web/viewer\.php",
    re.IGNORECASE,
)

# Strips parenthesised day name suffix, e.g. "(SELASA)" or "(ISNIN)"
_DAY_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")


# ---------------------------------------------------------------------------
# HTML extraction helpers
# ---------------------------------------------------------------------------


def _parse_wp_datetime(dt_str: str) -> str:
    """Parse a WordPress ISO 8601 datetime attribute to ISO date string.

    Handles: "2025-01-15T10:30:00+08:00", "2025-01-15", etc.
    Returns "YYYY-MM-DD" or "".
    """
    return parse_iso_date(dt_str)


def _parse_hansard_date(date_str: str) -> str:
    """Parse a hansard sitting date label into ISO 8601 (YYYY-MM-DD).

    Input examples:
        "18 FEB 2025 (SELASA)"    -> "2025-02-18"
        "3 MAC 2025 (ISNIN)"      -> "2025-03-03"
        "1 DISEMBER 2025 (SELASA)" -> "2025-12-01"
    """
    if not date_str or not date_str.strip():
        return ""
    cleaned = _DAY_PAREN_RE.sub("", date_str.strip())
    return parse_malay_date(cleaned)


def _parse_equans_date_range(text: str) -> str:
    """Parse an e-QUANS sitting date range into the start date (ISO 8601).

    Input examples:
        "17 Ogos - 20 Ogos 2015"   -> "2015-08-17"
        "3 Mac - 5 Mac 2023"        -> "2023-03-03"
        "21 Oktober 2019"           -> "2019-10-21"  (single date, no range)

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


def _since_filter(pub_date: str, since: date | None) -> bool:
    """Return True if the item should be SKIPPED (published before since)."""
    if not since or not pub_date:
        return False
    try:
        return date.fromisoformat(pub_date) < since
    except ValueError:
        return False


# -- Sitemap XML parser --


def _parse_sitemap_xml(xml: str, source_url: str) -> list[dict]:
    """Parse a standard XML sitemap and return URL entries.

    Handles both sitemap index files (lists child sitemaps) and regular
    URL-set sitemaps (lists <url> entries).

    Returns a list of dicts:
        {"url": str, "lastmod": str, "is_sitemap_index": bool}
    """
    soup = BeautifulSoup(xml, "lxml-xml")
    entries: list[dict] = []

    # Sitemap index: <sitemapindex> -> child <sitemap> elements
    sitemap_index = soup.find("sitemapindex")
    if sitemap_index:
        for sm in sitemap_index.find_all("sitemap"):
            loc = sm.find("loc")
            lastmod = sm.find("lastmod")
            if not loc:
                continue
            entries.append({
                "url": loc.get_text(strip=True),
                "lastmod": lastmod.get_text(strip=True) if lastmod else "",
                "is_sitemap_index": True,
            })
        log.info("[dewan_selangor] sitemap index parsed: %d child sitemaps from %s",
                 len(entries), source_url)
        return entries

    # Regular URL-set sitemap: <urlset> -> <url> elements
    urlset = soup.find("urlset")
    if urlset:
        for url_tag in urlset.find_all("url"):
            loc = url_tag.find("loc")
            lastmod = url_tag.find("lastmod")
            if not loc:
                continue
            entries.append({
                "url": loc.get_text(strip=True),
                "lastmod": lastmod.get_text(strip=True) if lastmod else "",
                "is_sitemap_index": False,
            })
        log.info("[dewan_selangor] sitemap parsed: %d URLs from %s",
                 len(entries), source_url)
        return entries

    log.warning("[dewan_selangor] empty sitemap: %s", source_url)
    return entries


# -- WordPress Listing Page extractor --


def _extract_wp_listing(html: str, source_url: str) -> list[dict]:
    """Extract article links from a WordPress archive listing page.

    Returns list of dicts:
        {"title": str, "href": str, "date_text": str, "source_url": str}
    """
    soup = BeautifulSoup(html, "lxml")
    seen_hrefs: set[str] = set()
    items: list[dict] = []

    articles = soup.find_all("article")
    if not articles:
        articles = soup.find_all("div", class_=re.compile(r"\bpost\b|\btype-post\b"))

    for article in articles:
        title_tag = article.find(["h2", "h3"], class_=re.compile(r"entry-title"))
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

        # Date: <time datetime="..."> inside the article
        time_tag = article.find("time", {"datetime": True})
        date_text = time_tag["datetime"].strip() if time_tag else ""

        items.append({
            "title": title,
            "href": href,
            "date_text": date_text,
            "source_url": source_url,
        })

    # Fallback scan for .entry-title links
    if not items:
        for a_tag in soup.find_all("a", class_=re.compile(r"entry-title|post-title"), href=True):
            href = a_tag["href"].strip()
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            items.append({
                "title": a_tag.get_text(strip=True),
                "href": href,
                "date_text": "",
                "source_url": source_url,
            })

    log.info("[dewan_selangor] WP listing: %d items from %s", len(items), source_url)
    return items


def _get_next_wp_listing_page_url(html: str) -> Optional[str]:
    """Find the 'next page' URL in a WordPress paginated archive.

    WordPress standard pagination:
        <a class="next page-numbers" href="https://.../page/2/">...</a>
    """
    soup = BeautifulSoup(html, "lxml")
    next_link = soup.find("a", class_=re.compile(r"\bnext\b.*page-numbers|page-numbers.*\bnext\b"))
    if next_link and next_link.get("href"):
        return next_link["href"].strip()
    return None


# -- WordPress Single Post meta extractor --


def _extract_wp_post_meta(html: str, source_url: str) -> dict:
    """Extract metadata from a WordPress single post/page.

    Returns: {"title": str, "published_at": str}
    """
    soup = BeautifulSoup(html, "lxml")

    # Title
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
            title = raw.split("|")[0].strip() if "|" in raw else raw.split("\u2013")[0].strip()

    # Published date
    published_at = ""

    # 1. <time class="entry-date published" datetime="...">
    time_tag = soup.find(
        "time",
        class_=re.compile(r"entry-date.*published|published.*entry-date"),
    )
    if not time_tag:
        time_tag = soup.find("time", class_=re.compile(r"\bpublished\b"))
    if time_tag and time_tag.get("datetime"):
        published_at = _parse_wp_datetime(time_tag["datetime"])

    # 2. <meta property="article:published_time">
    if not published_at:
        meta_pub = soup.find("meta", property="article:published_time")
        if meta_pub and meta_pub.get("content"):
            published_at = _parse_wp_datetime(meta_pub["content"])

    # 3. <time class="updated"> as a last resort
    if not published_at:
        updated_tag = soup.find("time", class_=re.compile(r"\bupdated\b"))
        if updated_tag and updated_tag.get("datetime"):
            published_at = _parse_wp_datetime(updated_tag["datetime"])

    # 4. e-QUANS: .sidang-details p.lead small -> date range
    if not published_at:
        sidang = soup.find("div", class_="sidang-details")
        if sidang:
            lead = sidang.find("p", class_="lead")
            if lead:
                small = lead.find("small")
                if small:
                    published_at = _parse_equans_date_range(small.get_text(strip=True))

    return {"title": title, "published_at": published_at}


# -- pdfjs-viewer and embedded document link extractor --


def _extract_embedded_doc_links(html: str, base_url: str) -> list[DownloadLink]:
    """Find all document download links embedded in a WordPress post body.

    Three sources:
      1. pdfjs-viewer <iframe>: extract PDF URL from the `file` query parameter.
      2. Direct <a href> links to document files in the post content area.
      3. e-QUANS .list-of-attachments section.

    Returns a deduplicated list of DownloadLink objects.
    """
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    links: list[DownloadLink] = []

    def _add(url: str, label: str) -> None:
        abs_url = make_absolute(url, base_url)
        if abs_url not in seen and abs_url.startswith("http"):
            seen.add(abs_url)
            links.append(DownloadLink(url=abs_url, label=label))

    # 1. pdfjs-viewer iframes
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"].strip()
        if not _PDFJS_VIEWER_RE.search(src):
            continue
        qs = parse_qs(urlparse(src).query)
        file_vals = qs.get("file", [])
        if not file_vals:
            continue
        pdf_url = unquote(file_vals[0])
        _add(pdf_url, "pdfjs-viewer embed")

    # 2. Direct document links in post content area
    content_area = (
        soup.find("div", class_=re.compile(r"entry-content|post-content|article-body"))
        or soup
    )
    for a_tag in content_area.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue
        if any(href.lower().endswith(ext) for ext in _DOC_EXTENSIONS):
            label = a_tag.get_text(strip=True) or href
            _add(href, label)

    # 3. e-QUANS: .list-of-attachments
    attachments_area = soup.find("div", class_="list-of-attachments")
    if attachments_area:
        for a_tag in attachments_area.find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href or href.startswith(("javascript:", "#", "mailto:")):
                continue
            label = a_tag.get_text(strip=True) or href
            _add(href, label)

    return links


# -- Hansard hub extractors --


def _extract_hansard_index(html: str, source_url: str) -> list[dict]:
    """Extract session page links from the /penyata-rasmi/ hub page.

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

        # Session links in .col-sm-10
        link_col = item_div.find("div", class_=re.compile(r"\bcol-sm-10\b"))
        if not link_col:
            continue

        for a in link_col.find_all("a", href=True):
            href = a["href"].strip()
            if href in seen:
                continue
            seen.add(href)
            items.append({
                "href": href,
                "title": a.get_text(strip=True),
                "year": year,
                "source_url": source_url,
            })

    log.info("[dewan_selangor] hansard index: %d session links from %s",
             len(items), source_url)
    return items


def _extract_hansard_session_pdfs(html: str, source_url: str, base_url: str) -> list[dict]:
    """Extract PDF links from a hansard session page (/hansard/sesi-N-N/).

    Returns list of dicts:
        {"href": str, "title": str, "date_text": str, "source_url": str}
    """
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
        items.append({
            "href": abs_href,
            "title": label,
            "date_text": label,  # e.g. "18 FEB 2025 (SELASA)"
            "source_url": source_url,
        })

    log.info("[dewan_selangor] hansard session: %d PDFs from %s",
             len(items), source_url)
    return items


# -- e-QUANS listing extractors --


def _extract_equans_listing(html: str, source_url: str) -> list[dict]:
    """Extract question links from /question/ or /question/page/N/ listing pages.

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
        items.append({
            "title": a.get_text(strip=True),
            "href": href,
            "date_text": "",
            "source_url": source_url,
        })

    log.info("[dewan_selangor] e-QUANS listing: %d items from %s",
             len(items), source_url)
    return items


def _get_next_equans_page_url(html: str, current_url: str) -> Optional[str]:
    """Find the 'next page' URL in the Bootstrap pagination used by /question/.

    The live site uses numbered <li class="page-item"> links without a dedicated
    "next" class.  We find the currently-active page number and return the link
    for page N+1.  Falls back to an explicit "next" <li> if present.
    """
    soup = BeautifulSoup(html, "lxml")
    page_items = soup.find_all("li", class_="page-item")
    if not page_items:
        return None

    # Strategy 1: explicit "next" class
    for li in page_items:
        if "next" in li.get("class", []):
            a = li.find("a", href=True)
            if a and a["href"].strip() != "#":
                return a["href"].strip()

    # Strategy 2: find active page number, then return N+1 link
    active_num = None
    for li in page_items:
        if "active" in li.get("class", []):
            a = li.find("a", href=True)
            txt = (a.get_text(strip=True) if a else li.get_text(strip=True))
            if txt.isdigit():
                active_num = int(txt)
            break

    if active_num is not None:
        target = str(active_num + 1)
        for li in page_items:
            if "active" in li.get("class", []) or "disabled" in li.get("class", []):
                continue
            a = li.find("a", href=True)
            if a and a.get_text(strip=True) == target and a["href"].strip() != "#":
                return a["href"].strip()

    return None


def _extract_equans_session_index(html: str, source_url: str) -> list[dict]:
    """Extract session links from /tahun-dan-sesi/ page.

    Each card represents a year with session links inside.
    Returns list of dicts: {"href": str, "title": str, "year": str}
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()

    for card in soup.find_all("div", class_="card"):
        header = card.find(class_=re.compile(r"card-header"))
        year = header.get_text(strip=True) if header else ""

        for a in card.find_all("a", href=True):
            href = a["href"].strip()
            if href in seen or not href:
                continue
            # Only follow /equans/ session links
            if "/equans/" not in href:
                continue
            seen.add(href)
            items.append({
                "href": href,
                "title": f"{year} {a.get_text(strip=True)}".strip(),
                "year": year,
            })

    log.info("[dewan_selangor] e-QUANS session index: %d sessions from %s",
             len(items), source_url)
    return items


def _extract_equans_session_categories(html: str, source_url: str, base_url: str) -> list[dict]:
    """Extract question category listing URLs from an e-QUANS session page.

    Each session page (e.g. /equans/41679/) has cards like:
        "Soalan Bertulis 1-390" -> /question?filter_question=1&...
        "Soalan Mulut 1-400"    -> /question?filter_question=1&...

    Returns list of dicts: {"href": str, "title": str}
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()

    for card in soup.find_all("div", class_="card"):
        a = card.find("a", href=True)
        if not a:
            continue
        href = a["href"].strip()
        if not href or href in seen:
            continue
        # Only follow /question links
        abs_href = make_absolute(href, base_url)
        if "/question" not in abs_href:
            continue
        seen.add(href)
        header = card.find(class_=re.compile(r"card-header|card-title"))
        title = header.get_text(strip=True) if header else a.get_text(strip=True)
        items.append({"href": abs_href, "title": title})

    log.info("[dewan_selangor] e-QUANS session categories: %d from %s",
             len(items), source_url)
    return items


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@register_adapter
class DewanSelangorAdapter(BaseSiteAdapter):
    slug = "dewan_selangor"
    agency = "Dewan Negeri Selangor"
    requires_browser = False

    def _base_url(self) -> str:
        return self.config.get("base_url", BASE_URL)

    # --- HOOK 1: Discovery --------------------------------------------------

    def discover(self, since: date | None = None, max_pages: int = 0) -> Iterable[DiscoveredItem]:
        """Walk all configured sections and yield DiscoveredItems.

        Sections are declared in the adapter config (mirroring dewan_selangor.yaml):
          - listing sections (WordPress archive pages with WP/Bootstrap pagination)
          - sitemap sections (XML sitemap-based discovery)
          - hub section (3-level Hansard hub navigation)
          - equans section (Bootstrap-paginated question listing)
        """
        sections = self.config.get("sections", [])

        for section in sections:
            source_type = section.get("source_type", "listing")
            doc_type = section.get("doc_type", "other")
            language = section.get("language", "ms")
            section_name = section.get("name", "unknown")

            log.info("[dewan_selangor] discover section=%s source_type=%s",
                     section_name, source_type)

            if source_type == "sitemap":
                sitemap_url = section.get("sitemap_url", "")
                if not sitemap_url:
                    log.warning("[dewan_selangor] section %s missing sitemap_url",
                                section_name)
                    continue
                yield from self._discover_from_sitemap(
                    sitemap_url, doc_type, language, since,
                )

            elif source_type == "hub":
                hub_page = section.get("hub_page", "")
                if not hub_page:
                    log.warning("[dewan_selangor] section %s missing hub_page",
                                section_name)
                    continue
                yield from self._discover_from_hub(
                    hub_page, doc_type, language, since, max_pages,
                )

            elif source_type == "equans":
                listing_url = section.get("listing_url", "")
                if not listing_url:
                    log.warning("[dewan_selangor] section %s missing listing_url",
                                section_name)
                    continue
                yield from self._discover_from_equans(
                    listing_url, doc_type, language, since, max_pages,
                )

            else:  # "listing" (default) -- paginated WordPress archive
                listing_pages = section.get("listing_pages", [])
                if not listing_pages:
                    log.warning("[dewan_selangor] section %s missing listing_pages",
                                section_name)
                    continue
                yield from self._discover_from_listing(
                    listing_pages, doc_type, language, since, max_pages,
                )

    # -- Discovery: Sitemap --

    def _discover_from_sitemap(
        self,
        sitemap_url: str,
        doc_type: str,
        language: str,
        since: date | None,
    ) -> Iterable[DiscoveredItem]:
        """Fetch a sitemap (or sitemap index) and yield DiscoveredItems.

        Recursively follows child sitemaps in a sitemap index.
        """
        log.info("[dewan_selangor] fetch sitemap: %s", sitemap_url)
        try:
            resp = self.http.get(sitemap_url)
        except Exception as exc:
            log.error("[dewan_selangor] sitemap fetch error %s: %s", sitemap_url, exc)
            return

        entries = _parse_sitemap_xml(resp.text, sitemap_url)

        for entry in entries:
            if entry.get("is_sitemap_index"):
                # Recurse into child sitemap
                yield from self._discover_from_sitemap(
                    entry["url"], doc_type, language, since,
                )
            else:
                lastmod = entry.get("lastmod", "")
                pub_date = parse_iso_date(lastmod) if lastmod else ""

                if _since_filter(pub_date, since):
                    continue

                yield DiscoveredItem(
                    source_url=entry["url"],
                    title="",  # populated later from page HTML
                    published_at=pub_date,
                    doc_type=doc_type,
                    language=language,
                    metadata={
                        "listing_url": sitemap_url,
                        "date_text": lastmod,
                        "source_type": "sitemap",
                    },
                )

    # -- Discovery: WordPress listing pages with pagination --

    def _discover_from_listing(
        self,
        listing_pages: list[dict],
        doc_type: str,
        language: str,
        since: date | None,
        max_pages: int,
    ) -> Iterable[DiscoveredItem]:
        """Walk paginated WordPress archive pages and yield DiscoveredItems.

        Pagination follows <a class="next page-numbers"> links until exhausted
        or max_pages is reached.
        """
        pages_fetched = 0

        for listing_cfg in listing_pages:
            current_url: Optional[str] = listing_cfg.get("url", "")
            if not current_url:
                continue

            while current_url:
                if max_pages and pages_fetched >= max_pages:
                    log.info("[dewan_selangor] max_pages=%d reached", max_pages)
                    return

                log.info("[dewan_selangor] fetch listing: %s", current_url)
                try:
                    resp = self.http.get(current_url)
                except Exception as exc:
                    log.error("[dewan_selangor] listing fetch error %s: %s",
                              current_url, exc)
                    break

                pages_fetched += 1
                items = _extract_wp_listing(resp.text, current_url)

                for item in items:
                    article_url = make_absolute(item["href"], self._base_url())
                    date_text = item.get("date_text", "")
                    pub_date = _parse_wp_datetime(date_text) if date_text else ""

                    if _since_filter(pub_date, since):
                        continue

                    yield DiscoveredItem(
                        source_url=article_url,
                        title=item.get("title", ""),
                        published_at=pub_date,
                        doc_type=doc_type,
                        language=language,
                        metadata={
                            "listing_url": current_url,
                            "date_text": date_text,
                            "source_type": "listing",
                        },
                    )

                current_url = _get_next_wp_listing_page_url(resp.text)

    # -- Discovery: Hansard/Penyata Rasmi 3-level hub --

    def _discover_from_hub(
        self,
        hub_page: str,
        doc_type: str,
        language: str,
        since: date | None,
        max_pages: int,
    ) -> Iterable[DiscoveredItem]:
        """Crawl the /penyata-rasmi/ hub to discover individual sitting PDFs.

        Level 1 - hub page: lists session links grouped by year.
        Level 2 - session page: lists dated PDFs for each sitting day.
        Level 3 - PDF URL: yielded as a DiscoveredItem with pre-parsed date.

        max_pages limits the number of session pages fetched (not the hub itself).
        """
        log.info("[dewan_selangor] fetch hub page: %s", hub_page)
        try:
            resp = self.http.get(hub_page)
        except Exception as exc:
            log.error("[dewan_selangor] hub fetch error %s: %s", hub_page, exc)
            return

        sessions = _extract_hansard_index(resp.text, hub_page)
        pages_fetched = 0

        for session in sessions:
            if max_pages and pages_fetched >= max_pages:
                log.info("[dewan_selangor] max_pages=%d reached (hub)", max_pages)
                return

            session_url = make_absolute(session["href"], self._base_url())
            session_can = canonical_url(session_url)

            log.info("[dewan_selangor] fetch session page: %s", session_can)
            try:
                sess_resp = self.http.get(session_can)
            except Exception as exc:
                log.error("[dewan_selangor] session fetch error %s: %s",
                          session_can, exc)
                continue

            pages_fetched += 1
            pdfs = _extract_hansard_session_pdfs(
                sess_resp.text, session_can, self._base_url(),
            )

            for pdf in pdfs:
                date_iso = _parse_hansard_date(pdf.get("date_text", ""))

                if _since_filter(date_iso, since):
                    continue

                pdf_url = canonical_url(pdf["href"])
                yield DiscoveredItem(
                    source_url=pdf_url,
                    title=pdf.get("title", ""),
                    published_at=date_iso,
                    doc_type=doc_type,
                    language=language,
                    metadata={
                        "listing_url": session_can,
                        "date_text": date_iso,
                        "source_type": "hub",
                        "year": session.get("year", ""),
                    },
                )

    # -- Discovery: e-QUANS paginated question listing --

    def _discover_from_equans(
        self,
        listing_url: str,
        doc_type: str,
        language: str,
        since: date | None,
        max_pages: int,
    ) -> Iterable[DiscoveredItem]:
        """Walk the full e-QUANS discovery chain to find question URLs.

        The chain is:
          1. Session index (/tahun-dan-sesi/) — year cards with session links
          2. Session page (/equans/{id}/) — category cards (Soalan Bertulis/Mulut)
          3. Question listing (/question?...) — paginated question cards
          4. Individual question (/question/{slug}/) — yielded as DiscoveredItem

        If listing_url points directly to /question, skip steps 1-2.
        """
        base = self._base_url()

        # Determine entry point: session index or direct question listing
        if "/question" in listing_url:
            # Direct question listing URL — skip session discovery
            yield from self._paginate_equans_listing(
                listing_url, doc_type, language, since, max_pages,
            )
            return

        # Step 1: Fetch session index page
        log.info("[dewan_selangor] fetch e-QUANS session index: %s", listing_url)
        try:
            resp = self.http.get(listing_url)
        except Exception as exc:
            log.error("[dewan_selangor] e-QUANS index fetch error %s: %s",
                      listing_url, exc)
            return

        sessions = _extract_equans_session_index(resp.text, listing_url)
        pages_fetched = 0

        for session in sessions:
            session_url = make_absolute(session["href"], base)

            # Step 2: Fetch session page to get category listing URLs
            log.info("[dewan_selangor] fetch e-QUANS session: %s", session_url)
            try:
                sess_resp = self.http.get(session_url)
            except Exception as exc:
                log.error("[dewan_selangor] e-QUANS session error %s: %s",
                          session_url, exc)
                continue

            categories = _extract_equans_session_categories(
                sess_resp.text, session_url, base,
            )

            # Step 3: Walk paginated question listings for each category
            for cat in categories:
                cat_url = cat["href"]
                yield from self._paginate_equans_listing(
                    cat_url, doc_type, language, since, max_pages,
                )

    def _paginate_equans_listing(
        self,
        listing_url: str,
        doc_type: str,
        language: str,
        since: date | None,
        max_pages: int,
    ) -> Iterable[DiscoveredItem]:
        """Paginate through a /question?... listing and yield question items."""
        pages_fetched = 0
        current_url: Optional[str] = listing_url

        while current_url:
            if max_pages and pages_fetched >= max_pages:
                log.info("[dewan_selangor] max_pages=%d reached (e-QUANS)", max_pages)
                return

            log.info("[dewan_selangor] fetch e-QUANS listing: %s", current_url)
            try:
                resp = self.http.get(current_url)
            except Exception as exc:
                log.error("[dewan_selangor] e-QUANS fetch error %s: %s",
                          current_url, exc)
                break

            pages_fetched += 1
            items = _extract_equans_listing(resp.text, current_url)

            for item in items:
                article_url = make_absolute(item["href"], self._base_url())

                yield DiscoveredItem(
                    source_url=article_url,
                    title=item.get("title", ""),
                    published_at="",
                    doc_type=doc_type,
                    language=language,
                    metadata={
                        "listing_url": current_url,
                        "source_type": "equans",
                    },
                )

            current_url = _get_next_equans_page_url(resp.text, current_url)

    # --- HOOK 2: Fetch + Extract Downloads ----------------------------------

    def fetch_and_extract(self, item: DiscoveredItem) -> Iterable[DocumentCandidate]:
        """Fetch detail page, extract metadata, and yield document candidates.

        Handles three cases:
        1. Direct document URL (PDF/DOC) -- yield as-is without HTML fetch.
        2. HTML detail page -- yield the page itself + embedded document links
           (pdfjs-viewer iframes, direct doc links, e-QUANS attachments).
        3. Sitemap/listing items -- fetch article HTML, extract WP metadata.
        """
        url = item.source_url
        url_lower = url.lower().split("?")[0]

        # Case 1: Direct document URL (e.g. hansard hub PDFs)
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

        # Case 2: HTML page -- fetch, extract metadata, yield page + embedded docs
        try:
            resp = self.http.get(url)
            html = resp.text
        except Exception as e:
            log.warning("[dewan_selangor] failed to fetch %s: %s", url, e)
            return

        # Extract metadata from article detail page
        meta = _extract_wp_post_meta(html, url)
        title = meta.get("title") or item.title
        published_at = meta.get("published_at") or item.published_at

        # Fallback: use date_text from listing metadata
        if not published_at:
            date_text = item.metadata.get("date_text", "")
            if date_text:
                published_at = _parse_wp_datetime(date_text)

        listing_url = item.metadata.get("listing_url", url)

        # Yield the HTML page itself
        yield DocumentCandidate(
            url=url,
            source_page_url=listing_url,
            title=title,
            published_at=published_at,
            doc_type=item.doc_type,
            content_type="text/html",
            language=item.language,
        )

        # Extract and yield embedded document links
        embedded_links = _extract_embedded_doc_links(html, self._base_url())
        for dl in embedded_links:
            ct = guess_content_type(dl.url)
            yield DocumentCandidate(
                url=dl.url,
                source_page_url=url,
                title=title,
                published_at=published_at,
                doc_type=item.doc_type,
                content_type=ct,
                language=item.language,
            )

    # --- HOOK 3: Download Link Extraction (override) ------------------------

    def extract_downloads(self, html: str, base_url: str) -> list[DownloadLink]:
        """Override to handle pdfjs-viewer iframes and e-QUANS attachments.

        Combines site-specific extraction with the generic extractor as fallback.
        """
        # Site-specific extraction (pdfjs-viewer + doc links + e-QUANS attachments)
        links = _extract_embedded_doc_links(html, base_url)

        # Merge in any links the generic extractor finds that we missed
        seen_urls = {dl.url for dl in links}
        for dl in extract_document_links(html, base_url):
            if dl.url not in seen_urls:
                seen_urls.add(dl.url)
                links.append(dl)

        return links
