"""MCMC adapter — Kentico ASP.NET, Bootstrap pagination."""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Iterable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from polisi_scraper.adapters.base import BaseSiteAdapter, DiscoveredItem, DocumentCandidate
from polisi_scraper.adapters.registry import register_adapter
from polisi_scraper.core.dates import parse_malay_date
from polisi_scraper.core.extractors import DownloadLink, extract_document_links
from polisi_scraper.core.urls import canonical_url, guess_content_type, make_absolute

log = logging.getLogger(__name__)

BASE_URL = "https://mcmc.gov.my"

_DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")


# ---------------------------------------------------------------------------
# HTML extraction helpers (ported from specific-scrapers/mcmc-scraper)
# ---------------------------------------------------------------------------


def _parse_mcmc_date(date_str: str) -> str:
    """Parse MCMC English date strings into ISO 8601 dates.

    Handles formats like "MAR 03, 2026", "03 Mar 2026", "January 15, 2025".
    Falls back to parse_malay_date which handles Malay month names too.
    """
    if not date_str or not date_str.strip():
        return ""
    return parse_malay_date(date_str.strip())


def _extract_article_list_items(html: str, source_url: str) -> list[dict]:
    """Extract article links from an MCMC article-list-box listing page.

    Used for: Press Releases, Announcements, Press Clippings.

    Returns list of dicts with keys: title, href, date_text, pdf_href, source_url.
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

        items.append({
            "title": title,
            "href": href,
            "date_text": date_text,
            "pdf_href": pdf_href,
            "source_url": source_url,
        })

    log.info(f"[mcmc] article_list extracted {len(items)} items from {source_url}")
    return items


def _extract_media_box_items(html: str, source_url: str) -> list[dict]:
    """Extract items from an MCMC media-box grid listing page.

    Used for: Publications, Reports, Guidelines, Annual Reports, Statistics.

    Returns list of dicts with keys: title, href, date_text, pdf_href, source_url.
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

        items.append({
            "title": title,
            "href": href,
            "date_text": "",
            "pdf_href": "",
            "source_url": source_url,
        })

    log.info(f"[mcmc] media_box extracted {len(items)} items from {source_url}")
    return items


def _get_next_page_number(html: str) -> Optional[int]:
    """Detect the next page number from MCMC Bootstrap pagination.

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
        try:
            page_num = int(a.get_text(strip=True))
        except ValueError:
            continue
        if page_num == next_page:
            return next_page

    # Ellipsis / windowed pagination: an enabled "next" button pointing
    # to a page after the current one means there are more pages.
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
        try:
            int(text)
            continue  # skip numeric page links already checked above
        except ValueError:
            pass
        # Non-numeric link (prev/next icons); verify it points after current page
        if "page=" in href:
            try:
                target = int(href.split("page=")[-1].split("&")[0].split("#")[0])
                if target > current_page:
                    return next_page
            except ValueError:
                pass

    return None


def _extract_acts_hub_items(html: str, source_url: str) -> list[dict]:
    """Extract individual Acts from the /en/legal/acts hub page.

    Each Act has an <h2> title followed by sibling anchors for detail pages
    and direct PDF/DOC links.

    Returns list of dicts with keys: title, detail_href, doc_hrefs, source_url.
    """
    soup = BeautifulSoup(html, "lxml")

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

            anchors = (
                sibling.find_all("a", href=True)
                if hasattr(sibling, "find_all")
                else []
            )
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
            items.append({
                "title": title,
                "detail_href": detail_href,
                "doc_hrefs": doc_hrefs,
                "source_url": source_url,
            })

    log.info(f"[mcmc] acts_hub extracted {len(items)} items from {source_url}")
    return items


def _extract_article_meta(html: str, source_url: str) -> dict:
    """Extract metadata (title, published_at) from a single MCMC detail page."""
    soup = BeautifulSoup(html, "lxml")

    # Title
    title = ""
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
            for sep in (" | ", " - ", " – "):
                if sep in raw:
                    title = raw.split(sep)[0].strip()
                    break
            else:
                title = raw

    # Published date
    published_at = ""
    date_div = soup.find("div", class_="date")
    if date_div:
        published_at = _parse_mcmc_date(date_div.get_text(strip=True))

    if not published_at:
        meta_pub = soup.find("meta", property="article:published_time")
        if meta_pub and meta_pub.get("content"):
            published_at = _parse_mcmc_date(meta_pub["content"])

    if not published_at:
        for meta_name in ("date", "DC.date", "dc.date"):
            meta_date = soup.find("meta", attrs={"name": meta_name})
            if meta_date and meta_date.get("content"):
                published_at = _parse_mcmc_date(meta_date["content"])
                if published_at:
                    break

    return {"title": title, "published_at": published_at}


def _extract_embedded_doc_links(html: str, base_url: str) -> list[str]:
    """Find all document download links embedded in an MCMC article page.

    Captures direct document extension links, /getattachment/ links (Kentico
    ASP.NET pattern), and PDF download buttons.
    """
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

    # Also capture PDF download buttons outside the main content
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


def _build_listing_url(base: str, page: int) -> str:
    """Append ?page=N (or &page=N if query string already present)."""
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}page={page}"


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@register_adapter
class McmcAdapter(BaseSiteAdapter):
    slug = "mcmc"
    agency = "Suruhanjaya Komunikasi dan Multimedia Malaysia (MCMC)"
    requires_browser = False

    def _base_url(self) -> str:
        return self.config.get("base_url", BASE_URL)

    # --- discover() ---------------------------------------------------------

    def discover(self, since: date | None = None, max_pages: int = 0) -> Iterable[DiscoveredItem]:
        """Walk all configured sections and yield DiscoveredItems.

        Sections are declared in the adapter config (mirroring mcmc.yaml):
          - listing sections (article_list / media_box) with Bootstrap pagination
          - acts_hub section (single non-paginated hub page)
          - static_page section (single content page)
        """
        sections = self.config.get("sections", [])

        for section in sections:
            source_type = section.get("source_type", "listing")
            doc_type = section.get("doc_type", "other")
            language = section.get("language", "en")

            if source_type == "acts_hub":
                hub_url = section.get("hub_url", "")
                if not hub_url:
                    log.warning(f"[mcmc] Section {section.get('name')} missing hub_url")
                    continue
                yield from self._discover_acts_hub(hub_url, doc_type, language, since)

            elif source_type == "static_page":
                page_url = section.get("page_url", "")
                if not page_url:
                    log.warning(f"[mcmc] Section {section.get('name')} missing page_url")
                    continue
                yield from self._discover_static_page(page_url, doc_type, language)

            else:  # "listing" (default) — paginated article_list / media_box
                listing_url = section.get("listing_url", "")
                if not listing_url:
                    log.warning(f"[mcmc] Section {section.get('name')} missing listing_url")
                    continue
                archetype = section.get("listing_archetype", "article_list")
                yield from self._discover_listing(
                    listing_url, archetype, doc_type, language, since, max_pages,
                )

    # --- Listing page discovery (article_list / media_box) ------------------

    def _discover_listing(
        self,
        listing_url: str,
        archetype: str,
        doc_type: str,
        language: str,
        since: date | None,
        max_pages: int,
    ) -> Iterable[DiscoveredItem]:
        page = 1
        pages_fetched = 0

        while True:
            if max_pages and pages_fetched >= max_pages:
                log.info(f"[mcmc] max_pages={max_pages} reached for {listing_url}")
                return

            current_url = _build_listing_url(listing_url, page)
            log.info(f"[mcmc] Fetching listing {current_url} (archetype={archetype})")

            try:
                resp = self.http.get(current_url)
            except Exception as exc:
                log.error(f"[mcmc] Failed to fetch listing {current_url}: {exc}")
                break

            pages_fetched += 1
            html = resp.text

            if archetype == "media_box":
                items = _extract_media_box_items(html, current_url)
            else:
                items = _extract_article_list_items(html, current_url)

            if not items:
                log.info(f"[mcmc] Empty listing page, stopping: {current_url}")
                break

            for item in items:
                # Early date filter using listing-page date
                date_text = item.get("date_text", "")
                published_at = _parse_mcmc_date(date_text) if date_text else ""

                if since and published_at:
                    try:
                        if date.fromisoformat(published_at) < since:
                            continue
                    except ValueError:
                        pass

                href = make_absolute(item["href"], self._base_url())

                yield DiscoveredItem(
                    source_url=href,
                    title=item.get("title", ""),
                    published_at=published_at,
                    doc_type=doc_type,
                    language=language,
                    metadata={
                        "listing_url": current_url,
                        "date_text": date_text,
                        "pdf_href": item.get("pdf_href", ""),
                        "archetype": archetype,
                    },
                )

            # Detect next page via Bootstrap pagination
            next_page_num = _get_next_page_number(html)
            if next_page_num is None:
                log.info(f"[mcmc] Last pagination page: {current_url}")
                break
            page = next_page_num

    # --- Acts hub discovery -------------------------------------------------

    def _discover_acts_hub(
        self,
        hub_url: str,
        doc_type: str,
        language: str,
        since: date | None,
    ) -> Iterable[DiscoveredItem]:
        can_hub = canonical_url(hub_url)
        log.info(f"[mcmc] Fetching acts hub: {can_hub}")

        try:
            resp = self.http.get(can_hub)
        except Exception as exc:
            log.error(f"[mcmc] Failed to fetch acts hub {can_hub}: {exc}")
            return

        items = _extract_acts_hub_items(resp.text, can_hub)

        for item in items:
            # Yield the detail page
            if item["detail_href"]:
                detail_url = make_absolute(item["detail_href"], self._base_url())
                yield DiscoveredItem(
                    source_url=detail_url,
                    title=item["title"],
                    published_at="",
                    doc_type=doc_type,
                    language=language,
                    metadata={
                        "listing_url": can_hub,
                        "source_type": "acts_hub",
                        "archetype": "acts_hub",
                    },
                )

            # Yield each direct document found on the hub row
            for doc_href in item.get("doc_hrefs", []):
                doc_url = make_absolute(doc_href, self._base_url())
                yield DiscoveredItem(
                    source_url=doc_url,
                    title=item["title"],
                    published_at="",
                    doc_type=doc_type,
                    language=language,
                    metadata={
                        "listing_url": can_hub,
                        "source_type": "acts_hub_doc",
                        "archetype": "acts_hub",
                    },
                )

    # --- Static page discovery ----------------------------------------------

    def _discover_static_page(
        self,
        page_url: str,
        doc_type: str,
        language: str,
    ) -> Iterable[DiscoveredItem]:
        log.info(f"[mcmc] Queuing static page: {page_url}")
        yield DiscoveredItem(
            source_url=canonical_url(page_url),
            title="",  # will be extracted when the page is fetched
            published_at="",
            doc_type=doc_type,
            language=language,
            metadata={
                "source_type": "static_page",
                "archetype": "static_page",
            },
        )

    # --- fetch_and_extract() ------------------------------------------------

    def fetch_and_extract(self, item: DiscoveredItem) -> Iterable[DocumentCandidate]:
        """Fetch detail page, extract metadata, and yield document candidates.

        Handles three cases:
        1. Direct document URL (PDF/DOC) — yield as-is without HTML fetch.
        2. HTML detail page — yield the page itself + embedded document links.
        3. Listing-row PDF — if metadata carries a pdf_href, yield it too.
        """
        url = item.source_url
        url_lower = url.lower().split("?")[0]

        # Case 1: Direct document URL (e.g. from acts hub doc_hrefs)
        if any(url_lower.endswith(ext) for ext in _DOC_EXTENSIONS) or "/getattachment/" in url_lower:
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

        # Case 2: HTML page — fetch, extract metadata, yield page + embedded docs
        try:
            resp = self.http.get(url)
            html = resp.text
        except Exception as e:
            log.warning(f"[mcmc] Failed to fetch {url}: {e}")
            return

        meta = _extract_article_meta(html, url)
        title = meta.get("title") or item.title
        published_at = meta.get("published_at") or item.published_at

        # Fallback: use date_text from listing metadata
        if not published_at:
            date_text = item.metadata.get("date_text", "")
            if date_text:
                published_at = _parse_mcmc_date(date_text)

        # Yield the HTML page itself
        yield DocumentCandidate(
            url=url,
            source_page_url=item.metadata.get("listing_url", url),
            title=title,
            published_at=published_at,
            doc_type=item.doc_type,
            content_type="text/html",
            language=item.language,
        )

        # Case 3: Direct PDF link from the listing row (article_list archetype)
        pdf_href = item.metadata.get("pdf_href", "")
        if pdf_href:
            pdf_url = make_absolute(pdf_href, self._base_url())
            ct = guess_content_type(pdf_url)
            yield DocumentCandidate(
                url=pdf_url,
                source_page_url=url,
                title=title,
                published_at=published_at,
                doc_type=item.doc_type,
                content_type=ct,
                language=item.language,
            )

        # Extract embedded document links from the page
        embedded_urls = _extract_embedded_doc_links(html, self._base_url())
        for doc_url in embedded_urls:
            ct = guess_content_type(doc_url)
            yield DocumentCandidate(
                url=doc_url,
                source_page_url=url,
                title=title,
                published_at=published_at,
                doc_type=item.doc_type,
                content_type=ct,
                language=item.language,
            )

    # --- extract_downloads() override ---------------------------------------

    def extract_downloads(self, html: str, base_url: str) -> list[DownloadLink]:
        """Extract downloadable document links from an MCMC HTML page.

        Combines the generic extractor with MCMC-specific /getattachment/ handling.
        """
        # Start with the generic extractor (handles /getattachment/ already)
        links = extract_document_links(html, base_url)

        # Also pick up MCMC-specific embedded doc links that the generic
        # extractor might miss (e.g. button-styled downloads outside content area)
        seen_urls = {dl.url for dl in links}
        for doc_url in _extract_embedded_doc_links(html, base_url):
            if doc_url not in seen_urls:
                seen_urls.add(doc_url)
                links.append(DownloadLink(url=doc_url, label="MCMC embedded doc"))

        return links
