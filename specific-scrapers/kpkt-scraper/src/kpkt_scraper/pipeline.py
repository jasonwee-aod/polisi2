"""
Orchestration pipeline: listing-page fetch → extract → download → archive → state.

Run flow per section listing page:
  1. Fetch listing HTML.
  2. Extract item list (title, date_text, href).
  3. For each item:
     a. Canonicalize URL.
     b. Apply --since date filter.
     c. Pre-fetch dedup: if URL already in state with same ETag → skip.
     d. Fetch raw document bytes.
     e. Compute sha256.
     f. Post-fetch dedup: if sha256 already in state → reuse gcs_uri, skip upload.
     g. Upload to GCS.
     h. Write record to records.jsonl and state DB.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from .archiver import GCSArchiver, gcs_object_path, sha256_of_bytes
from .crawler import HTTPClient, canonical_url, make_absolute
from .extractor import (
    extract_container_attachments,
    extract_downloads_hub,
    extract_siaran_media,
    guess_content_type,
    parse_malay_date,
)
from .models import CrawlRun, Record
from .state import StateStore

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _dispatch_extractor(
    doc_type: str, html: str, source_url: str, base_url: str
) -> list[dict]:
    """
    Route to the correct section extractor based on doc_type.

    Returns a list of item dicts ready for _process_item.
    Hub pages return an empty list (sub-pages are handled separately via
    _dispatch_hub_extractor).
    """
    if doc_type == "press_release":
        return extract_siaran_media(html, source_url)
    if doc_type in ("legislation", "form", "report", "notice", "other"):
        return extract_container_attachments(html, source_url, base_url, doc_type)
    log.warning(
        {
            "event": "no_extractor",
            "doc_type": doc_type,
            "url": source_url,
            "category": "parse",
        }
    )
    return []


# ── Pipeline ──────────────────────────────────────────────────────────────────


class KPKTPipeline:
    def __init__(
        self,
        config: dict,
        state: StateStore,
        archiver: GCSArchiver,
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
        self.since = since           # "YYYY-MM-DD" lower bound, inclusive
        self.max_pages = max_pages   # 0 = unlimited

        self.site_slug: str = config["site_slug"]
        self.agency: str = config["agency"]
        self.base_url: str = config["base_url"]

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

        page_count = 0
        for section in self.config.get("sections", []):
            for listing in section.get("listing_pages", []):
                if self.max_pages and page_count >= self.max_pages:
                    log.info(
                        {
                            "event": "max_pages_reached",
                            "max_pages": self.max_pages,
                            "crawl_run_id": run.crawl_run_id,
                        }
                    )
                    break
                self._process_listing(listing["url"], section, run, records_path)
                page_count += 1

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

    # ── Listing page ──────────────────────────────────────────────────────────

    def _process_listing(
        self,
        url: str,
        section: dict,
        run: CrawlRun,
        records_path: Path,
    ) -> None:
        log.info(
            {"event": "fetch_listing", "url": url, "crawl_run_id": run.crawl_run_id}
        )
        try:
            resp = self.http.get(url)
        except Exception as exc:
            log.error(
                {
                    "event": "listing_fetch_error",
                    "url": url,
                    "error": str(exc),
                    "category": "network",
                    "crawl_run_id": run.crawl_run_id,
                }
            )
            run.failed_count += 1
            return

        doc_type = section.get("doc_type", "other")
        language = section.get("language", "ms")

        # ── Hub page: follow links to sub-pages ───────────────────────────────
        if section.get("page_type") == "hub":
            sub_urls = extract_downloads_hub(resp.text, url, self.base_url)
            for sub_url in sub_urls:
                self._process_listing(
                    sub_url,
                    {**section, "page_type": "attachments"},  # sub-pages are attachment pages
                    run,
                    records_path,
                )
            return

        # ── Regular listing: extract and process document items ───────────────
        raw_items = _dispatch_extractor(doc_type, resp.text, url, self.base_url)

        for item in raw_items:
            effective_doc_type = item.get("doc_type", doc_type)
            self._process_item(item, effective_doc_type, language, run, records_path)

    # ── Individual document ───────────────────────────────────────────────────

    def _process_item(
        self,
        item: dict,
        doc_type: str,
        language: str,
        run: CrawlRun,
        records_path: Path,
    ) -> None:
        # Build and canonicalize URL
        abs_url = make_absolute(item["href"], self.base_url)
        can = canonical_url(abs_url)
        published_at = parse_malay_date(item.get("date_text", ""))

        # ── Date filter ───────────────────────────────────────────────────────
        if self.since and published_at and published_at < self.since:
            log.debug(
                {
                    "event": "skip_before_since",
                    "url": can,
                    "published_at": published_at,
                    "since": self.since,
                }
            )
            run.skipped_count += 1
            return

        # ── Pre-fetch dedup by canonical URL ──────────────────────────────────
        existing = self.state.get_by_url(can)
        if existing:
            log.debug({"event": "skip_known_url", "url": can})
            run.skipped_count += 1
            return

        # ── Fetch document ────────────────────────────────────────────────────
        log.info({"event": "fetch_document", "url": can})
        try:
            doc_resp = self.http.get(can, stream=False)
        except Exception as exc:
            log.error(
                {
                    "event": "doc_fetch_error",
                    "url": can,
                    "error": str(exc),
                    "category": "network",
                }
            )
            run.failed_count += 1
            return

        data = doc_resp.content
        sha256_hex = sha256_of_bytes(data)
        http_etag = doc_resp.headers.get("ETag", "")
        http_last_modified = doc_resp.headers.get("Last-Modified", "")
        actual_ct = (
            doc_resp.headers.get("Content-Type", guess_content_type(can))
            .split(";")[0]
            .strip()
        )

        # ── Post-fetch dedup by sha256 ────────────────────────────────────────
        existing_gcs_uri = self.state.get_gcs_uri_by_sha256(sha256_hex)
        if existing_gcs_uri:
            gcs_uri = existing_gcs_uri
            gcs_obj = gcs_uri.replace(f"gs://{self.archiver.bucket_name}/", "")
            log.info(
                {
                    "event": "dedup_sha256_reuse",
                    "sha256": sha256_hex,
                    "gcs_uri": gcs_uri,
                }
            )
        else:
            gcs_obj = gcs_object_path(self.site_slug, sha256_hex, can)
            gcs_uri = self.archiver.upload(data, gcs_obj, actual_ct)

        # ── Build record ──────────────────────────────────────────────────────
        record_id = f"{sha256_hex[:16]}-{uuid.uuid4().hex[:8]}"
        record = Record(
            record_id=record_id,
            source_url=item["source_url"],
            canonical_url=can,
            title=item.get("title", ""),
            published_at=published_at,
            agency=self.agency,
            doc_type=doc_type,
            content_type=actual_ct,
            language=language,
            sha256=sha256_hex,
            gcs_bucket=self.archiver.bucket_name,
            gcs_object=gcs_obj,
            gcs_uri=gcs_uri,
            http_etag=http_etag,
            http_last_modified=http_last_modified,
            fetched_at=_utcnow(),
            crawl_run_id=run.crawl_run_id,
        )

        if not self.dry_run:
            self.state.upsert_record(record)

        with open(records_path, "a", encoding="utf-8") as fh:
            fh.write(record.to_json() + "\n")

        run.new_count += 1
        log.info(
            {
                "event": "record_saved",
                "url": can,
                "title": record.title[:80],
                "published_at": record.published_at,
            }
        )
