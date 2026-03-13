from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from moe_scraper.models import ListingItem
from moe_scraper.utils import is_downloadable_url, normalize_whitespace, parse_publication_date

# Generic title prefixes that the MOE CMS emits — strip these to get a meaningful fallback.
_TITLE_PREFIXES = ("kpm | ", "kementerian pendidikan malaysia | ", "kpm | ")


@dataclass(slots=True)
class ParsedDetail:
    title: str
    published_at: str | None
    language: str | None
    file_links: list[str]


def parse_atom_feed(feed_xml: bytes) -> list[str]:
    urls: list[str] = []
    root = ElementTree.fromstring(feed_xml)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("atom:entry", ns):
        link = entry.find("atom:link", ns)
        if link is None:
            continue
        href = link.attrib.get("href")
        if href:
            urls.append(href)
    return urls


def parse_sitemap_xml(sitemap_xml: bytes) -> list[str]:
    urls: list[str] = []
    root = ElementTree.fromstring(sitemap_xml)
    if root.tag.endswith("sitemapindex"):
        for node in root.findall("{*}sitemap/{*}loc"):
            if node.text:
                urls.append(node.text.strip())
    else:
        for node in root.findall("{*}url/{*}loc"):
            if node.text:
                urls.append(node.text.strip())
    return urls


def parse_listing_links(html: bytes, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        if not href:
            continue
        absolute = urljoin(page_url, href)
        if absolute.startswith("http"):
            links.append(absolute)
    return links


def parse_moe_listing_table(html: bytes, page_url: str) -> list[ListingItem]:
    """Extract items from the DataTables listing table used on www.moe.gov.my.

    All MOE section listing pages share the same structure::

        <table id="example" class="table table-bordered table-hover">
          <thead><tr><th>Tajuk</th><th>Tarikh</th></tr></thead>
          <tbody>
            <tr>
              <td><a href="https://www.moe.gov.my/...">Title text</a></td>
              <td>12 Feb 2026</td>
            </tr>
          </tbody>
        </table>

    The table data is server-side rendered (no client-side AJAX); DataTables only
    provides the search/pagination UI on top.
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[ListingItem] = []
    for row in soup.select("table#example tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        anchor = cells[0].find("a", href=True)
        if not anchor:
            continue
        href = anchor.get("href", "").strip()
        if not href:
            continue
        url = urljoin(page_url, href)
        if not url.startswith("http"):
            continue
        title = normalize_whitespace(anchor.get_text())
        date_str = normalize_whitespace(cells[1].get_text()) if len(cells) > 1 else None
        items.append(ListingItem(url=url, title=title or "Untitled", date_str=date_str or None))
    return items


def parse_detail_page(html: bytes, page_url: str) -> ParsedDetail:
    soup = BeautifulSoup(html, "lxml")

    # MOE detail pages often have an empty <h1> and a generic title tag like
    # "KPM | Kenyataan Media".  The nav/header area contains <h2> elements that
    # appear before the main content <h1> in document order, so we must walk the
    # heading hierarchy explicitly (h1 → h2 → h3) rather than using a single
    # CSS selector, which would return them interleaved in DOM order.
    title = ""
    for tag_name in ("h1", "h2", "h3"):
        for heading_tag in soup.find_all(tag_name):
            text = normalize_whitespace(heading_tag.get_text())
            if text:
                title = text
                break
        if title:
            break
    if not title and soup.title and soup.title.text:
        raw = normalize_whitespace(soup.title.text)
        lower = raw.lower()
        for prefix in _TITLE_PREFIXES:
            if lower.startswith(prefix):
                raw = raw[len(prefix):]
                break
        title = raw

    # MOE CMS uses lang="my" (non-standard; "my" is Burmese in BCP 47) to mean
    # Malay.  Normalise to the correct ISO 639-1 code "ms".
    raw_lang = soup.html.get("lang") if soup.html else None
    language = _normalize_lang(raw_lang)

    # Date extraction: MOE detail pages rarely embed structured date metadata.
    # Try standard meta tags and <time> elements; the listing-page date is more
    # reliable and will be preferred by the crawler when available.
    publication_candidates = [
        soup.select_one("meta[property='article:published_time']"),
        soup.select_one("meta[name='pubdate']"),
        soup.select_one("meta[name='date']"),
        soup.select_one("time[datetime]"),
        soup.select_one(".published, .date, .post-date"),
    ]
    published_at = None
    for candidate in publication_candidates:
        if not candidate:
            continue
        raw = candidate.get("content") or candidate.get("datetime") or candidate.text
        published_at = parse_publication_date(raw)
        if published_at:
            break

    file_links: list[str] = []
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        absolute = urljoin(page_url, href)
        if is_downloadable_url(absolute):
            file_links.append(absolute)

    return ParsedDetail(title=title or "Untitled", published_at=published_at, language=language, file_links=file_links)


def _normalize_lang(lang: str | None) -> str | None:
    """Normalise the HTML lang attribute to a BCP 47 language tag.

    MOE pages use ``lang="my"`` which is the ISO 639-1 code for Burmese, not
    Malay.  Map it to the correct ``"ms"`` tag.
    """
    if not lang:
        return None
    mapping = {"my": "ms"}
    lower = lang.strip().lower()
    return mapping.get(lower, lower) or None
