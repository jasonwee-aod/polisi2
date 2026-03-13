"""
Orchestration pipeline for dewannegeri.johor.gov.my.

Run flow per section:
  1. URL Discovery
     a. Sitemap mode: fetch sitemap XML → list of {url, lastmod}
     b. Listing mode: paginate through Divi archive pages → article URLs

  2. For each discovered article URL:
     a. Canonicalize URL.
     b. Apply --since date filter (if date known at discovery time).
     c. Pre-fetch dedup: if URL already in state → skip.
     d. Fetch article HTML.
     e. Extract metadata (title, published_at).
     f. Re-apply --since filter on extracted published_at.
     g. Compute sha256 of HTML bytes.
     h. Post-fetch dedup: if sha256 already in state → reuse gcs_uri, skip upload.
     i. Upload HTML to GCS.
     j. Write HTML record to records.jsonl and state DB.
     k. Extract embedded document links (PDFs, WPDM downloads) from the page.
     l. For each embedded document: fetch (following redirects for WPDM tokens),
        dedup, upload, write record.

  WPDM special handling:
     When a wpdmpro package page is processed, the `a.inddl` download token URLs
     in the page are treated as embedded documents. requests follows the server
     redirect automatically, so resp.url gives the final resolved file URL. The
     canonical_url stored in the DB and records.jsonl is the final resolved URL,
     not the WPDM token URL.

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
    extract_divi_listing,
    extract_embedded_doc_links,
    extract_post_meta,
    extract_pr_hub,
    extract_ruu_hub,
    extract_sdjl_hub,
    extract_wpdm_page_meta,
    get_next_divi_page_url,
    guess_content_type,
    parse_divi_date,
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


def _is_wpdmpro_url(url: str) -> bool:
    """Heuristic: wpdmpro package pages live under /download/{slug}/."""
    from urllib.parse import urlparse
    path = urlparse(url).path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    return len(parts) >= 1 and parts[0] == "download"


# ── Pipeline ──────────────────────────────────────────────────────────────────


class DewanJohorPipeline:
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
            elif source_type == "pr_hub":
                hub_url = section.get("hub_url", "")
                if not hub_url:
                    log.warning(
                        {
                            "event": "section_missing_hub_url",
                            "section": section.get("name"),
                            "category": "policy",
                        }
                    )
                    continue
                url_entries = list(
                    self._discover_from_pr_hub(hub_url, run.crawl_run_id)
                )
            elif source_type == "sdjl_hub":
                hub_url = section.get("hub_url", "")
                if not hub_url:
                    log.warning(
                        {
                            "event": "section_missing_hub_url",
                            "section": section.get("name"),
                            "category": "policy",
                        }
                    )
                    continue
                url_entries = list(
                    self._discover_from_sdjl_hub(hub_url, run.crawl_run_id)
                )
            elif source_type == "ruu_hub":
                hub_url = section.get("hub_url", "")
                if not hub_url:
                    log.warning(
                        {
                            "event": "section_missing_hub_url",
                            "section": section.get("name"),
                            "category": "policy",
                        }
                    )
                    continue
                url_entries = list(
                    self._discover_from_ruu_hub(hub_url, run.crawl_run_id)
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
                yield from self._discover_from_sitemap(entry["url"], run_id)
            else:
                yield {
                    "url": entry["url"],
                    "lastmod": entry.get("lastmod", ""),
                    "source_url": sitemap_url,
                    "title": "",
                    "date_text": entry.get("lastmod", ""),
                    "crawl_run_id": run_id,
                }

    # ── Discovery: Listing pages with pagination ──────────────────────────────

    def _discover_from_listing(
        self, listing_pages: list[dict], run_id: str
    ) -> Iterator[dict]:
        """
        Walk paginated Divi archive pages and yield article URL entries.

        Pagination follows <div class="pagination"> <div class="alignright"> <a>
        links until exhausted or max_pages is reached.
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
                items = extract_divi_listing(resp.text, current_url)

                for item in items:
                    yield {
                        "url": make_absolute(item["href"], self.base_url),
                        "lastmod": "",
                        "source_url": current_url,
                        "title": item.get("title", ""),
                        "date_text": item.get("date_text", ""),
                        "crawl_run_id": run_id,
                    }

                current_url = get_next_divi_page_url(resp.text)

    # ── Discovery: Penyata Rasmi single-page hub (/pr/) ───────────────────────

    def _discover_from_pr_hub(
        self, hub_page: str, run_id: str
    ) -> Iterator[dict]:
        """
        Fetch the /pr/ hub page and yield one URL entry per PDF found.

        The entire page is a single HTML document with all verbatim records
        embedded across four Dewan levels, multiple sessions, and meetings.

        Each yielded entry contains a direct PDF URL plus pre-extracted
        metadata (title, date_text, dewan_level, session, meeting) so that
        _process_article can store complete provenance without re-parsing the
        hub page.

        max_pages is not applied here (the hub is a single page).
        """
        log.info(
            {
                "event": "fetch_pr_hub",
                "url": hub_page,
                "crawl_run_id": run_id,
            }
        )
        try:
            resp = self.http.get(hub_page)
        except Exception as exc:
            log.error(
                {
                    "event": "pr_hub_fetch_error",
                    "url": hub_page,
                    "error": str(exc),
                    "category": "network",
                    "crawl_run_id": run_id,
                }
            )
            return

        entries = extract_pr_hub(resp.text, hub_page)
        log.info(
            {
                "event": "pr_hub_urls_discovered",
                "url": hub_page,
                "count": len(entries),
                "crawl_run_id": run_id,
            }
        )

        for entry in entries:
            yield {
                "url": entry["href"],
                "lastmod": "",
                "source_url": hub_page,
                "title": entry["title"],
                "date_text": entry["date_text"],
                "crawl_run_id": run_id,
            }

    # ── Discovery: Soalan & Jawapan Lisan single-page hub (/sdjl/) ────────────

    def _discover_from_sdjl_hub(
        self, hub_url: str, run_id: str
    ) -> Iterator[dict]:
        """
        Fetch the /sdjl/ hub page and yield one URL entry per PDF found.

        All oral-question PDFs are embedded directly in a single Divi accordion
        page. The link text is the document date (Malay format).

        max_pages is not applied here (the hub is a single page).
        """
        log.info(
            {
                "event": "fetch_sdjl_hub",
                "url": hub_url,
                "crawl_run_id": run_id,
            }
        )
        try:
            resp = self.http.get(hub_url)
        except Exception as exc:
            log.error(
                {
                    "event": "sdjl_hub_fetch_error",
                    "url": hub_url,
                    "error": str(exc),
                    "category": "network",
                    "crawl_run_id": run_id,
                }
            )
            return

        entries = extract_sdjl_hub(resp.text, hub_url)
        log.info(
            {
                "event": "sdjl_hub_urls_discovered",
                "url": hub_url,
                "count": len(entries),
                "crawl_run_id": run_id,
            }
        )

        for entry in entries:
            yield {
                "url": entry["href"],
                "lastmod": "",
                "source_url": hub_url,
                "title": entry["title"],
                "date_text": entry["date_text"],
                "crawl_run_id": run_id,
            }

    # ── Discovery: Rang Undang-Undang / Enakmen hub ────────────────────────────

    def _discover_from_ruu_hub(
        self, hub_url: str, run_id: str
    ) -> Iterator[dict]:
        """
        Fetch the /rang-undang-undang-enakmen/ hub page and yield PDF entries.

        The page uses 4-column tables (Bil | Tarikh | Perkara | Muat Turun).
        Placeholder rows (no link in Muat Turun) are skipped by the extractor.
        max_pages is not applied here (single page).
        """
        log.info(
            {
                "event": "fetch_ruu_hub",
                "url": hub_url,
                "crawl_run_id": run_id,
            }
        )
        try:
            resp = self.http.get(hub_url)
        except Exception as exc:
            log.error(
                {
                    "event": "ruu_hub_fetch_error",
                    "url": hub_url,
                    "error": str(exc),
                    "category": "network",
                    "crawl_run_id": run_id,
                }
            )
            return

        entries = extract_ruu_hub(resp.text, hub_url)
        log.info(
            {
                "event": "ruu_hub_urls_discovered",
                "url": hub_url,
                "count": len(entries),
                "crawl_run_id": run_id,
            }
        )

        for entry in entries:
            yield {
                "url": entry["href"],
                "lastmod": "",
                "source_url": hub_url,
                "title": entry["title"],
                "date_text": entry["date_text"],
                "crawl_run_id": run_id,
            }

    # ── Article processing ────────────────────────────────────────────────────

    def _process_article(
        self,
        entry: dict,
        section: dict,
        run: CrawlRun,
        records_path: Path,
    ) -> None:
        """
        Fetch an article HTML page (or wpdmpro package page), archive it,
        and process any embedded documents.
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

        # Pre-fetch dedup by canonical URL
        existing = self.state.get_by_url(article_url)
        if existing:
            lastmod = entry.get("lastmod", "")
            fetched_at = existing["fetched_at"] or ""
            if lastmod and fetched_at:
                lastmod_date = lastmod[:10]
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

        is_html = actual_ct.startswith("text/html") or actual_ct == "application/xhtml+xml"
        is_wpdm = _is_wpdmpro_url(article_url)

        # Extract metadata
        if is_html and is_wpdm:
            meta = extract_wpdm_page_meta(resp.text, article_url)
        elif is_html:
            meta = extract_post_meta(resp.text, article_url)
        else:
            meta = {"title": "", "published_at": ""}

        title = meta.get("title") or entry.get("title", "")
        published_at = meta.get("published_at", "")

        # Fallback: derive published_at from date_text discovered at listing/sitemap
        if not published_at and entry.get("date_text"):
            date_text = entry["date_text"]
            # Try ISO format first (from sitemap lastmod), then Divi date format
            published_at = parse_wp_datetime(date_text) or parse_divi_date(date_text)

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

        # Process embedded documents (PDFs, WPDM download tokens, etc.)
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
        """
        Fetch and archive a single document embedded in an article.

        For WPDM download token URLs (?wpdmdl=ID), requests follows the
        server redirect to the actual file. The final resp.url (after redirects)
        is used as the canonical_url for deduplication and storage.
        """
        # Use the requested URL as the initial check (may be a WPDM token URL)
        initial_can = canonical_url(doc_url)

        # Host check on the initial URL
        if self.allowed_hosts and not is_allowed_host(initial_can, self.allowed_hosts):
            log.warning(
                {
                    "event": "skip_disallowed_doc_host",
                    "url": initial_can,
                    "category": "policy",
                }
            )
            return

        # Pre-fetch dedup on the initial URL (catches re-crawl of same WPDM token)
        if self.state.get_by_url(initial_can):
            log.debug({"event": "skip_known_embedded_doc", "url": initial_can})
            run.skipped_count += 1
            return

        log.info({"event": "fetch_embedded_doc", "url": initial_can})
        try:
            doc_resp = self.http.get(initial_can, stream=False)
        except Exception as exc:
            log.error(
                {
                    "event": "embedded_doc_fetch_error",
                    "url": initial_can,
                    "error": str(exc),
                    "category": "network",
                }
            )
            run.failed_count += 1
            return

        # After redirect, use the final URL as the canonical URL
        final_can = canonical_url(doc_resp.url)

        # Host check on final URL (redirect destination)
        if self.allowed_hosts and not is_allowed_host(final_can, self.allowed_hosts):
            log.warning(
                {
                    "event": "skip_disallowed_redirect_host",
                    "url": final_can,
                    "category": "policy",
                }
            )
            return

        # Post-redirect dedup check on final URL
        if self.state.get_by_url(final_can):
            log.debug({"event": "skip_known_final_url", "url": final_can})
            run.skipped_count += 1
            return

        data = doc_resp.content
        sha256_hex = sha256_of_bytes(data)
        http_etag = doc_resp.headers.get("ETag", "")
        http_last_modified = doc_resp.headers.get("Last-Modified", "")
        actual_ct = (
            doc_resp.headers.get("Content-Type", guess_content_type(final_can))
            .split(";")[0]
            .strip()
        )

        # Post-fetch dedup by sha256
        existing_gcs_uri = self.state.get_gcs_uri_by_sha256(sha256_hex)
        if existing_gcs_uri:
            gcs_uri = existing_gcs_uri
            gcs_obj = gcs_uri.replace(f"gs://{self.archiver.bucket_name}/", "")
        else:
            gcs_obj = gcs_object_path(self.site_slug, sha256_hex, final_can)
            gcs_uri = self.archiver.upload(data, gcs_obj, actual_ct)

        record_id = f"{sha256_hex[:16]}-{uuid.uuid4().hex[:8]}"
        record = Record(
            record_id=record_id,
            source_url=article_url,
            canonical_url=final_can,
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
                "url": final_can,
                "content_type": actual_ct,
                "parent_article": article_url,
            }
        )
