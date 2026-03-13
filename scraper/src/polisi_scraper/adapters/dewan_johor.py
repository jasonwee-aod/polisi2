"""Dewan Johor adapter — WordPress + WPDM + Divi.

Site overview
-------------
dewannegeri.johor.gov.my runs WordPress 5.5+ with the Divi theme and WP Download
Manager Pro (wpdmpro).  All content is server-rendered — no JavaScript required.

Discovery sources:

  1. Sitemap XML  (wp-sitemap-posts-post-1.xml, wp-sitemap-posts-wpdmpro-1.xml)
     WordPress native sitemaps listing blog posts and WPDM download packages.

  2. Hub pages — single-page Divi accordion layouts that embed all PDF links
     directly in the HTML.  Four hub types:

     a. Penyata Rasmi (/pr/)
        Verbatim records.  Structure: h2 (Dewan level) > et_pb_accordion >
        et_pb_toggle (session) > h3 (meeting) + table (2-col: title | link).
        Date is extracted from document title text (Malay month names).

     b. Soalan & Jawapan Lisan (/sdjl/)
        Oral-question PDFs.  No top-level h2.  Structure: et_pb_accordion >
        et_pb_toggle (session) > p>strong (meeting) + table (1-col: link text
        is the date in Malay format, e.g. "19 Mei 2025").

     c. Soalan & Jawapan Bertulis (/sdjb/)
        Written-question PDFs.  Structurally identical to /sdjl/.

     d. Rang Undang-Undang / Enakmen (/rang-undang-undang-enakmen/)
        Bills/ordinances.  Structure: optional h2 (Dewan level) >
        et_pb_accordion > et_pb_toggle (session) > p>strong (meeting) +
        4-col table (Bil | Tarikh | Perkara | Muat Turun).

WPDM handling:
  WP Download Manager package pages (/download/{slug}/) contain file download
  links as <a class="inddl" href="...?wpdmdl=ID&ind=TIMESTAMP">.  These are
  redirect URLs — following them with requests yields the actual file.  The
  adapter's fetch_and_extract() resolves these redirects and uses the final
  URL as the canonical URL for deduplication.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from polisi_scraper.adapters.base import BaseSiteAdapter, DiscoveredItem, DocumentCandidate
from polisi_scraper.adapters.registry import register_adapter
from polisi_scraper.core.dates import parse_malay_date, parse_iso_date
from polisi_scraper.core.urls import canonical_url, guess_content_type, make_absolute
from polisi_scraper.core.extractors import extract_document_links, DownloadLink

log = logging.getLogger(__name__)

_BASE_URL = "https://dewannegeri.johor.gov.my"

# Document file extensions for direct-download detection
_DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")

# Header cell values that identify a table header row (skip these rows)
_RUU_HEADER_CELLS = frozenset({"bil", "no", "tarikh", "date", "perkara", "subject"})


# ---------------------------------------------------------------------------
# Sitemap XML parser
# ---------------------------------------------------------------------------

def _parse_sitemap_xml(xml: str) -> list[dict]:
    """Parse a standard XML sitemap and return URL entries.

    Handles both sitemap index files (lists child sitemaps) and regular
    URL-set sitemaps (lists <url> entries).

    Returns a list of dicts:
        {"url": str, "lastmod": str, "is_sitemap_index": bool}
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
            entries.append({
                "url": loc.get_text(strip=True),
                "lastmod": lastmod.get_text(strip=True) if lastmod else "",
                "is_sitemap_index": True,
            })
        return entries

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

    return entries


# ---------------------------------------------------------------------------
# Divi theme listing page extractor
# ---------------------------------------------------------------------------

def _extract_divi_listing(html: str, source_url: str) -> list[dict]:
    """Extract article links from a Divi theme archive listing page.

    Works for both standard WordPress post archives (/category/pengumuman/)
    and WP Download Manager category archives (/download-category/*/).

    Returns list of dicts: {title, href, date_text, source_url}
    """
    soup = BeautifulSoup(html, "lxml")
    seen_hrefs: set[str] = set()
    items: list[dict] = []

    articles = soup.find_all("article", class_=re.compile(r"\bet_pb_post\b|\bwpdmpro\b"))
    if not articles:
        articles = soup.find_all("article")

    for article in articles:
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

        pub_span = article.find("span", class_=re.compile(r"\bpublished\b"))
        date_text = pub_span.get_text(strip=True) if pub_span else ""

        if not date_text:
            time_tag = article.find("time", {"datetime": True})
            date_text = time_tag["datetime"].strip() if time_tag else ""

        items.append({
            "title": title,
            "href": href,
            "date_text": date_text,
            "source_url": source_url,
        })

    return items


def _get_next_divi_page_url(html: str) -> str | None:
    """Find the "next page" URL in a Divi theme paginated archive.

    Returns the href string, or None on the last page.
    """
    soup = BeautifulSoup(html, "lxml")

    pagination = soup.find("div", class_=re.compile(r"\bpagination\b"))
    if pagination:
        right_div = pagination.find("div", class_=re.compile(r"\balignright\b"))
        if right_div:
            a = right_div.find("a", href=True)
            if a and a["href"] and a["href"] != "#":
                return a["href"].strip()

    next_link = soup.find("a", class_=re.compile(r"\bnext\b.*page-numbers|page-numbers.*\bnext\b"))
    if next_link and next_link.get("href"):
        return next_link["href"].strip()

    return None


# ---------------------------------------------------------------------------
# Single post/page metadata extractor
# ---------------------------------------------------------------------------

def _extract_post_meta(html: str) -> dict:
    """Extract metadata from a Divi theme single post or page.

    Returns {"title": str, "published_at": str}
    """
    soup = BeautifulSoup(html, "lxml")

    # -- Title --
    title = ""

    h1 = soup.find("h1", class_=re.compile(r"entry-title|post-title|page-title"))
    if h1:
        title = h1.get_text(strip=True)

    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            raw = og_title["content"].strip()
            title = raw.split("|")[0].strip() if "|" in raw else raw.split("\u2013")[0].strip()

    if not title:
        title_tag = soup.find("title")
        if title_tag:
            raw = title_tag.get_text(strip=True)
            title = raw.split("|")[0].strip() if "|" in raw else raw.split("\u2013")[0].strip()

    # -- Published date --
    published_at = ""

    # 1. <meta property="article:published_time">
    meta_pub = soup.find("meta", property="article:published_time")
    if meta_pub and meta_pub.get("content"):
        published_at = parse_iso_date(meta_pub["content"])

    # 2. <time class="entry-date published" datetime="...">
    if not published_at:
        time_tag = soup.find(
            "time",
            class_=re.compile(r"entry-date.*published|published.*entry-date"),
        )
        if not time_tag:
            time_tag = soup.find("time", class_=re.compile(r"\bpublished\b"))
        if time_tag and time_tag.get("datetime"):
            published_at = parse_iso_date(time_tag["datetime"])

    # 3. <span class="published"> (Divi post-meta, English date text)
    if not published_at:
        pub_span = soup.find("span", class_=re.compile(r"\bpublished\b"))
        if pub_span:
            published_at = parse_malay_date(pub_span.get_text(strip=True))

    # 4. <time class="updated"> as last resort
    if not published_at:
        updated_tag = soup.find("time", class_=re.compile(r"\bupdated\b"))
        if updated_tag and updated_tag.get("datetime"):
            published_at = parse_iso_date(updated_tag["datetime"])

    return {"title": title, "published_at": published_at}


# ---------------------------------------------------------------------------
# WP Download Manager (wpdmpro) page metadata extractor
# ---------------------------------------------------------------------------

def _extract_wpdm_page_meta(html: str) -> dict:
    """Extract metadata from a WP Download Manager package page (/download/{slug}/).

    Returns {"title": str, "published_at": str, "description": str}
    """
    soup = BeautifulSoup(html, "lxml")

    # -- Title --
    title = ""
    h1 = soup.find("h1", class_=re.compile(r"entry-title|post-title"))
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            raw = og_title["content"].strip()
            title = raw.split("|")[0].strip() if "|" in raw else raw.split("\u2013")[0].strip()

    # -- Date from WPDM metadata widget --
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
                if "Create Date" in li_text or "Tarikh Cipta" in li_text:
                    published_at = parse_malay_date(badge_text)
                    if published_at:
                        break
                if not published_at and ("Last Updated" in li_text or "Tarikh Kemaskini" in li_text):
                    published_at = parse_malay_date(badge_text)

    if not published_at:
        pub_span = soup.find("span", class_=re.compile(r"\bpublished\b"))
        if pub_span:
            published_at = parse_malay_date(pub_span.get_text(strip=True))

    # -- Description --
    description = ""
    if w3eden:
        for col in w3eden.find_all("div", class_=re.compile(r"\bcol-md-12\b")):
            p = col.find("p")
            if p:
                description = p.get_text(strip=True)
                if description:
                    break

    return {"title": title, "published_at": published_at, "description": description}


def _is_wpdmpro_url(url: str) -> bool:
    """Heuristic: wpdmpro package pages live under /download/{slug}/."""
    path = urlparse(url).path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    return len(parts) >= 1 and parts[0] == "download"


# ---------------------------------------------------------------------------
# WPDM file link extractor
# ---------------------------------------------------------------------------

def _extract_wpdm_file_links(html: str, base_url: str) -> list[str]:
    """Extract file download links (a.inddl[href*=wpdmdl]) from a WPDM page.

    Returns a deduplicated list of absolute WPDM token URLs.
    """
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    links: list[str] = []

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

    return links


# ---------------------------------------------------------------------------
# Embedded document link extractor
# ---------------------------------------------------------------------------

def _extract_embedded_doc_links(html: str, base_url: str) -> list[DownloadLink]:
    """Find all document download links embedded in a post or page body.

    Finds both direct links to document files (.pdf, .doc, etc.) and
    WP Download Manager inddl redirect links (?wpdmdl=).
    """
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    links: list[DownloadLink] = []

    content_area = (
        soup.find("div", class_=re.compile(r"entry-content|post-content|article-body"))
        or soup
    )

    # Direct document links
    for a_tag in content_area.find_all("a", href=True):
        href = a_tag["href"].strip()
        lower = href.lower()
        if any(lower.endswith(ext) for ext in _DOC_EXTENSIONS):
            abs_url = make_absolute(href, base_url)
            if abs_url not in seen:
                seen.add(abs_url)
                label = a_tag.get_text(strip=True) or href
                links.append(DownloadLink(url=abs_url, label=label))

    # WPDM inddl links
    for a_tag in soup.find_all("a", class_=re.compile(r"\binddl\b"), href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith(("#", "javascript:")):
            continue
        if "wpdmdl" not in href:
            continue
        abs_url = make_absolute(href, base_url)
        if abs_url not in seen:
            seen.add(abs_url)
            label = a_tag.get_text(strip=True) or href
            links.append(DownloadLink(url=abs_url, label=label))

    return links


# ---------------------------------------------------------------------------
# Penyata Rasmi hub page (/pr/) extractor
# ---------------------------------------------------------------------------

def _extract_pr_hub(html: str, source_url: str) -> list[dict]:
    """Extract PDF entries from the /pr/ Penyata Rasmi hub page.

    Structure: h2 (Dewan level) > et_pb_accordion > et_pb_toggle (session) >
    h3 (meeting) + table (2-col: title | link).

    Returns list of dicts: {href, title, date_text, dewan_level, session, meeting, source_url}
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()
    current_dewan = ""

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

                content = toggle.find("div", class_=re.compile(r"\bet_pb_toggle_content\b"))
                if not content:
                    continue

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
                            if doc_title.lower() in ("tajuk", "title", ""):
                                continue

                            a = cells[-1].find("a", href=True)
                            if not a:
                                continue  # placeholder

                            href = a["href"].strip()
                            if not href.lower().endswith(".pdf"):
                                continue

                            abs_href = make_absolute(href, source_url)
                            if abs_href in seen:
                                continue
                            seen.add(abs_href)

                            items.append({
                                "href": abs_href,
                                "title": doc_title,
                                "date_text": parse_malay_date(doc_title),
                                "dewan_level": current_dewan,
                                "session": session,
                                "meeting": current_meeting,
                                "source_url": source_url,
                            })

    log.info("[dewan_johor] pr_hub extracted %d items from %s", len(items), source_url)
    return items


# ---------------------------------------------------------------------------
# Soalan & Jawapan Lisan hub page (/sdjl/, /sdjb/) extractor
# ---------------------------------------------------------------------------

def _extract_sdjl_hub(html: str, source_url: str) -> list[dict]:
    """Extract PDF entries from the Soalan & Jawapan Lisan/Bertulis hub page.

    Structure: et_pb_accordion > et_pb_toggle (session) > p>strong (meeting) +
    table (1-col: link text is the date).

    Returns list of dicts: {href, title, date_text, session, meeting, source_url}
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()

    for accordion in soup.find_all(
        "div",
        class_=lambda c: c and "et_pb_accordion" in c and "et_pb_module" in c,
    ):
        for toggle in accordion.find_all("div", class_=re.compile(r"\bet_pb_toggle\b")):
            h5 = toggle.find("h5", class_=re.compile(r"\bet_pb_toggle_title\b"))
            session = h5.get_text(strip=True) if h5 else ""

            content = toggle.find("div", class_=re.compile(r"\bet_pb_toggle_content\b"))
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
                        items.append({
                            "href": abs_href,
                            "title": link_text,
                            "date_text": parse_malay_date(link_text),
                            "session": session,
                            "meeting": current_meeting,
                            "source_url": source_url,
                        })

    log.info("[dewan_johor] sdjl_hub extracted %d items from %s", len(items), source_url)
    return items


# ---------------------------------------------------------------------------
# Rang Undang-Undang / Enakmen hub page extractor
# ---------------------------------------------------------------------------

def _extract_ruu_hub(html: str, source_url: str) -> list[dict]:
    """Extract PDF entries from the Rang Undang-Undang / Enakmen hub page.

    Structure: optional h2 (Dewan level) > et_pb_accordion > et_pb_toggle >
    p>strong (meeting) + 4-col table (Bil | Tarikh | Perkara | Muat Turun).

    Returns list of dicts: {href, title, date_text, dewan_level, session, meeting, source_url}
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()
    current_dewan = ""

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

                content = toggle.find("div", class_=re.compile(r"\bet_pb_toggle_content\b"))
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

                            first = cells[0].get_text(strip=True).lower().rstrip(".")
                            if first in _RUU_HEADER_CELLS:
                                continue

                            date_raw = cells[1].get_text(strip=True)
                            title = cells[2].get_text(strip=True)

                            a = cells[-1].find("a", href=True)
                            if not a:
                                continue  # placeholder

                            href = a["href"].strip()
                            if not href.lower().endswith(".pdf"):
                                continue

                            abs_href = make_absolute(href, source_url)
                            if abs_href in seen:
                                continue
                            seen.add(abs_href)

                            items.append({
                                "href": abs_href,
                                "title": title,
                                "date_text": parse_malay_date(date_raw),
                                "dewan_level": current_dewan,
                                "session": session,
                                "meeting": current_meeting,
                                "source_url": source_url,
                            })

    log.info("[dewan_johor] ruu_hub extracted %d items from %s", len(items), source_url)
    return items


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@register_adapter
class DewanJohorAdapter(BaseSiteAdapter):
    """Adapter for dewannegeri.johor.gov.my (WordPress + Divi + WPDM)."""

    slug = "dewan_johor"
    agency = "Dewan Negeri Johor"
    requires_browser = False

    @property
    def _base_url(self) -> str:
        return self.config.get("base_url", _BASE_URL)

    @property
    def _sections(self) -> list[dict]:
        return self.config.get("sections", [])

    # ------------------------------------------------------------------
    # discover()
    # ------------------------------------------------------------------

    def discover(
        self, since: date | None = None, max_pages: int = 0
    ) -> Iterable[DiscoveredItem]:
        """Yield DiscoveredItems from all configured sections.

        Dispatches to the appropriate discovery method based on the section's
        source_type: sitemap, listing, pr_hub, sdjl_hub, or ruu_hub.
        """
        for section in self._sections:
            source_type = section.get("source_type", "listing")
            doc_type = section.get("doc_type", "other")
            language = section.get("language", "ms")
            section_name = section.get("name", "unknown")

            if source_type == "sitemap":
                sitemap_url = section.get("sitemap_url", "")
                if not sitemap_url:
                    log.warning("[dewan_johor:%s] Missing sitemap_url", section_name)
                    continue
                yield from self._discover_from_sitemap(
                    sitemap_url, doc_type, language, section_name, since,
                )

            elif source_type == "listing":
                listing_pages = section.get("listing_pages", [])
                if not listing_pages:
                    listing_url = section.get("listing_url", "")
                    if listing_url:
                        listing_pages = [{"url": listing_url}]
                if not listing_pages:
                    log.warning("[dewan_johor:%s] Missing listing_pages/listing_url", section_name)
                    continue
                yield from self._discover_from_listing(
                    listing_pages, doc_type, language, section_name, since, max_pages,
                )

            elif source_type == "pr_hub":
                hub_url = section.get("hub_url", "")
                if not hub_url:
                    log.warning("[dewan_johor:%s] Missing hub_url", section_name)
                    continue
                yield from self._discover_from_pr_hub(
                    hub_url, doc_type, language, section_name, since,
                )

            elif source_type == "sdjl_hub":
                hub_url = section.get("hub_url", "")
                if not hub_url:
                    log.warning("[dewan_johor:%s] Missing hub_url", section_name)
                    continue
                yield from self._discover_from_sdjl_hub(
                    hub_url, doc_type, language, section_name, since,
                )

            elif source_type == "ruu_hub":
                hub_url = section.get("hub_url", "")
                if not hub_url:
                    log.warning("[dewan_johor:%s] Missing hub_url", section_name)
                    continue
                yield from self._discover_from_ruu_hub(
                    hub_url, doc_type, language, section_name, since,
                )

            else:
                log.warning(
                    "[dewan_johor:%s] Unknown source_type %r", section_name, source_type,
                )

    # ------------------------------------------------------------------
    # Discovery: Sitemap
    # ------------------------------------------------------------------

    def _discover_from_sitemap(
        self,
        sitemap_url: str,
        doc_type: str,
        language: str,
        section_name: str,
        since: date | None,
    ) -> Iterable[DiscoveredItem]:
        """Fetch a sitemap (or sitemap index) and yield DiscoveredItems.

        Recursively follows child sitemaps in a sitemap index.
        """
        log.info("[dewan_johor:%s] Fetching sitemap %s", section_name, sitemap_url)

        try:
            resp = self.http.get(sitemap_url)
        except Exception as exc:
            log.error("[dewan_johor:%s] Failed to fetch sitemap %s: %s", section_name, sitemap_url, exc)
            return

        entries = _parse_sitemap_xml(resp.text)

        for entry in entries:
            if entry.get("is_sitemap_index"):
                # Recurse into child sitemap
                yield from self._discover_from_sitemap(
                    entry["url"], doc_type, language, section_name, since,
                )
            else:
                url = entry["url"]
                lastmod = entry.get("lastmod", "")
                pub_date = parse_iso_date(lastmod) if lastmod else ""

                # Apply --since filter using lastmod
                if since and pub_date:
                    try:
                        if date.fromisoformat(pub_date) < since:
                            continue
                    except ValueError:
                        pass

                yield DiscoveredItem(
                    source_url=url,
                    title="",
                    published_at=pub_date,
                    doc_type=doc_type,
                    language=language,
                    metadata={
                        "section": section_name,
                        "source_type": "sitemap",
                        "sitemap_url": sitemap_url,
                        "lastmod": lastmod,
                    },
                )

    # ------------------------------------------------------------------
    # Discovery: Divi listing pages with pagination
    # ------------------------------------------------------------------

    def _discover_from_listing(
        self,
        listing_pages: list[dict],
        doc_type: str,
        language: str,
        section_name: str,
        since: date | None,
        max_pages: int,
    ) -> Iterable[DiscoveredItem]:
        """Walk paginated Divi archive pages and yield DiscoveredItems.

        Pagination follows the Divi pattern: div.pagination > div.alignright > a.
        """
        pages_fetched = 0

        for listing_cfg in listing_pages:
            current_url: str | None = listing_cfg["url"]

            while current_url:
                if max_pages and pages_fetched >= max_pages:
                    log.info("[dewan_johor:%s] max_pages=%d reached", section_name, max_pages)
                    return

                log.info("[dewan_johor:%s] Fetching listing %s", section_name, current_url)

                try:
                    resp = self.http.get(current_url)
                except Exception as exc:
                    log.error(
                        "[dewan_johor:%s] Failed to fetch listing %s: %s",
                        section_name, current_url, exc,
                    )
                    break

                pages_fetched += 1
                items = _extract_divi_listing(resp.text, current_url)

                for item in items:
                    article_url = make_absolute(item["href"], self._base_url)
                    date_text = item.get("date_text", "")
                    pub_date = parse_malay_date(date_text) if date_text else ""

                    if since and pub_date:
                        try:
                            if date.fromisoformat(pub_date) < since:
                                continue
                        except ValueError:
                            pass

                    yield DiscoveredItem(
                        source_url=article_url,
                        title=item.get("title", ""),
                        published_at=pub_date,
                        doc_type=doc_type,
                        language=language,
                        metadata={
                            "section": section_name,
                            "source_type": "listing",
                            "listing_page_url": current_url,
                            "date_text": date_text,
                        },
                    )

                current_url = _get_next_divi_page_url(resp.text)

    # ------------------------------------------------------------------
    # Discovery: Penyata Rasmi hub (/pr/)
    # ------------------------------------------------------------------

    def _discover_from_pr_hub(
        self,
        hub_url: str,
        doc_type: str,
        language: str,
        section_name: str,
        since: date | None,
    ) -> Iterable[DiscoveredItem]:
        """Fetch the /pr/ hub page and yield one DiscoveredItem per PDF."""
        log.info("[dewan_johor:%s] Fetching PR hub %s", section_name, hub_url)

        try:
            resp = self.http.get(hub_url)
        except Exception as exc:
            log.error("[dewan_johor:%s] Failed to fetch PR hub %s: %s", section_name, hub_url, exc)
            return

        entries = _extract_pr_hub(resp.text, hub_url)

        for entry in entries:
            pub_date = entry.get("date_text", "")

            if since and pub_date:
                try:
                    if date.fromisoformat(pub_date) < since:
                        continue
                except ValueError:
                    pass

            yield DiscoveredItem(
                source_url=entry["href"],
                title=entry["title"],
                published_at=pub_date,
                doc_type=doc_type,
                language=language,
                metadata={
                    "section": section_name,
                    "source_type": "pr_hub",
                    "hub_url": hub_url,
                    "dewan_level": entry.get("dewan_level", ""),
                    "session": entry.get("session", ""),
                    "meeting": entry.get("meeting", ""),
                    "_direct_file": True,
                },
            )

    # ------------------------------------------------------------------
    # Discovery: Soalan & Jawapan Lisan/Bertulis hub (/sdjl/, /sdjb/)
    # ------------------------------------------------------------------

    def _discover_from_sdjl_hub(
        self,
        hub_url: str,
        doc_type: str,
        language: str,
        section_name: str,
        since: date | None,
    ) -> Iterable[DiscoveredItem]:
        """Fetch the /sdjl/ or /sdjb/ hub page and yield one DiscoveredItem per PDF."""
        log.info("[dewan_johor:%s] Fetching SDJL hub %s", section_name, hub_url)

        try:
            resp = self.http.get(hub_url)
        except Exception as exc:
            log.error("[dewan_johor:%s] Failed to fetch SDJL hub %s: %s", section_name, hub_url, exc)
            return

        entries = _extract_sdjl_hub(resp.text, hub_url)

        for entry in entries:
            pub_date = entry.get("date_text", "")

            if since and pub_date:
                try:
                    if date.fromisoformat(pub_date) < since:
                        continue
                except ValueError:
                    pass

            yield DiscoveredItem(
                source_url=entry["href"],
                title=entry["title"],
                published_at=pub_date,
                doc_type=doc_type,
                language=language,
                metadata={
                    "section": section_name,
                    "source_type": "sdjl_hub",
                    "hub_url": hub_url,
                    "session": entry.get("session", ""),
                    "meeting": entry.get("meeting", ""),
                    "_direct_file": True,
                },
            )

    # ------------------------------------------------------------------
    # Discovery: Rang Undang-Undang / Enakmen hub
    # ------------------------------------------------------------------

    def _discover_from_ruu_hub(
        self,
        hub_url: str,
        doc_type: str,
        language: str,
        section_name: str,
        since: date | None,
    ) -> Iterable[DiscoveredItem]:
        """Fetch the /rang-undang-undang-enakmen/ hub and yield PDF DiscoveredItems."""
        log.info("[dewan_johor:%s] Fetching RUU hub %s", section_name, hub_url)

        try:
            resp = self.http.get(hub_url)
        except Exception as exc:
            log.error("[dewan_johor:%s] Failed to fetch RUU hub %s: %s", section_name, hub_url, exc)
            return

        entries = _extract_ruu_hub(resp.text, hub_url)

        for entry in entries:
            pub_date = entry.get("date_text", "")

            if since and pub_date:
                try:
                    if date.fromisoformat(pub_date) < since:
                        continue
                except ValueError:
                    pass

            yield DiscoveredItem(
                source_url=entry["href"],
                title=entry["title"],
                published_at=pub_date,
                doc_type=doc_type,
                language=language,
                metadata={
                    "section": section_name,
                    "source_type": "ruu_hub",
                    "hub_url": hub_url,
                    "dewan_level": entry.get("dewan_level", ""),
                    "session": entry.get("session", ""),
                    "meeting": entry.get("meeting", ""),
                    "_direct_file": True,
                },
            )

    # ------------------------------------------------------------------
    # fetch_and_extract()
    # ------------------------------------------------------------------

    def fetch_and_extract(self, item: DiscoveredItem) -> Iterable[DocumentCandidate]:
        """Fetch a discovered item and extract downloadable documents.

        Handles three cases:

        1. Direct file URLs (from hub pages): yield a single DocumentCandidate
           pointing at the PDF URL — no HTML fetch needed.

        2. WPDM package pages (/download/{slug}/): fetch the HTML, extract
           metadata, yield the HTML page itself, then yield each WPDM inddl
           download token URL.  The runner will follow the redirect to the
           actual file.

        3. Standard Divi post pages: fetch the HTML, extract metadata, yield
           the HTML page, then yield any embedded document links found in
           the article body.
        """
        is_direct_file = item.metadata.get("_direct_file", False)

        # Case 1: Direct file URL (hub pages yield direct PDF links)
        if is_direct_file:
            ct = guess_content_type(item.source_url)
            yield DocumentCandidate(
                url=item.source_url,
                source_page_url=item.metadata.get("hub_url", item.source_url),
                title=item.title,
                published_at=item.published_at,
                doc_type=item.doc_type,
                content_type=ct,
                language=item.language,
            )
            return

        # Check if the URL is itself a direct document link
        url_lower = item.source_url.lower().split("?")[0]
        if any(url_lower.endswith(ext) for ext in _DOC_EXTENSIONS):
            ct = guess_content_type(item.source_url)
            yield DocumentCandidate(
                url=item.source_url,
                source_page_url=item.metadata.get("listing_page_url", item.source_url),
                title=item.title,
                published_at=item.published_at,
                doc_type=item.doc_type,
                content_type=ct,
                language=item.language,
            )
            return

        # Fetch the article/package HTML
        try:
            resp = self.http.get(item.source_url)
            html = resp.text
        except Exception as e:
            log.warning("[dewan_johor] Failed to fetch %s: %s", item.source_url, e)
            return

        is_wpdm = _is_wpdmpro_url(item.source_url)

        # Case 2: WPDM package page
        if is_wpdm:
            meta = _extract_wpdm_page_meta(html)
            title = meta.get("title") or item.title
            published_at = meta.get("published_at") or item.published_at

            # Fallback: listing date_text
            if not published_at:
                date_text = item.metadata.get("date_text", "")
                if date_text:
                    published_at = parse_malay_date(date_text)

            # Yield the HTML package page itself
            yield DocumentCandidate(
                url=item.source_url,
                source_page_url=item.metadata.get("listing_page_url", item.source_url),
                title=title,
                published_at=published_at,
                doc_type=item.doc_type,
                content_type="text/html",
                language=item.language,
            )

            # Yield WPDM download token URLs (a.inddl[href*=wpdmdl])
            # The runner resolves the redirect; we pass the token URL here.
            wpdm_links = _extract_wpdm_file_links(html, self._base_url)
            for token_url in wpdm_links:
                yield DocumentCandidate(
                    url=token_url,
                    source_page_url=item.source_url,
                    title=title,
                    published_at=published_at,
                    doc_type=item.doc_type,
                    content_type="",  # unknown until redirect followed
                    language=item.language,
                )

            # Also yield any direct doc links (some WPDM pages embed .pdf hrefs too)
            embedded = _extract_embedded_doc_links(html, self._base_url)
            seen_urls = set(wpdm_links)
            for dl in embedded:
                if dl.url not in seen_urls:
                    seen_urls.add(dl.url)
                    ct = guess_content_type(dl.url) if dl.url else ""
                    yield DocumentCandidate(
                        url=dl.url,
                        source_page_url=item.source_url,
                        title=title,
                        published_at=published_at,
                        doc_type=item.doc_type,
                        content_type=ct,
                        language=item.language,
                    )
            return

        # Case 3: Standard Divi post page
        meta = _extract_post_meta(html)
        title = meta.get("title") or item.title
        published_at = meta.get("published_at") or item.published_at

        # Fallback: listing date_text
        if not published_at:
            date_text = item.metadata.get("date_text", "")
            if date_text:
                published_at = parse_malay_date(date_text)

        # Yield the HTML article page itself
        yield DocumentCandidate(
            url=item.source_url,
            source_page_url=item.metadata.get("listing_page_url", item.source_url),
            title=title,
            published_at=published_at,
            doc_type=item.doc_type,
            content_type="text/html",
            language=item.language,
        )

        # Yield embedded document links from the article body
        embedded = _extract_embedded_doc_links(html, self._base_url)
        for dl in embedded:
            ct = guess_content_type(dl.url) if dl.url else ""
            yield DocumentCandidate(
                url=dl.url,
                source_page_url=item.source_url,
                title=title,
                published_at=published_at,
                doc_type=item.doc_type,
                content_type=ct,
                language=item.language,
            )

    # ------------------------------------------------------------------
    # extract_downloads() — override for WPDM-aware link extraction
    # ------------------------------------------------------------------

    def extract_downloads(self, html: str, base_url: str) -> list[DownloadLink]:
        """Extract download links with WPDM-aware logic.

        In addition to the default document link scanner, also picks up
        a.inddl[href*=wpdmdl] redirect URLs.
        """
        embedded = _extract_embedded_doc_links(html, base_url)
        if embedded:
            return embedded
        return extract_document_links(html, base_url)
