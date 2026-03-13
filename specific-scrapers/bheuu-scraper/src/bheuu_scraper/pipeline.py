"""
Orchestration pipeline for bheuu.gov.my (Nuxt.js / Strapi v3 CMS).

Site architecture:
  Frontend : https://www.bheuu.gov.my  (Nuxt.js SSR, Vue 2)
  Backend  : https://strapi.bheuu.gov.my  (Strapi v3 REST API, publicly accessible)

All content is fetched from the Strapi API as JSON — no HTML scraping needed.
Files (PDFs, DOCXs) are served from strapi.bheuu.gov.my/uploads/.

Source types supported (per section in bheuu.yaml):

  collection   – Paginated Strapi collection (?_start=N&_limit=PAGE_SIZE).
                 Each record has a file URL extracted via `file_field` config.
                 Pagination stops when the API returns an empty array.

  single_type  – Single-type Strapi endpoint that returns a single dict (not array).
                 Treated as one document containing one or more files.
                 Useful for act-protection-newspaper-clip, act-protection-guideline,
                 act-protection-brief, act-protection-copy.

  metadata_only– Collection with no downloadable file (e.g. latest-news,
                 tender-holders). Records are written to records.jsonl with
                 content_type="text/html" and the Strapi API URL as canonical_url.
                 No Spaces upload is performed.

Run flow per record:
  a. Resolve file URL from API JSON.
  b. Canonicalize URL.
  c. Pre-fetch dedup by canonical_url.
  d. Apply --since date filter.
  e. Fetch file bytes.
  f. Compute sha256; post-fetch dedup → reuse spaces_url if already stored.
  g. Upload to Spaces.
  h. Write Record to records.jsonl + state DB.

Run summary: new, changed, skipped, failed counts.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

import yaml

from .archiver import SpacesArchiver, sha256_of_bytes, spaces_object_path
from .crawler import HTTPClient, canonical_url, is_allowed_host
from .extractor import (
    extract_date,
    extract_file_url,
    extract_record_id,
    extract_title,
    guess_content_type,
    resolve_file_url,
)
from .models import CrawlRun, Record
from .state import StateStore

log = logging.getLogger(__name__)

_PAGE_SIZE = 100   # Strapi records per page


# ── Helpers ───────────────────────────────────────────────────────────────────


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ── Pipeline ──────────────────────────────────────────────────────────────────


class BHEUUPipeline:
    def __init__(
        self,
        config: dict,
        state: StateStore,
        archiver: SpacesArchiver,
        http: HTTPClient,
        manifest_dir: Path,
        dry_run: bool = False,
        since: Optional[str] = None,
        max_pages: int = 0,
    ) -> None:
        self.config = config
        self.state = state
        self.archiver = archiver
        self.http = http
        self.manifest_dir = manifest_dir
        self.dry_run = dry_run
        self.since = since            # "YYYY-MM-DD" lower bound (inclusive), or None
        self.max_pages = max_pages    # 0 = unlimited

        self.site_slug: str = config["site_slug"]
        self.agency: str = config["agency"]
        self.strapi_base: str = config["strapi_base"]
        self.allowed_hosts: frozenset[str] = frozenset(config.get("allowed_hosts", []))

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self) -> CrawlRun:
        run_id = (
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{self.site_slug}"
        )
        run = CrawlRun(
            crawl_run_id=run_id,
            site_slug=self.site_slug,
            started_at=_utcnow(),
        )

        self.manifest_dir.mkdir(parents=True, exist_ok=True)
        records_path = self.manifest_dir / "records.jsonl"
        runs_path = self.manifest_dir / "crawl_runs.jsonl"

        for section in self.config.get("sections", []):
            source_type = section.get("source_type", "collection")

            if source_type == "collection":
                entries = list(self._discover_from_collection(section, run_id))
            elif source_type == "single_type":
                entries = list(self._discover_from_single_type(section, run_id))
            elif source_type == "metadata_only":
                entries = list(self._discover_from_collection(section, run_id))
            else:
                log.warning(
                    {
                        "event": "unknown_source_type",
                        "source_type": source_type,
                        "section": section.get("name"),
                        "category": "policy",
                    }
                )
                continue

            for entry in entries:
                self._process_entry(entry, section, run, records_path)

        run.completed_at = _utcnow()

        if not self.dry_run:
            self.state.save_crawl_run(
                run.crawl_run_id,
                run.site_slug,
                run.started_at,
                run.completed_at,
                run.new_count,
                run.changed_count,
                run.skipped_count,
                run.failed_count,
            )

        with open(runs_path, "a", encoding="utf-8") as fh:
            fh.write(run.to_json() + "\n")

        return run

    # ── Discovery: paginated collection ───────────────────────────────────────

    def _discover_from_collection(
        self, section: dict, run_id: str
    ) -> Iterator[dict]:
        """
        Walk a paginated Strapi v3 collection endpoint.

        Pagination: ?_start=N&_limit=PAGE_SIZE; stops when array is empty.
        """
        endpoint = section.get("endpoint", "")
        if not endpoint:
            log.warning(
                {
                    "event": "section_missing_endpoint",
                    "section": section.get("name"),
                    "category": "policy",
                }
            )
            return

        api_url = f"{self.strapi_base}/{endpoint}"
        start = 0
        pages_fetched = 0

        while True:
            if self.max_pages and pages_fetched >= self.max_pages:
                log.info(
                    {
                        "event": "max_pages_reached",
                        "max_pages": self.max_pages,
                        "crawl_run_id": run_id,
                        "endpoint": endpoint,
                    }
                )
                return

            params = {"_start": start, "_limit": _PAGE_SIZE}
            log.info(
                {
                    "event": "fetch_collection_page",
                    "url": api_url,
                    "params": params,
                    "crawl_run_id": run_id,
                }
            )

            try:
                data = self.http.get_json(api_url, params=params)
            except Exception as exc:
                log.error(
                    {
                        "event": "collection_fetch_error",
                        "url": api_url,
                        "error": str(exc),
                        "category": "network",
                        "crawl_run_id": run_id,
                    }
                )
                break

            if not isinstance(data, list) or not data:
                log.info(
                    {
                        "event": "collection_empty_stop",
                        "url": api_url,
                        "start": start,
                        "crawl_run_id": run_id,
                    }
                )
                break

            pages_fetched += 1

            for record in data:
                yield {
                    "strapi_record": record,
                    "source_url": f"{api_url}?_start={start}&_limit={_PAGE_SIZE}",
                    "crawl_run_id": run_id,
                }

            start += _PAGE_SIZE

    # ── Discovery: single-type endpoint ───────────────────────────────────────

    def _discover_from_single_type(
        self, section: dict, run_id: str
    ) -> Iterator[dict]:
        """
        Fetch a Strapi single-type endpoint (returns a dict, not a list).

        Yields exactly one entry.
        """
        endpoint = section.get("endpoint", "")
        if not endpoint:
            log.warning(
                {
                    "event": "section_missing_endpoint",
                    "section": section.get("name"),
                    "category": "policy",
                }
            )
            return

        api_url = f"{self.strapi_base}/{endpoint}"
        log.info(
            {
                "event": "fetch_single_type",
                "url": api_url,
                "crawl_run_id": run_id,
            }
        )

        try:
            data = self.http.get_json(api_url)
        except Exception as exc:
            log.error(
                {
                    "event": "single_type_fetch_error",
                    "url": api_url,
                    "error": str(exc),
                    "category": "network",
                    "crawl_run_id": run_id,
                }
            )
            return

        if not isinstance(data, dict):
            log.warning(
                {
                    "event": "single_type_unexpected_type",
                    "url": api_url,
                    "type": type(data).__name__,
                    "category": "parse",
                }
            )
            return

        yield {
            "strapi_record": data,
            "source_url": api_url,
            "crawl_run_id": run_id,
        }

    # ── Entry processing ──────────────────────────────────────────────────────

    def _process_entry(
        self,
        entry: dict,
        section: dict,
        run: CrawlRun,
        records_path: Path,
    ) -> None:
        """
        Process one Strapi record:
          1. Extract title, date, file URL from JSON.
          2. For metadata_only sections: write a metadata record (no file fetch).
          3. For file sections: download file, archive to Spaces, write record.
        """
        record_json = entry["strapi_record"]
        source_url = entry["source_url"]
        run_id = entry.get("crawl_run_id", "")

        doc_type = section.get("doc_type", "other")
        language = section.get("language", "ms")
        title_field = section.get("title_field", "title")
        date_field = section.get("date_field", "")
        file_field = section.get("file_field", "")
        source_type = section.get("source_type", "collection")

        title = extract_title(record_json, title_field)
        published_at = extract_date(record_json, date_field)
        strapi_id = extract_record_id(record_json)

        # Apply --since filter early (skip records before cut-off date)
        if self.since and published_at and published_at < self.since:
            log.debug(
                {
                    "event": "skip_before_since",
                    "id": strapi_id,
                    "published_at": published_at,
                    "since": self.since,
                }
            )
            run.skipped_count += 1
            return

        # ── metadata_only: record the API entry without downloading a file ──
        if source_type == "metadata_only":
            canonical = canonical_url(
                f"{self.strapi_base}/{section['endpoint']}/{strapi_id}"
            )
            self._write_metadata_record(
                canonical_url_str=canonical,
                source_url=source_url,
                title=title,
                published_at=published_at,
                doc_type=doc_type,
                language=language,
                run=run,
                records_path=records_path,
                run_id=run_id,
            )
            return

        # ── Resolve file URL ─────────────────────────────────────────────────
        raw_file_url = extract_file_url(record_json, file_field)
        if not raw_file_url:
            log.debug(
                {
                    "event": "skip_no_file_url",
                    "id": strapi_id,
                    "section": section.get("name"),
                    "title": title[:80],
                }
            )
            run.skipped_count += 1
            return

        file_url = resolve_file_url(raw_file_url)
        can = canonical_url(file_url)

        # Host allowlist check
        if self.allowed_hosts and not is_allowed_host(can, self.allowed_hosts):
            log.warning(
                {
                    "event": "skip_disallowed_host",
                    "url": can,
                    "category": "policy",
                }
            )
            run.skipped_count += 1
            return

        # Pre-fetch dedup by canonical URL
        existing = self.state.get_by_url(can)
        if existing:
            log.debug({"event": "skip_known_url", "url": can})
            run.skipped_count += 1
            return

        # Fetch the file
        log.info(
            {
                "event": "fetch_file",
                "url": can,
                "title": title[:80],
                "section": section.get("name"),
            }
        )
        try:
            resp = self.http.get(can)
        except Exception as exc:
            log.error(
                {
                    "event": "file_fetch_error",
                    "url": can,
                    "error": str(exc),
                    "category": "network",
                }
            )
            run.failed_count += 1
            return

        data = resp.content
        http_etag = resp.headers.get("ETag", "")
        http_last_modified = resp.headers.get("Last-Modified", "")
        actual_ct = (
            resp.headers.get("Content-Type", guess_content_type(can))
            .split(";")[0]
            .strip()
        ) or guess_content_type(can)

        # Follow redirects: use final URL as canonical
        final_url = canonical_url(resp.url)

        sha256_hex = sha256_of_bytes(data)

        # Post-fetch dedup by sha256
        existing_spaces_url = self.state.get_spaces_url_by_sha256(sha256_hex)
        if existing_spaces_url:
            spaces_url = existing_spaces_url
            spaces_path = self.state.get_spaces_path_by_sha256(sha256_hex) or ""
            log.info(
                {
                    "event": "dedup_sha256_reuse",
                    "sha256": sha256_hex,
                    "spaces_url": spaces_url,
                }
            )
        else:
            spaces_path = spaces_object_path(self.site_slug, sha256_hex, final_url)
            spaces_url = self.archiver.upload(data, spaces_path, actual_ct)

        record_id = f"{sha256_hex[:16]}-{uuid.uuid4().hex[:8]}"
        record = Record(
            record_id=record_id,
            source_url=source_url,
            canonical_url=final_url,
            title=title,
            published_at=published_at,
            agency=self.agency,
            doc_type=doc_type,
            content_type=actual_ct,
            language=language,
            sha256=sha256_hex,
            spaces_bucket=self.archiver.bucket_name,
            spaces_path=spaces_path,
            spaces_url=spaces_url,
            http_etag=http_etag,
            http_last_modified=http_last_modified,
            fetched_at=_utcnow(),
            crawl_run_id=run_id,
        )

        if not self.dry_run:
            self.state.upsert_record(record)

        with open(records_path, "a", encoding="utf-8") as fh:
            fh.write(record.to_json() + "\n")

        run.new_count += 1
        log.info(
            {
                "event": "file_archived",
                "url": final_url,
                "title": title[:80],
                "published_at": published_at,
                "sha256": sha256_hex[:16],
            }
        )

    # ── Metadata-only record (no file download) ───────────────────────────────

    def _write_metadata_record(
        self,
        canonical_url_str: str,
        source_url: str,
        title: str,
        published_at: str,
        doc_type: str,
        language: str,
        run: CrawlRun,
        records_path: Path,
        run_id: str,
    ) -> None:
        """Write a record that has no downloadable file (metadata only)."""
        existing = self.state.get_by_url(canonical_url_str)
        if existing:
            log.debug({"event": "skip_known_url", "url": canonical_url_str})
            run.skipped_count += 1
            return

        sha256_hex = sha256_of_bytes(canonical_url_str.encode())
        record_id = f"{sha256_hex[:16]}-{uuid.uuid4().hex[:8]}"

        record = Record(
            record_id=record_id,
            source_url=source_url,
            canonical_url=canonical_url_str,
            title=title,
            published_at=published_at,
            agency=self.agency,
            doc_type=doc_type,
            content_type="text/html",
            language=language,
            sha256="",
            spaces_bucket="",
            spaces_path="",
            spaces_url="",
            http_etag="",
            http_last_modified="",
            fetched_at=_utcnow(),
            crawl_run_id=run_id,
        )

        if not self.dry_run:
            self.state.upsert_record(record)

        with open(records_path, "a", encoding="utf-8") as fh:
            fh.write(record.to_json() + "\n")

        run.new_count += 1
        log.info(
            {
                "event": "metadata_record_written",
                "url": canonical_url_str,
                "title": title[:80],
            }
        )
