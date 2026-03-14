"""data.gov.my adapter — CKAN API-based open data portal scraper.

Source: https://archive.data.gov.my
API:    CKAN 3 (package_search, package_show)

Discovers all datasets via the CKAN package_search API and yields each
downloadable resource (CSV, XLSX, PDF, etc.) as a DocumentCandidate.
With ~12,340 datasets this requires only ~13 API calls to enumerate.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from polisi_scraper.adapters.base import BaseSiteAdapter, DiscoveredItem, DocumentCandidate
from polisi_scraper.adapters.registry import register_adapter
from polisi_scraper.core.urls import guess_content_type

log = logging.getLogger(__name__)

API_BASE = "https://archive.data.gov.my/data/api/3/action"
ROWS_PER_PAGE = 1000

# File formats we want to download
_WANTED_FORMATS = {"csv", "xlsx", "xls", "pdf", "json", "xml", "doc", "docx"}


@register_adapter
class DataGovMyAdapter(BaseSiteAdapter):
    slug = "data_gov_my"
    agency = "Malaysian Open Data Portal (MAMPU)"
    requires_browser = False

    def discover(self, since: date | None = None, max_pages: int = 0) -> Iterable[DiscoveredItem]:
        """Enumerate all datasets via CKAN package_search API.

        Each dataset may have multiple resources (CSV, XLSX, etc.).
        We yield one DiscoveredItem per *resource* (not per dataset)
        so that each downloadable file gets its own archive entry.
        """
        start = 0
        pages_fetched = 0
        total_datasets = None

        while True:
            if max_pages and pages_fetched >= max_pages:
                log.info("[data_gov_my] max_pages=%d reached", max_pages)
                return

            url = f"{API_BASE}/package_search?rows={ROWS_PER_PAGE}&start={start}"
            log.info("[data_gov_my] fetching datasets start=%d", start)

            try:
                resp = self.http.get(url)
                data = resp.json()
            except Exception as exc:
                log.error("[data_gov_my] API error at start=%d: %s", start, exc)
                break

            if not data.get("success"):
                log.error("[data_gov_my] API returned success=false at start=%d", start)
                break

            result = data.get("result", {})
            if total_datasets is None:
                total_datasets = result.get("count", 0)
                log.info("[data_gov_my] total datasets: %d", total_datasets)

            datasets = result.get("results", [])
            if not datasets:
                log.info("[data_gov_my] no more datasets at start=%d", start)
                break

            pages_fetched += 1

            for ds in datasets:
                ds_title = ds.get("title", ds.get("name", ""))
                ds_name = ds.get("name", "")
                ds_modified = ds.get("metadata_modified", "")[:10]  # YYYY-MM-DD
                org = ds.get("organization") or {}
                org_name = org.get("title", org.get("name", ""))

                # since filter on dataset level
                if since and ds_modified:
                    try:
                        if date.fromisoformat(ds_modified) < since:
                            continue
                    except ValueError:
                        pass

                resources = ds.get("resources", [])
                for res in resources:
                    fmt = (res.get("format") or "").lower().strip()
                    if fmt not in _WANTED_FORMATS:
                        continue

                    res_url = res.get("url", "")
                    if not res_url:
                        continue

                    res_name = res.get("name", "") or res.get("description", "") or ds_title
                    res_modified = (res.get("last_modified") or ds_modified)[:10]

                    yield DiscoveredItem(
                        source_url=res_url,
                        title=f"{ds_title} — {res_name}".strip(" —"),
                        published_at=res_modified,
                        doc_type="dataset",
                        language="ms",
                        metadata={
                            "dataset_name": ds_name,
                            "dataset_id": ds.get("id", ""),
                            "resource_id": res.get("id", ""),
                            "format": fmt,
                            "organization": org_name,
                            "source_type": "ckan_api",
                        },
                    )

            start += ROWS_PER_PAGE
            if start >= (total_datasets or 0):
                log.info("[data_gov_my] enumerated all %d datasets", total_datasets)
                break

    def fetch_and_extract(self, item: DiscoveredItem) -> Iterable[DocumentCandidate]:
        """Yield the resource URL as a direct download candidate."""
        fmt = item.metadata.get("format", "")
        ct = guess_content_type(item.source_url)

        # Override content type for known formats
        format_ct = {
            "csv": "text/csv",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xls": "application/vnd.ms-excel",
            "json": "application/json",
            "xml": "application/xml",
        }
        if fmt in format_ct:
            ct = format_ct[fmt]

        yield DocumentCandidate(
            url=item.source_url,
            source_page_url=f"https://archive.data.gov.my/data/ms_MY/dataset/{item.metadata.get('dataset_name', '')}",
            title=item.title,
            published_at=item.published_at,
            doc_type=item.doc_type,
            content_type=ct,
            language=item.language,
        )
