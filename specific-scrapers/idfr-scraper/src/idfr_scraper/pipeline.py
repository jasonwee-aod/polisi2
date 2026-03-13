"""
Orchestration pipeline for idfr.gov.my.

Run flow per section:
  1. URL Discovery (varies by source_type)
     a. press_listing:      fetch /my/media-1/press → PDF entries with year dates
     b. speeches_listing:   fetch /my/media-1/speeches → PDF entries with dates
     c. publications_hub:   fetch /my/publications → direct PDFs + sub-listing URLs
     d. article_body_listing: fetch a Joomla article page → PDF entries

  2. For each discovered PDF entry:
     a. Canonicalize URL.
     b. Apply --since date filter (if date known).
     c. Pre-fetch dedup: if URL already in state → skip.
     d. Fetch PDF bytes.
     e. Compute sha256.
     f. Post-fetch dedup: if sha256 already in state → reuse gcs_uri, skip upload.
     g. Upload PDF to GCS.
     h. Write PDF record to records.jsonl and state DB.

  Publications hub special handling:
     The hub yields both direct PDF links and sub-listing page URLs.
     Sub-listing page URLs are fetched and their embedded PDF links are extracted
     using the article_body_listing extractor.

Run summary: new, changed, skipped, failed counts.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

import yaml

from .archiver import GCSArchiver, gcs_object_path, sha256_of_bytes
from .crawler import HTTPClient, canonical_url, is_allowed_host, make_absolute
from .extractor import (
    extract_article_body_listing,
    extract_press_listing,
    extract_publications_hub,
    extract_speeches_listing,
    guess_content_type,
    parse_idfr_date,
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


# ── Pipeline ──────────────────────────────────────────────────────────────────


class IDFRPipeline:
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
        self.max_pages = max_pages   # 0 = unlimited (not used for single-page listings)

        self.site_slug: str = config["site_slug"]
        self.agency: str = config["agency"]
        self.base_url: str = config["base_url"]
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
            source_type = section.get("source_type", "article_body_listing")
            section_name = section.get("name", "unknown")

            log.info(
                {
                    "event": "section_start",
                    "section": section_name,
                    "source_type": source_type,
                    "crawl_run_id": run.crawl_run_id,
                }
            )

            if source_type == "press_listing":
                listing_url = section.get("listing_url", "")
                if not listing_url:
                    log.warning(
                        {
                            "event": "section_missing_listing_url",
                            "section": section_name,
                            "category": "policy",
                        }
                    )
                    continue
                entries = list(
                    self._discover_from_press_listing(listing_url, run.crawl_run_id)
                )

            elif source_type == "speeches_listing":
                listing_urls = section.get("listing_urls", [])
                if not listing_urls and section.get("listing_url"):
                    listing_urls = [section["listing_url"]]
                if not listing_urls:
                    log.warning(
                        {
                            "event": "section_missing_listing_url",
                            "section": section_name,
                            "category": "policy",
                        }
                    )
                    continue
                entries = []
                for url in listing_urls:
                    entries.extend(
                        self._discover_from_speeches_listing(url, run.crawl_run_id)
                    )

            elif source_type == "publications_hub":
                hub_url = section.get("hub_url", "")
                if not hub_url:
                    log.warning(
                        {
                            "event": "section_missing_hub_url",
                            "section": section_name,
                            "category": "policy",
                        }
                    )
                    continue
                entries = list(
                    self._discover_from_publications_hub(hub_url, run.crawl_run_id)
                )

            else:  # article_body_listing (default)
                listing_url = section.get("listing_url", "")
                if not listing_url:
                    log.warning(
                        {
                            "event": "section_missing_listing_url",
                            "section": section_name,
                            "category": "policy",
                        }
                    )
                    continue
                entries = list(
                    self._discover_from_article_body(listing_url, run.crawl_run_id)
                )

            log.info(
                {
                    "event": "section_discovered",
                    "section": section_name,
                    "count": len(entries),
                    "crawl_run_id": run.crawl_run_id,
                }
            )

            for entry in entries:
                self._process_doc(entry, section, run, records_path)

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

    # ── Discovery: Press Listing ───────────────────────────────────────────────

    def _discover_from_press_listing(
        self, listing_url: str, run_id: str
    ) -> Iterator[dict]:
        """
        Fetch the press release listing page and yield one entry per PDF.

        All press releases are on a single page organized by year headings.
        """
        log.info(
            {
                "event": "fetch_press_listing",
                "url": listing_url,
                "crawl_run_id": run_id,
            }
        )
        try:
            resp = self.http.get(listing_url)
        except Exception as exc:
            log.error(
                {
                    "event": "press_listing_fetch_error",
                    "url": listing_url,
                    "error": str(exc),
                    "category": "network",
                    "crawl_run_id": run_id,
                }
            )
            return

        entries = extract_press_listing(resp.text, listing_url)
        log.info(
            {
                "event": "press_listing_urls_discovered",
                "url": listing_url,
                "count": len(entries),
                "crawl_run_id": run_id,
            }
        )

        for entry in entries:
            yield {
                "url": entry["href"],
                "source_url": listing_url,
                "title": entry["title"],
                "date_text": entry["date_text"],
                "crawl_run_id": run_id,
            }

    # ── Discovery: Speeches Listing ────────────────────────────────────────────

    def _discover_from_speeches_listing(
        self, listing_url: str, run_id: str
    ) -> Iterator[dict]:
        """
        Fetch a speeches listing page and yield one entry per PDF.

        Each yearly page has an HTML table with speech links.
        """
        log.info(
            {
                "event": "fetch_speeches_listing",
                "url": listing_url,
                "crawl_run_id": run_id,
            }
        )
        try:
            resp = self.http.get(listing_url)
        except Exception as exc:
            log.error(
                {
                    "event": "speeches_listing_fetch_error",
                    "url": listing_url,
                    "error": str(exc),
                    "category": "network",
                    "crawl_run_id": run_id,
                }
            )
            return

        entries = extract_speeches_listing(resp.text, listing_url)
        log.info(
            {
                "event": "speeches_listing_urls_discovered",
                "url": listing_url,
                "count": len(entries),
                "crawl_run_id": run_id,
            }
        )

        for entry in entries:
            yield {
                "url": entry["href"],
                "source_url": listing_url,
                "title": entry["title"],
                "date_text": entry["date_text"],
                "crawl_run_id": run_id,
            }

    # ── Discovery: Publications Hub ────────────────────────────────────────────

    def _discover_from_publications_hub(
        self, hub_url: str, run_id: str
    ) -> Iterator[dict]:
        """
        Fetch the publications hub and yield entries for each document.

        Direct PDF links are yielded immediately.
        Sub-listing page links are fetched and their PDFs are also yielded.
        """
        log.info(
            {
                "event": "fetch_publications_hub",
                "url": hub_url,
                "crawl_run_id": run_id,
            }
        )
        try:
            resp = self.http.get(hub_url)
        except Exception as exc:
            log.error(
                {
                    "event": "publications_hub_fetch_error",
                    "url": hub_url,
                    "error": str(exc),
                    "category": "network",
                    "crawl_run_id": run_id,
                }
            )
            return

        hub_entries = extract_publications_hub(resp.text, hub_url)
        log.info(
            {
                "event": "publications_hub_entries_found",
                "url": hub_url,
                "count": len(hub_entries),
                "crawl_run_id": run_id,
            }
        )

        for hub_entry in hub_entries:
            href = hub_entry["href"]

            # Host check
            if self.allowed_hosts and not is_allowed_host(href, self.allowed_hosts):
                log.debug(
                    {"event": "skip_external_publication_link", "url": href}
                )
                continue

            if hub_entry["is_pdf"]:
                # Direct PDF – yield immediately
                yield {
                    "url": href,
                    "source_url": hub_url,
                    "title": hub_entry["title"],
                    "date_text": "",
                    "crawl_run_id": run_id,
                }
            else:
                # Sub-listing page – fetch and extract embedded PDFs
                yield from self._discover_from_article_body(href, run_id)

    # ── Discovery: Generic Article Body Listing ────────────────────────────────

    def _discover_from_article_body(
        self, listing_url: str, run_id: str
    ) -> Iterator[dict]:
        """
        Fetch a generic Joomla article page and yield one entry per PDF found.

        Used for: newsletters, JDFR journal, other-publications, and any
        sub-listing pages discovered via the publications hub.
        """
        log.info(
            {
                "event": "fetch_article_body_listing",
                "url": listing_url,
                "crawl_run_id": run_id,
            }
        )

        if self.allowed_hosts and not is_allowed_host(listing_url, self.allowed_hosts):
            log.warning(
                {
                    "event": "skip_disallowed_listing_host",
                    "url": listing_url,
                    "category": "policy",
                }
            )
            return

        try:
            resp = self.http.get(listing_url)
        except Exception as exc:
            log.error(
                {
                    "event": "article_body_listing_fetch_error",
                    "url": listing_url,
                    "error": str(exc),
                    "category": "network",
                    "crawl_run_id": run_id,
                }
            )
            return

        entries = extract_article_body_listing(resp.text, listing_url)
        log.info(
            {
                "event": "article_body_listing_urls_discovered",
                "url": listing_url,
                "count": len(entries),
                "crawl_run_id": run_id,
            }
        )

        for entry in entries:
            yield {
                "url": entry["href"],
                "source_url": listing_url,
                "title": entry["title"],
                "date_text": entry["date_text"],
                "crawl_run_id": run_id,
            }

    # ── Document processing ───────────────────────────────────────────────────

    def _process_doc(
        self,
        entry: dict,
        section: dict,
        run: CrawlRun,
        records_path: Path,
    ) -> None:
        """
        Fetch and archive a single document (PDF or other file).

        Flow:
          1. Canonicalize URL and enforce host allowlist.
          2. Pre-fetch dedup: skip if URL already in state (unchanged).
          3. Apply --since date filter.
          4. Fetch document bytes.
          5. Post-fetch dedup by sha256.
          6. Upload to GCS (or reuse existing path).
          7. Write record to records.jsonl and state DB.
        """
        doc_url = canonical_url(entry["url"])
        doc_type = section.get("doc_type", "other")
        language = section.get("language", "ms")

        # Enforce host allowlist
        if self.allowed_hosts and not is_allowed_host(doc_url, self.allowed_hosts):
            log.warning(
                {
                    "event": "skip_disallowed_host",
                    "url": doc_url,
                    "category": "policy",
                }
            )
            run.skipped_count += 1
            return

        # Pre-fetch dedup by canonical URL
        existing = self.state.get_by_url(doc_url)
        if existing:
            # Check if content may have changed via ETag/Last-Modified
            http_last_modified = existing["http_last_modified"] or ""
            if http_last_modified:
                log.debug(
                    {"event": "skip_known_url_with_etag", "url": doc_url}
                )
            else:
                log.debug({"event": "skip_known_url", "url": doc_url})
            run.skipped_count += 1
            return

        # Apply --since date filter
        date_text = entry.get("date_text", "")
        published_at = parse_idfr_date(date_text) if date_text else ""

        if self.since and published_at and published_at < self.since:
            log.debug(
                {
                    "event": "skip_before_since",
                    "url": doc_url,
                    "published_at": published_at,
                    "since": self.since,
                }
            )
            run.skipped_count += 1
            return

        # Fetch the document
        log.info({"event": "fetch_doc", "url": doc_url})
        try:
            doc_resp = self.http.get(doc_url)
        except Exception as exc:
            log.error(
                {
                    "event": "doc_fetch_error",
                    "url": doc_url,
                    "error": str(exc),
                    "category": "network",
                }
            )
            run.failed_count += 1
            return

        # Use final URL after redirects as canonical
        final_url = canonical_url(doc_resp.url)

        # Host check on redirect destination
        if self.allowed_hosts and not is_allowed_host(final_url, self.allowed_hosts):
            log.warning(
                {
                    "event": "skip_disallowed_redirect_host",
                    "url": final_url,
                    "category": "policy",
                }
            )
            run.skipped_count += 1
            return

        # Post-redirect dedup on final URL
        if final_url != doc_url and self.state.get_by_url(final_url):
            log.debug({"event": "skip_known_final_url", "url": final_url})
            run.skipped_count += 1
            return

        data = doc_resp.content
        sha256_hex = sha256_of_bytes(data)
        http_etag = doc_resp.headers.get("ETag", "")
        http_last_modified = doc_resp.headers.get("Last-Modified", "")
        actual_ct = (
            doc_resp.headers.get("Content-Type", guess_content_type(final_url))
            .split(";")[0]
            .strip()
        ) or guess_content_type(final_url)

        # Post-fetch dedup by sha256
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
            gcs_obj = gcs_object_path(self.site_slug, sha256_hex, final_url)
            if not self.dry_run:
                gcs_uri = self.archiver.upload(data, gcs_obj, actual_ct)
            else:
                gcs_uri = f"gs://{self.archiver.bucket_name}/{gcs_obj}"

        record_id = f"{sha256_hex[:16]}-{uuid.uuid4().hex[:8]}"
        record = Record(
            record_id=record_id,
            source_url=entry.get("source_url", doc_url),
            canonical_url=final_url,
            title=entry.get("title", ""),
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
            crawl_run_id=entry.get("crawl_run_id", ""),
        )

        if not self.dry_run:
            self.state.upsert_record(record)

        with open(records_path, "a", encoding="utf-8") as fh:
            fh.write(record.to_json() + "\n")

        run.new_count += 1
        log.info(
            {
                "event": "doc_archived",
                "url": final_url,
                "title": record.title[:80],
                "published_at": published_at,
                "content_type": actual_ct,
            }
        )
