"""DOSM adapter — Department of Statistics Malaysia (open.dosm.gov.my).

Scrapes publications from OpenDOSM, a Next.js portal with embedded JSON
metadata. Downloads PDFs and Excel files from storage.dosm.gov.my.

Discovery flow:
1. Paginate through /publications?page=N (90 pages, 15 per page)
2. Extract publication IDs from __NEXT_DATA__ JSON
3. Fetch each publication detail page
4. Parse resources array from __NEXT_DATA__ for download URLs

All files hosted on public S3: storage.dosm.gov.my/{category}/{id}.{pdf|xlsx}
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from polisi_scraper.adapters.base import BaseSiteAdapter, DiscoveredItem, DocumentCandidate
from polisi_scraper.adapters.registry import register_adapter
from polisi_scraper.core.urls import guess_content_type

log = logging.getLogger(__name__)

BASE_URL = "https://open.dosm.gov.my"
STORAGE_URL = "https://storage.dosm.gov.my"


def _extract_next_data(html: str) -> dict | None:
    """Extract __NEXT_DATA__ JSON from a Next.js page."""
    soup = BeautifulSoup(html, "lxml")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script:
        return None
    try:
        return json.loads(script.string)
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_publication_ids_from_listing(next_data: dict) -> list[dict]:
    """Extract publication info from a /publications listing page's __NEXT_DATA__."""
    results: list[dict] = []
    try:
        # Navigate the Next.js data structure
        props = next_data.get("props", {}).get("pageProps", {})

        # Try different possible data locations
        publications = props.get("publications", [])
        if not publications:
            publications = props.get("data", [])
        if not publications:
            # Fallback: search recursively for arrays with publication-like objects
            for key, val in props.items():
                if isinstance(val, list) and val and isinstance(val[0], dict) and "publication_id" in val[0]:
                    publications = val
                    break

        for pub in publications:
            if not isinstance(pub, dict):
                continue
            pub_id = pub.get("publication_id", "")
            if not pub_id:
                continue
            results.append({
                "id": pub_id,
                "title": pub.get("title", pub.get("publication_title", pub_id)),
                "release_date": pub.get("release_date", ""),
                "frequency": pub.get("frequency", ""),
                "type": pub.get("publication_type", ""),
            })
    except Exception as exc:
        log.warning("[dosm] failed to parse listing data: %s", exc)

    return results


def _extract_resources_from_detail(next_data: dict) -> list[dict]:
    """Extract download resources from a publication detail page's __NEXT_DATA__."""
    resources: list[dict] = []
    try:
        props = next_data.get("props", {}).get("pageProps", {})

        # Look for resources array
        res_list = props.get("resources", [])
        if not res_list:
            # Search in nested structures
            for key, val in props.items():
                if isinstance(val, dict):
                    res_list = val.get("resources", [])
                    if res_list:
                        break
                if isinstance(val, list) and val and isinstance(val[0], dict) and "resource_link" in val[0]:
                    res_list = val
                    break

        for res in res_list:
            if not isinstance(res, dict):
                continue
            link = res.get("resource_link", "")
            if not link:
                continue
            resources.append({
                "url": link,
                "type": res.get("resource_type", ""),
                "name": res.get("resource_name", ""),
            })
    except Exception as exc:
        log.warning("[dosm] failed to parse resources: %s", exc)

    return resources


@register_adapter
class DosmAdapter(BaseSiteAdapter):
    slug = "dosm"
    agency = "Jabatan Perangkaan Malaysia (DOSM)"
    requires_browser = False

    def _base_url(self) -> str:
        return self.config.get("base_url", BASE_URL)

    def discover(self, since: date | None = None, max_pages: int = 0) -> Iterable[DiscoveredItem]:
        sections = self.config.get("sections", [])
        pages_fetched = 0

        for section in sections:
            source_type = section.get("source_type", "publications")
            doc_type = section.get("doc_type", "report")
            language = section.get("language", "ms")
            section_name = section.get("name", "unknown")

            log.info("[dosm] discover section=%s source_type=%s", section_name, source_type)

            if source_type == "publications":
                for item in self._discover_publications(section, doc_type, language, since):
                    pages_fetched += 1
                    if max_pages and pages_fetched >= max_pages:
                        return
                    yield item

            elif source_type == "data_catalogue":
                for item in self._discover_data_catalogue(section, doc_type, language):
                    pages_fetched += 1
                    if max_pages and pages_fetched >= max_pages:
                        return
                    yield item

    def _discover_publications(
        self, section: dict, doc_type: str, language: str, since: date | None,
    ) -> Iterable[DiscoveredItem]:
        """Paginate through /publications and discover all publication detail pages."""
        base = self._base_url()
        max_listing_pages = section.get("max_listing_pages", 100)

        for page_num in range(1, max_listing_pages + 1):
            page_url = f"{base}/publications?page={page_num}"
            log.info("[dosm] fetch publications page %d", page_num)

            try:
                resp = self.http.get(page_url)
            except Exception as exc:
                log.error("[dosm] publications page error %s: %s", page_url, exc)
                break

            next_data = _extract_next_data(resp.text)
            if not next_data:
                log.warning("[dosm] no __NEXT_DATA__ on page %d", page_num)
                break

            pubs = _extract_publication_ids_from_listing(next_data)
            if not pubs:
                log.info("[dosm] no publications on page %d, stopping", page_num)
                break

            log.info("[dosm] page %d: %d publications", page_num, len(pubs))

            for pub in pubs:
                pub_date = pub.get("release_date", "")
                if since and pub_date:
                    try:
                        if date.fromisoformat(pub_date[:10]) < since:
                            continue
                    except ValueError:
                        pass

                detail_url = f"{base}/publications/{pub['id']}"
                yield DiscoveredItem(
                    source_url=detail_url,
                    title=pub.get("title", pub["id"]),
                    published_at=pub_date[:10] if pub_date else "",
                    doc_type=doc_type,
                    language=language,
                    metadata={
                        "section": "publications",
                        "source_type": "publications",
                        "publication_id": pub["id"],
                        "frequency": pub.get("frequency", ""),
                        "pub_type": pub.get("type", ""),
                        "has_detail_page": True,
                    },
                )

    def _discover_data_catalogue(
        self, section: dict, doc_type: str, language: str,
    ) -> Iterable[DiscoveredItem]:
        """Discover datasets from the data catalogue page."""
        base = self._base_url()
        catalogue_url = f"{base}/data-catalogue"

        log.info("[dosm] fetch data catalogue: %s", catalogue_url)
        try:
            resp = self.http.get(catalogue_url)
        except Exception as exc:
            log.error("[dosm] catalogue fetch error: %s", exc)
            return

        next_data = _extract_next_data(resp.text)
        if not next_data:
            log.warning("[dosm] no __NEXT_DATA__ on data catalogue")
            return

        # Extract dataset IDs from the catalogue
        props = next_data.get("props", {}).get("pageProps", {})
        datasets = []
        for key, val in props.items():
            if isinstance(val, list) and val and isinstance(val[0], dict):
                if any(k in val[0] for k in ["id", "dataset_id", "catalog_id"]):
                    datasets = val
                    break

        log.info("[dosm] data catalogue: %d datasets found", len(datasets))

        for ds in datasets:
            if not isinstance(ds, dict):
                continue
            ds_id = ds.get("id", ds.get("dataset_id", ds.get("catalog_id", "")))
            if not ds_id:
                continue

            detail_url = f"{base}/data-catalogue/{ds_id}"
            yield DiscoveredItem(
                source_url=detail_url,
                title=ds.get("title", ds.get("name", ds_id)),
                doc_type=doc_type,
                language=language,
                metadata={
                    "section": "data_catalogue",
                    "source_type": "data_catalogue",
                    "dataset_id": ds_id,
                    "has_detail_page": True,
                },
            )

    def fetch_and_extract(self, item: DiscoveredItem) -> Iterable[DocumentCandidate]:
        """Fetch publication/dataset detail page and extract download resources."""
        has_detail = item.metadata.get("has_detail_page", False)

        if not has_detail:
            ct = guess_content_type(item.source_url)
            yield DocumentCandidate(
                url=item.source_url,
                source_page_url=item.source_url,
                title=item.title,
                published_at=item.published_at,
                doc_type=item.doc_type,
                content_type=ct or "application/pdf",
                language=item.language,
            )
            return

        # Fetch detail page and extract resources from __NEXT_DATA__
        try:
            resp = self.http.get(item.source_url)
        except Exception as exc:
            log.warning("[dosm] failed to fetch %s: %s", item.source_url, exc)
            return

        next_data = _extract_next_data(resp.text)
        if not next_data:
            log.warning("[dosm] no __NEXT_DATA__ on %s", item.source_url)
            return

        resources = _extract_resources_from_detail(next_data)
        if not resources:
            # Fallback: scan HTML for storage.dosm.gov.my links
            soup = BeautifulSoup(resp.text, "lxml")
            seen: set[str] = set()
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if "storage.dosm.gov.my" in href and href not in seen:
                    seen.add(href)
                    resources.append({
                        "url": href,
                        "type": "pdf" if href.endswith(".pdf") else "excel",
                        "name": a.get_text(strip=True) or href.split("/")[-1],
                    })

        log.info("[dosm] %s: %d resources", item.metadata.get("publication_id", item.source_url), len(resources))

        for res in resources:
            url = res["url"]
            ct = guess_content_type(url)
            yield DocumentCandidate(
                url=url,
                source_page_url=item.source_url,
                title=f"{item.title} - {res.get('name', '')}".strip(" -"),
                published_at=item.published_at,
                doc_type=item.doc_type,
                content_type=ct or "application/pdf",
                language=item.language,
            )
