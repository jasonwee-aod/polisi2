"""MOH adapter — Joomla 4, offset pagination (?start=N)."""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from polisi_scraper.adapters.base import BaseSiteAdapter, DiscoveredItem, DocumentCandidate
from polisi_scraper.adapters.registry import register_adapter
from polisi_scraper.core.dates import parse_malay_date
from polisi_scraper.core.urls import canonical_url, guess_content_type
from polisi_scraper.core.extractors import extract_document_links, DownloadLink

log = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 10
_BASE_URL = "https://www.moh.gov.my"


# ---------------------------------------------------------------------------
# Joomla 4 HTML helpers
# ---------------------------------------------------------------------------

def _build_listing_url(base: str, offset: int) -> str:
    """Append Joomla offset parameter (?start=N) to a listing URL.

    Returns the base URL unchanged when *offset* is 0.
    """
    if offset == 0:
        return base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}start={offset}"


def _get_listing_urls(section: dict) -> list[str]:
    """Return all seed listing URLs for a section.

    Supports three config forms:
      1. listing_url: "https://..."             - single URL
      2. listing_urls: [...]                    - explicit list
      3. listing_url_template: "...{year}..."   - generated from year_from..year_to
         (years are yielded newest-first so incremental --since works well)
    """
    # Form 3: year-range template
    template = section.get("listing_url_template", "")
    if template:
        year_from = int(section.get("year_from", 2020))
        year_to = int(section.get("year_to", 2026))
        return [template.format(year=y) for y in range(year_to, year_from - 1, -1)]

    # Form 2: explicit list
    urls = section.get("listing_urls", [])
    if urls:
        return list(urls)

    # Form 1: single URL
    single = section.get("listing_url", "")
    return [single] if single else []


def _extract_joomla_listing_items(html: str, source_url: str) -> list[dict]:
    """Extract article rows from a Joomla 4 com_content category table page.

    Returns list of dicts with keys: title, href, date_text, source_url.
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen_hrefs: set[str] = set()

    table = soup.find("table", class_=re.compile(r"\bcom-content-category__table\b"))
    if not table:
        log.debug(f"[moh] No listing table found on {source_url}")
        return []

    tbody = table.find("tbody")
    if not tbody:
        return []

    for tr in tbody.find_all("tr"):
        a_tag = tr.find("a", href=True)
        if not a_tag:
            continue

        href = a_tag["href"].strip()
        if href in seen_hrefs or href.startswith(("javascript:", "#", "mailto:")):
            continue
        seen_hrefs.add(href)

        title = a_tag.get_text(strip=True)

        # Date: td whose class contains "list-date"
        date_td = tr.find("td", class_=re.compile(r"\blist-date\b"))
        date_text = date_td.get_text(strip=True) if date_td else ""

        items.append({
            "title": title,
            "href": href,
            "date_text": date_text,
            "source_url": source_url,
        })

    log.info(f"[moh] Extracted {len(items)} items from {source_url}")
    return items


def _has_more_pages(html: str, current_offset: int) -> bool:
    """Check whether the Joomla 4 pagination widget has a page beyond *current_offset*.

    Returns True if any pagination link has a ``start=`` value greater than
    *current_offset*.
    """
    soup = BeautifulSoup(html, "lxml")
    pag = soup.find("div", class_=re.compile(r"\bcom-content-category__pagination\b"))
    if not pag:
        return False

    for a in pag.find_all("a", href=True):
        href = a["href"]
        if "start=" in href:
            try:
                raw = href.split("start=")[1].split("&")[0].split("#")[0]
                val = int(raw)
                if val > current_offset:
                    return True
            except (ValueError, IndexError):
                pass

    return False


def _extract_article_meta(html: str) -> dict:
    """Extract title and published date from a Joomla 4 MOH article page.

    Returns ``{"title": str, "published_at": str}``.
    """
    soup = BeautifulSoup(html, "lxml")

    # -- Title --
    title = ""

    # 1. h1 with Joomla 4 microdata
    h1_micro = soup.find("h1", itemprop="headline")
    if h1_micro:
        title = h1_micro.get_text(strip=True)

    # 2. h1/h2 inside <article> or .item-page container
    if not title:
        container = (
            soup.find("article")
            or soup.find("div", class_=re.compile(r"\bitem-page\b"))
            or soup.find("div", class_=re.compile(r"\bcom-content-article\b"))
        )
        if container:
            h_tag = container.find(["h1", "h2"])
            if h_tag:
                title = h_tag.get_text(strip=True)

    # 3. og:title
    if not title:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()

    # 4. <title> tag -- strip common suffixes
    if not title:
        tag = soup.find("title")
        if tag:
            raw = tag.get_text(strip=True)
            for sep in (" | ", " - ", " \u2013 "):
                if sep in raw:
                    title = raw.split(sep)[0].strip()
                    break
            else:
                title = raw

    # -- Published date --
    published_at = ""

    # 1. time[itemprop="datePublished"] -- prefer datetime attribute
    time_pub = soup.find("time", itemprop="datePublished")
    if time_pub:
        dt_attr = time_pub.get("datetime", "")
        if dt_attr:
            published_at = parse_malay_date(dt_attr)
        if not published_at:
            published_at = parse_malay_date(time_pub.get_text(strip=True))

    # 2. time[itemprop="dateModified"] -- fallback
    if not published_at:
        time_mod = soup.find("time", itemprop="dateModified")
        if time_mod:
            dt_attr = time_mod.get("datetime", "")
            if dt_attr:
                published_at = parse_malay_date(dt_attr)

    # 3. article:published_time meta
    if not published_at:
        meta = soup.find("meta", property="article:published_time")
        if meta and meta.get("content"):
            published_at = parse_malay_date(meta["content"])

    return {"title": title, "published_at": published_at}


def _extract_embedded_doc_links(html: str, base_url: str) -> list[DownloadLink]:
    """Find document download links embedded in a MOH article body.

    Scopes to the article body container (itemprop="articleBody", <article>,
    .item-page) to avoid navigation noise, falling back to the full document.
    """
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    links: list[DownloadLink] = []

    doc_extensions = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")

    # Scope to article body
    content = (
        soup.find(itemprop="articleBody")
        or soup.find(attrs={"itemprop": "articleBody"})
        or soup.find("article")
        or soup.find("div", class_=re.compile(r"\bitem-page\b"))
        or soup
    )

    for a_tag in content.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue

        href_lower = href.lower().split("?")[0]
        if any(href_lower.endswith(ext) for ext in doc_extensions):
            abs_url = urljoin(base_url, href)
            if abs_url not in seen:
                seen.add(abs_url)
                label = a_tag.get_text(strip=True) or href
                links.append(DownloadLink(url=abs_url, label=label))

    return links


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@register_adapter
class MohAdapter(BaseSiteAdapter):
    slug = "moh"
    agency = "Kementerian Kesihatan Malaysia (MOH)"
    requires_browser = False

    # -- HOOK 1: Discovery --------------------------------------------------

    def discover(self, since: date | None = None, max_pages: int = 0) -> Iterable[DiscoveredItem]:
        """Walk all configured sections, paginating with Joomla ?start=N offsets.

        For each section the adapter resolves seed URLs (supporting single URL,
        explicit list, and year-template forms), then paginates each seed until
        the listing is exhausted, the pagination widget shows no further pages,
        or *max_pages* is reached.
        """
        sections = self.config.get("sections", [])
        base_url = self.config.get("base_url", _BASE_URL)

        for section in sections:
            doc_type = section.get("doc_type", "other")
            language = section.get("language", "ms")
            page_size = int(section.get("page_size", _DEFAULT_PAGE_SIZE))
            section_name = section.get("name", "unknown")

            seed_urls = _get_listing_urls(section)
            if not seed_urls:
                log.warning(f"[moh] Section {section_name!r} has no listing URLs")
                continue

            for seed_url in seed_urls:
                yield from self._paginate_listing(
                    seed_url=seed_url,
                    base_url=base_url,
                    page_size=page_size,
                    doc_type=doc_type,
                    language=language,
                    section_name=section_name,
                    since=since,
                    max_pages=max_pages,
                )

    def _paginate_listing(
        self,
        seed_url: str,
        base_url: str,
        page_size: int,
        doc_type: str,
        language: str,
        section_name: str,
        since: date | None,
        max_pages: int,
    ) -> Iterable[DiscoveredItem]:
        """Paginate a single Joomla listing seed URL, yielding DiscoveredItems."""
        offset = 0
        pages_fetched = 0

        while True:
            if max_pages and pages_fetched >= max_pages:
                log.info(f"[moh] max_pages={max_pages} reached for {seed_url}")
                return

            current_url = _build_listing_url(seed_url, offset)
            log.info(f"[moh] Fetching listing {current_url} (offset={offset})")

            try:
                resp = self.http.get(current_url)
            except Exception as exc:
                log.error(f"[moh] Failed to fetch listing {current_url}: {exc}")
                break

            html = resp.text
            items = _extract_joomla_listing_items(html, current_url)

            if not items:
                log.info(f"[moh] Empty listing page, stopping: {current_url}")
                break

            pages_fetched += 1

            for item in items:
                # Resolve absolute URL
                article_url = urljoin(base_url, item["href"])

                # Parse listing date for early --since filtering
                pub_date = parse_malay_date(item["date_text"]) if item["date_text"] else ""

                if since and pub_date:
                    try:
                        if date.fromisoformat(pub_date) < since:
                            continue
                    except ValueError:
                        pass

                yield DiscoveredItem(
                    source_url=article_url,
                    title=item["title"],
                    published_at=pub_date,
                    doc_type=doc_type,
                    language=language,
                    metadata={
                        "listing_url": current_url,
                        "date_text": item["date_text"],
                        "section": section_name,
                    },
                )

            # Early stop: pagination widget has no further pages
            if not _has_more_pages(html, offset):
                log.info(f"[moh] Pagination end at offset={offset} for {seed_url}")
                break

            offset += page_size

    # -- HOOK 2: Fetch + Extract Downloads ----------------------------------

    def fetch_and_extract(self, item: DiscoveredItem) -> Iterable[DocumentCandidate]:
        """Fetch an article detail page and extract embedded document links.

        Yields the HTML article page itself as a candidate, plus any embedded
        PDF/DOC/etc. links found in the article body.
        """
        article_url = item.source_url

        # If the URL is a direct document link, yield it without HTML fetch
        url_lower = article_url.lower().split("?")[0]
        doc_extensions = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")
        if any(url_lower.endswith(ext) for ext in doc_extensions):
            yield DocumentCandidate(
                url=article_url,
                source_page_url=item.metadata.get("listing_url", article_url),
                title=item.title,
                published_at=item.published_at,
                doc_type=item.doc_type,
                content_type=guess_content_type(article_url),
                language=item.language,
            )
            return

        # Fetch article HTML
        try:
            resp = self.http.get(article_url)
            html = resp.text
        except Exception as e:
            log.warning(f"[moh] Failed to fetch article {article_url}: {e}")
            return

        # Extract metadata from article detail page
        meta = _extract_article_meta(html)
        title = meta.get("title") or item.title
        published_at = meta.get("published_at") or item.published_at

        # Fallback: use listing date_text if detail page has no date
        if not published_at:
            date_text = item.metadata.get("date_text", "")
            if date_text:
                published_at = parse_malay_date(date_text)

        # Yield the HTML article page itself
        yield DocumentCandidate(
            url=article_url,
            source_page_url=item.metadata.get("listing_url", article_url),
            title=title,
            published_at=published_at,
            doc_type=item.doc_type,
            content_type="text/html",
            language=item.language,
        )

        # Extract and yield embedded document links from article body
        base_url = self.config.get("base_url", _BASE_URL)
        embedded_links = _extract_embedded_doc_links(html, base_url)

        for dl in embedded_links:
            ct = guess_content_type(dl.url)
            yield DocumentCandidate(
                url=dl.url,
                source_page_url=article_url,
                title=title,
                published_at=published_at,
                doc_type=item.doc_type,
                content_type=ct,
                language=item.language,
            )

    # -- HOOK 3: Download Link Extraction (override) ------------------------

    def extract_downloads(self, html: str, base_url: str) -> list[DownloadLink]:
        """MOH-specific download extraction scoped to the article body.

        Falls back to the generic extractor if no article body links are found.
        """
        embedded = _extract_embedded_doc_links(html, base_url)
        if embedded:
            return embedded
        return extract_document_links(html, base_url)
