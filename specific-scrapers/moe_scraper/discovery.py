from __future__ import annotations

import json
import logging
import re
from collections import OrderedDict
from urllib.parse import urljoin

from moe_scraper.config import SiteConfig
from moe_scraper.http_client import HttpClient
from moe_scraper.models import ListingItem
from moe_scraper.parser import parse_atom_feed, parse_listing_links, parse_moe_listing_table, parse_sitemap_xml
from moe_scraper.utils import canonicalize_url, is_allowed_host


def parse_robots_sitemaps(robots_text: str, base_url: str) -> list[str]:
    sitemaps: list[str] = []
    for line in robots_text.splitlines():
        match = re.match(r"^\s*sitemap\s*:\s*(.+)$", line, flags=re.IGNORECASE)
        if match:
            sitemaps.append(match.group(1).strip())
    if not sitemaps:
        for candidate in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml", "/sitemap1.xml"):
            sitemaps.append(urljoin(base_url, candidate))
    return sitemaps


def discover_urls(config: SiteConfig, http: HttpClient, max_pages: int) -> list[str]:
    logger = logging.getLogger(__name__)
    urls: OrderedDict[str, None] = OrderedDict()

    def remember(candidate: str) -> None:
        canonical = canonicalize_url(candidate)
        if is_allowed_host(canonical, set(config.allowed_hosts)):
            urls[canonical] = None

    robots_url = urljoin(config.base_url, "/robots.txt")
    try:
        robots = http.fetch(robots_url)
        robots_text = robots.content.decode("utf-8", errors="ignore")
        robots_sitemaps = parse_robots_sitemaps(robots_text, config.base_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning(json.dumps({"url": robots_url, "status": "network", "reason": str(exc)}))
        robots_sitemaps = []

    for feed_url in config.feed_urls:
        try:
            feed = http.fetch(feed_url)
            for url in parse_atom_feed(feed.content):
                remember(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning(json.dumps({"url": feed_url, "status": "parse", "reason": str(exc)}))

    sitemap_candidates = list(dict.fromkeys(config.sitemap_urls + robots_sitemaps))
    for sitemap_url in sitemap_candidates:
        if len(urls) >= max_pages:
            break
        try:
            sitemap = http.fetch(sitemap_url)
            if "xml" not in sitemap.content_type:
                continue
            discovered = parse_sitemap_xml(sitemap.content)
            for url in discovered:
                remember(url)
                if len(urls) >= max_pages:
                    break
        except Exception:
            # Sitemaps are often blocked or redirected on this site.
            continue

    for section_url in config.section_urls:
        if len(urls) >= max_pages:
            break
        try:
            page = http.fetch(section_url)
            for url in parse_listing_links(page.content, page.url):
                remember(url)
                if len(urls) >= max_pages:
                    break
        except Exception as exc:  # noqa: BLE001
            logger.warning(json.dumps({"url": section_url, "status": "network", "reason": str(exc)}))

    return list(urls.keys())


def discover_listing_items(config: SiteConfig, http: HttpClient, max_pages: int) -> list[ListingItem]:
    """Fetch each section URL and extract items from the MOE DataTables listing table.

    Returns :class:`ListingItem` objects that carry the title and raw date string
    directly from the listing row — more reliable than parsing the detail page,
    which has an empty ``<h1>`` and a generic ``<title>`` tag.
    """
    logger = logging.getLogger(__name__)
    items: list[ListingItem] = []
    seen: set[str] = set()
    allowed_hosts = set(config.allowed_hosts)

    for section_url in config.section_urls:
        if len(items) >= max_pages:
            break
        try:
            page = http.fetch(section_url)
            for item in parse_moe_listing_table(page.content, page.url):
                canonical = canonicalize_url(item.url)
                if canonical in seen:
                    continue
                if not is_allowed_host(canonical, allowed_hosts):
                    continue
                seen.add(canonical)
                items.append(item)
                if len(items) >= max_pages:
                    break
        except Exception as exc:  # noqa: BLE001
            logger.warning(json.dumps({"url": section_url, "status": "network", "reason": str(exc)}))

    return items
