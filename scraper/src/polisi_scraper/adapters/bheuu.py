"""BHEUU adapter — Strapi v3 API, no HTML parsing."""

from __future__ import annotations

import logging
from datetime import date
from typing import Iterable

from dateutil import parser as dateutil_parser

from polisi_scraper.adapters.base import (
    BaseSiteAdapter,
    DiscoveredItem,
    DocumentCandidate,
)
from polisi_scraper.adapters.registry import register_adapter
from polisi_scraper.core.urls import canonical_url, guess_content_type

log = logging.getLogger(__name__)

STRAPI_BASE = "https://strapi.bheuu.gov.my"


def _parse_strapi_date(value: str | None) -> str:
    if not value or not value.strip():
        return ""
    value = value.strip()
    if len(value) == 4 and value.isdigit():
        return f"{value}-01-01"
    try:
        dt = dateutil_parser.parse(value)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        return ""


def _get_nested(data: dict, dotted_key: str) -> str | None:
    keys = dotted_key.split(".")
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    if current is None:
        return None
    return str(current) if not isinstance(current, str) else current


def _resolve_file_url(raw: str | None) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    if raw.startswith(("http://", "https://")):
        return raw
    if raw.startswith("/"):
        return f"{STRAPI_BASE}{raw}"
    return raw


@register_adapter
class BheuuAdapter(BaseSiteAdapter):
    slug = "bheuu"
    agency = "Bahagian Hal Ehwal Undang-undang (BHEUU)"
    requires_browser = False

    def discover(self, since: date | None = None, max_pages: int = 0) -> Iterable[DiscoveredItem]:
        strapi_base = self.config.get("strapi_base", STRAPI_BASE)
        sections = self.config.get("sections", [])
        limit = 100

        for section in sections:
            endpoint = section.get("endpoint", "")
            source_type = section.get("source_type", "collection")
            doc_type = section.get("doc_type", "other")
            language = section.get("language", "ms")
            title_field = section.get("title_field", "title")
            date_field = section.get("date_field", "publishDate")
            file_field = section.get("file_field", "")

            if source_type == "single_type":
                # Single-type endpoint returns one dict
                url = f"{strapi_base}/{endpoint}"
                try:
                    resp = self.http.get(url)
                    record = resp.json()
                    if isinstance(record, dict):
                        yield from self._process_record(
                            record, url, title_field, date_field, file_field,
                            doc_type, language, since,
                        )
                except Exception as e:
                    log.warning(f"[bheuu] Failed to fetch {url}: {e}")
                continue

            if source_type == "metadata_only":
                # Metadata only — no file downloads
                start = 0
                while True:
                    url = f"{strapi_base}/{endpoint}?_start={start}&_limit={limit}"
                    try:
                        resp = self.http.get(url)
                        records = resp.json()
                    except Exception as e:
                        log.warning(f"[bheuu] Failed to fetch {url}: {e}")
                        break
                    if not isinstance(records, list) or not records:
                        break
                    for rec in records:
                        title = _get_nested(rec, title_field) or ""
                        pub_date = _parse_strapi_date(_get_nested(rec, date_field))
                        if since and pub_date:
                            try:
                                if date.fromisoformat(pub_date) < since:
                                    continue
                            except ValueError:
                                pass
                        yield DiscoveredItem(
                            source_url=url,
                            title=title,
                            published_at=pub_date,
                            doc_type=doc_type,
                            language=language,
                            metadata={"section": endpoint, "type": "metadata_only"},
                        )
                    start += limit
                    if len(records) < limit:
                        break
                continue

            # Collection endpoint — paginated
            start = 0
            page_count = 0
            while True:
                url = f"{strapi_base}/{endpoint}?_start={start}&_limit={limit}"
                try:
                    resp = self.http.get(url)
                    records = resp.json()
                except Exception as e:
                    log.warning(f"[bheuu] Failed to fetch {url}: {e}")
                    break

                if not isinstance(records, list) or not records:
                    break

                for rec in records:
                    yield from self._process_record(
                        rec, url, title_field, date_field, file_field,
                        doc_type, language, since,
                    )

                start += limit
                page_count += 1
                if len(records) < limit:
                    break
                if max_pages and page_count >= max_pages:
                    break

    def _process_record(
        self, record: dict, source_url: str,
        title_field: str, date_field: str, file_field: str,
        doc_type: str, language: str, since: date | None,
    ) -> Iterable[DiscoveredItem]:
        title = _get_nested(record, title_field) or ""
        if not title:
            for fallback in ("title", "titleEN", "titleBM", "tenderTitle"):
                title = record.get(fallback, "")
                if title:
                    break

        # Date extraction with fallback chain
        raw_date = _get_nested(record, date_field) if date_field else None
        if not raw_date:
            for fb in ("publishDate", "published_at", "startDate", "resultDate", "createdAt"):
                raw_date = record.get(fb)
                if raw_date:
                    break
        pub_date = _parse_strapi_date(raw_date)

        if since and pub_date:
            try:
                if date.fromisoformat(pub_date) < since:
                    return
            except ValueError:
                pass

        # File URL
        file_url = _resolve_file_url(_get_nested(record, file_field)) if file_field else ""
        if not file_url:
            return

        yield DiscoveredItem(
            source_url=file_url,  # For BHEUU, source_url IS the file URL
            title=title,
            published_at=pub_date,
            doc_type=doc_type,
            language=language,
            metadata={"strapi_api": source_url},
        )

    def fetch_and_extract(self, item: DiscoveredItem) -> Iterable[DocumentCandidate]:
        """BHEUU items are direct file URLs from the API — no page fetching needed."""
        ct = guess_content_type(item.source_url)
        yield DocumentCandidate(
            url=item.source_url,
            source_page_url=item.metadata.get("strapi_api", item.source_url),
            title=item.title,
            published_at=item.published_at,
            doc_type=item.doc_type,
            content_type=ct,
            language=item.language,
        )
