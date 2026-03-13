"""
Orchestration pipeline for dewan.selangor.gov.my.

Run flow per section:
  1. URL Discovery
     a. Sitemap mode: fetch sitemap XML → list of {url, lastmod}
     b. Listing mode: paginate through WordPress archive pages → article URLs

  2. For each discovered article URL:
     a. Canonicalize URL.
     b. Apply --since date filter (if date known at discovery time).
     c. Pre-fetch dedup: if URL already in state with same ETag → skip.
     d. Fetch article HTML.
     e. Extract metadata (title, published_at).
     f. Re-apply --since filter on extracted published_at.
     g. Compute sha256 of HTML bytes.
     h. Post-fetch dedup: if sha256 already in state → reuse gcs_uri, skip upload.
     i. Upload HTML to GCS.
     j. Write HTML record to records.jsonl and state DB.
     k. Extract embedded document links (PDFs, DOCx, etc.) from the article.
     l. For each embedded document: fetch, dedup, upload, write record.

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
    extract_embedded_doc_links,
    extract_equans_listing,
    extract_hansard_index,
    extract_hansard_session_pdfs,
    extract_wp_listing,
    extract_wp_post_meta,
    get_next_equans_page_url,
    get_next_listing_page_url,
    guess_content_type,
    parse_hansard_date,
    parse_sitemap_xml,
    parse_wp_datetime,
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


class DewanSelangorPipeline:
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
            source_type = section.get("source_type", "listing")

            if source_type == "sitemap":
                sitemap_url = section.get("sitemap_url", "")
                if not sitemap_url:
                    log.warning(
                        {
                            "event": "section_missing_sitemap_url",
                            "section": section.get("name"),
                            "category": "policy",
                        }
                    )
                    continue
                url_entries = list(
                    self._discover_from_sitemap(sitemap_url, run.crawl_run_id)
                )
            elif source_type == "hub":
                hub_page = section.get("hub_page", "")
                if not hub_page:
                    log.warning(
                        {
                            "event": "section_missing_hub_page",
                            "section": section.get("name"),
                            "category": "policy",
                        }
                    )
                    continue
                url_entries = list(
                    self._discover_from_hub(hub_page, run.crawl_run_id)
                )
            elif source_type == "equans":
                listing_url = section.get("listing_url", "")
                if not listing_url:
                    log.warning(
                        {
                            "event": "section_missing_listing_url",
                            "section": section.get("name"),
                            "category": "policy",
                        }
                    )
                    continue
                url_entries = list(
                    self._discover_from_equans(listing_url, run.crawl_run_id)
                )
            else:
                url_entries = list(
                    self._discover_from_listing(
                        section.get("listing_pages", []), run.crawl_run_id
                    )
                )

            for entry in url_entries:
                self._process_article(entry, section, run, records_path)

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

    # ── Discovery: Sitemap ────────────────────────────────────────────────────

    def _discover_from_sitemap(
        self, sitemap_url: str, run_id: str
    ) -> Iterator[dict]:
        """
        Fetch a sitemap (or sitemap index) and yield URL entries.

        Recursively follows child sitemaps in a sitemap index.
        Each yielded dict has: {url, lastmod, source_url}.
        """
        log.info(
            {
                "event": "fetch_sitemap",
                "url": sitemap_url,
                "crawl_run_id": run_id,
            }
        )
        try:
            resp = self.http.get(sitemap_url)
        except Exception as exc:
            log.error(
                {
                    "event": "sitemap_fetch_error",
                    "url": sitemap_url,
                    "error": str(exc),
                    "category": "network",
                    "crawl_run_id": run_id,
                }
            )
            return

        entries = parse_sitemap_xml(resp.text, sitemap_url)

        for entry in entries:
            if entry.get("is_sitemap_index"):
                # Recurse into child sitemap
                yield from self._discover_from_sitemap(entry["url"], run_id)
            else:
                yield {
                    "url": entry["url"],
                    "lastmod": entry.get("lastmod", ""),
                    "source_url": sitemap_url,
                    "title": "",       # populated later from page HTML
                    "date_text": entry.get("lastmod", ""),
                }

    # ── Discovery: Listing pages with pagination ──────────────────────────────

    def _discover_from_listing(
        self, listing_pages: list[dict], run_id: str
    ) -> Iterator[dict]:
        """
        Walk paginated WordPress archive pages and yield article URL entries.

        Pagination follows <a class="next page-numbers"> links until exhausted
        or max_pages is reached.
        """
        pages_fetched = 0

        for listing_cfg in listing_pages:
            current_url: Optional[str] = listing_cfg["url"]

            while current_url:
                if self.max_pages and pages_fetched >= self.max_pages:
                    log.info(
                        {
                            "event": "max_pages_reached",
                            "max_pages": self.max_pages,
                            "crawl_run_id": run_id,
                        }
                    )
                    return

                log.info(
                    {
                        "event": "fetch_listing",
                        "url": current_url,
                        "crawl_run_id": run_id,
                    }
                )
                try:
                    resp = self.http.get(current_url)
                except Exception as exc:
                    log.error(
                        {
                            "event": "listing_fetch_error",
                            "url": current_url,
                            "error": str(exc),
                            "category": "network",
                            "crawl_run_id": run_id,
                        }
                    )
                    break

                pages_fetched += 1
                items = extract_wp_listing(resp.text, current_url)

                for item in items:
                    yield {
                        "url": make_absolute(item["href"], self.base_url),
                        "lastmod": "",
                        "source_url": current_url,
                        "title": item.get("title", ""),
                        "date_text": item.get("date_text", ""),
                    }

                current_url = get_next_listing_page_url(resp.text)

    # ── Discovery: Hansard/Penyata Rasmi 3-level hub ──────────────────────────

    def _discover_from_hub(
        self, hub_page: str, run_id: str
    ) -> Iterator[dict]:
        """
        Crawl the /penyata-rasmi/ hub to discover individual sitting PDFs.

        Level 1 – hub page: lists session links grouped by year.
        Level 2 – session page: lists dated PDFs for each sitting day.
        Level 3 – PDF URL: yielded as a url entry with pre-parsed date.

        max_pages limits the number of session pages fetched (not the hub itself).
        """
        log.info({"event": "fetch_hub_page", "url": hub_page, "crawl_run_id": run_id})
        try:
            resp = self.http.get(hub_page)
        except Exception as exc:
            log.error(
                {
                    "event": "hub_fetch_error",
                    "url": hub_page,
                    "error": str(exc),
                    "category": "network",
                    "crawl_run_id": run_id,
                }
            )
            return

        sessions = extract_hansard_index(resp.text, hub_page)
        pages_fetched = 0

        for session in sessions:
            if self.max_pages and pages_fetched >= self.max_pages:
                log.info(
                    {
                        "event": "max_pages_reached",
                        "max_pages": self.max_pages,
                        "crawl_run_id": run_id,
                    }
                )
                return

            session_url = make_absolute(session["href"], self.base_url)
            session_can = canonical_url(session_url)

            if self.allowed_hosts and not is_allowed_host(session_can, self.allowed_hosts):
                log.warning(
                    {
                        "event": "skip_disallowed_host",
                        "url": session_can,
                        "category": "policy",
                    }
                )
                continue

            log.info(
                {
                    "event": "fetch_session_page",
                    "url": session_can,
                    "crawl_run_id": run_id,
                }
            )
            try:
                sess_resp = self.http.get(session_can)
            except Exception as exc:
                log.error(
                    {
                        "event": "session_fetch_error",
                        "url": session_can,
                        "error": str(exc),
                        "category": "network",
                        "crawl_run_id": run_id,
                    }
                )
                continue

            pages_fetched += 1
            pdfs = extract_hansard_session_pdfs(
                sess_resp.text, session_can, self.base_url
            )

            for pdf in pdfs:
                date_iso = parse_hansard_date(pdf.get("date_text", ""))
                yield {
                    "url": canonical_url(pdf["href"]),
                    "lastmod": date_iso,
                    "source_url": session_can,
                    "title": pdf.get("title", ""),
                    "date_text": date_iso,   # pre-parsed; works with parse_wp_datetime fallback
                    "crawl_run_id": run_id,
                }

    # ── Discovery: e-QUANS paginated question listing ─────────────────────────

    def _discover_from_equans(
        self, listing_url: str, run_id: str
    ) -> Iterator[dict]:
        """
        Walk paginated /question/page/N/ listing to discover all question URLs.

        Uses Bootstrap pagination (li.page-item.next) instead of the standard
        WordPress "next page-numbers" link.
        """
        pages_fetched = 0
        current_url: Optional[str] = listing_url

        while current_url:
            if self.max_pages and pages_fetched >= self.max_pages:
                log.info(
                    {
                        "event": "max_pages_reached",
                        "max_pages": self.max_pages,
                        "crawl_run_id": run_id,
                    }
                )
                return

            log.info(
                {
                    "event": "fetch_equans_listing",
                    "url": current_url,
                    "crawl_run_id": run_id,
                }
            )
            try:
                resp = self.http.get(current_url)
            except Exception as exc:
                log.error(
                    {
                        "event": "equans_listing_fetch_error",
                        "url": current_url,
                        "error": str(exc),
                        "category": "network",
                        "crawl_run_id": run_id,
                    }
                )
                break

            pages_fetched += 1
            items = extract_equans_listing(resp.text, current_url)

            for item in items:
                yield {
                    "url": make_absolute(item["href"], self.base_url),
                    "lastmod": "",
                    "source_url": current_url,
                    "title": item.get("title", ""),
                    "date_text": "",
                    "crawl_run_id": run_id,
                }

            current_url = get_next_equans_page_url(resp.text)

    # ── Article processing ────────────────────────────────────────────────────

    def _process_article(
        self,
        entry: dict,
        section: dict,
        run: CrawlRun,
        records_path: Path,
    ) -> None:
        """
        Fetch an article HTML page, archive it, and process any embedded documents.
        """
        article_url = canonical_url(entry["url"])
        doc_type = section.get("doc_type", "other")
        language = section.get("language", "ms")

        # Enforce host allowlist
        if self.allowed_hosts and not is_allowed_host(article_url, self.allowed_hosts):
            log.warning(
                {
                    "event": "skip_disallowed_host",
                    "url": article_url,
                    "category": "policy",
                }
            )
            run.skipped_count += 1
            return

        # Pre-fetch dedup by canonical URL + ETag
        existing = self.state.get_by_url(article_url)
        if existing:
            # Check if the server signals a change via lastmod hint
            lastmod = entry.get("lastmod", "")
            fetched_at = existing["fetched_at"] or ""
            # If lastmod is available and newer than last fetch, re-fetch
            if lastmod and fetched_at:
                lastmod_date = lastmod[:10]   # "YYYY-MM-DD"
                fetched_date = fetched_at[:10]
                if lastmod_date <= fetched_date:
                    log.debug({"event": "skip_unchanged_url", "url": article_url})
                    run.skipped_count += 1
                    return
            else:
                log.debug({"event": "skip_known_url", "url": article_url})
                run.skipped_count += 1
                return

        # Fetch the article HTML
        log.info({"event": "fetch_article", "url": article_url})
        try:
            resp = self.http.get(article_url)
        except Exception as exc:
            log.error(
                {
                    "event": "article_fetch_error",
                    "url": article_url,
                    "error": str(exc),
                    "category": "network",
                }
            )
            run.failed_count += 1
            return

        html_bytes = resp.content
        http_etag = resp.headers.get("ETag", "")
        http_last_modified = resp.headers.get("Last-Modified", "")
        actual_ct = (
            resp.headers.get("Content-Type", "text/html")
            .split(";")[0]
            .strip()
        ) or "text/html"

        # Extract metadata (HTML only; skip for PDFs and other binary types)
        is_html = actual_ct.startswith("text/html") or actual_ct == "application/xhtml+xml"
        if is_html:
            meta = extract_wp_post_meta(resp.text, article_url)
        else:
            meta = {"title": "", "published_at": ""}

        title = meta.get("title") or entry.get("title", "")
        published_at = meta.get("published_at", "")

        # Fallback: derive published_at from date_text discovered on listing/hub page
        if not published_at and entry.get("date_text"):
            published_at = parse_wp_datetime(entry["date_text"])

        # Apply --since date filter
        if self.since and published_at and published_at < self.since:
            log.debug(
                {
                    "event": "skip_before_since",
                    "url": article_url,
                    "published_at": published_at,
                    "since": self.since,
                }
            )
            run.skipped_count += 1
            return

        # Archive the HTML
        sha256_hex = sha256_of_bytes(html_bytes)
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
            gcs_obj = gcs_object_path(self.site_slug, sha256_hex, article_url)
            gcs_uri = self.archiver.upload(html_bytes, gcs_obj, actual_ct)

        # Write HTML record
        record_id = f"{sha256_hex[:16]}-{uuid.uuid4().hex[:8]}"
        record = Record(
            record_id=record_id,
            source_url=entry.get("source_url", article_url),
            canonical_url=article_url,
            title=title,
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
                "event": "article_archived",
                "url": article_url,
                "title": title[:80],
                "published_at": published_at,
            }
        )

        # Process embedded documents (PDFs, DOCx, etc.) – HTML pages only
        embedded_urls = extract_embedded_doc_links(resp.text, self.base_url) if is_html else []
        for doc_url in embedded_urls:
            self._process_embedded_doc(
                doc_url=doc_url,
                article_url=article_url,
                title=title,
                published_at=published_at,
                doc_type=doc_type,
                language=language,
                run=run,
                records_path=records_path,
            )

    # ── Embedded document processing ─────────────────────────────────────────

    def _process_embedded_doc(
        self,
        doc_url: str,
        article_url: str,
        title: str,
        published_at: str,
        doc_type: str,
        language: str,
        run: CrawlRun,
        records_path: Path,
    ) -> None:
        """Fetch and archive a single document embedded in an article."""
        can = canonical_url(doc_url)

        # Host check
        if self.allowed_hosts and not is_allowed_host(can, self.allowed_hosts):
            log.warning(
                {
                    "event": "skip_disallowed_doc_host",
                    "url": can,
                    "category": "policy",
                }
            )
            return

        # Pre-fetch dedup
        if self.state.get_by_url(can):
            log.debug({"event": "skip_known_embedded_doc", "url": can})
            run.skipped_count += 1
            return

        log.info({"event": "fetch_embedded_doc", "url": can})
        try:
            doc_resp = self.http.get(can, stream=False)
        except Exception as exc:
            log.error(
                {
                    "event": "embedded_doc_fetch_error",
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

        # Post-fetch dedup by sha256
        existing_gcs_uri = self.state.get_gcs_uri_by_sha256(sha256_hex)
        if existing_gcs_uri:
            gcs_uri = existing_gcs_uri
            gcs_obj = gcs_uri.replace(f"gs://{self.archiver.bucket_name}/", "")
        else:
            gcs_obj = gcs_object_path(self.site_slug, sha256_hex, can)
            gcs_uri = self.archiver.upload(data, gcs_obj, actual_ct)

        record_id = f"{sha256_hex[:16]}-{uuid.uuid4().hex[:8]}"
        record = Record(
            record_id=record_id,
            source_url=article_url,        # where the embed was found
            canonical_url=can,
            title=title,                   # inherit from parent article
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
            crawl_run_id="",
        )

        if not self.dry_run:
            self.state.upsert_record(record)

        with open(records_path, "a", encoding="utf-8") as fh:
            fh.write(record.to_json() + "\n")

        run.new_count += 1
        log.info(
            {
                "event": "embedded_doc_archived",
                "url": can,
                "content_type": actual_ct,
                "parent_article": article_url,
            }
        )
