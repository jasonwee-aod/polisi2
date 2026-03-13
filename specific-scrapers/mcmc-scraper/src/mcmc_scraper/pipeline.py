"""
Orchestration pipeline for mcmc.gov.my (Kentico CMS / ASP.NET).

Source types supported per section:

  listing     – Paginated listing pages (?page=N); article_list or media_box archetype.
  acts_hub    – Single /en/legal/acts hub page; <h2> per Act + sibling PDF/detail links.
  static_page – A single content page (e.g. /en/legal/dispute-resolution); no sub-items.

Run flow for each discovered URL:
  a. Canonicalize URL.
  b. If URL is a direct document (PDF/DOC/…) → archive without HTML fetch.
  c. Pre-fetch dedup by canonical URL.
  d. Apply --since date filter (early exit if date known from listing).
  e. Fetch HTML page.
  f. Extract metadata (title, published_at).
  g. Re-apply --since filter on extracted date.
  h. Compute sha256; post-fetch dedup → reuse spaces_url if already stored.
  i. Upload HTML to Spaces.
  j. Write record to records.jsonl + state DB.
  k. Extract embedded document links; archive each.

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
from .crawler import HTTPClient, canonical_url, is_allowed_host, make_absolute
from .extractor import (
    extract_acts_hub_items,
    extract_article_list_items,
    extract_article_meta,
    extract_embedded_doc_links,
    extract_media_box_items,
    get_next_page_number,
    guess_content_type,
    parse_mcmc_date,
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


def _build_listing_url(base: str, page: int) -> str:
    """Append ?page=N (or &page=N if query already present)."""
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}page={page}"


# ── Pipeline ──────────────────────────────────────────────────────────────────


class MCMCPipeline:
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

            if source_type == "acts_hub":
                hub_url = section.get("hub_url", "")
                if not hub_url:
                    log.warning({"event": "section_missing_hub_url",
                                 "section": section.get("name"), "category": "policy"})
                    continue
                url_entries = list(self._discover_from_acts_hub(hub_url, run_id))

            elif source_type == "static_page":
                page_url = section.get("page_url", "")
                if not page_url:
                    log.warning({"event": "section_missing_page_url",
                                 "section": section.get("name"), "category": "policy"})
                    continue
                url_entries = list(self._discover_from_static_page(page_url, run_id))

            else:  # "listing" (default) – paginated article_list / media_box
                listing_url = section.get("listing_url", "")
                if not listing_url:
                    log.warning({"event": "section_missing_listing_url",
                                 "section": section.get("name"), "category": "policy"})
                    continue
                archetype = section.get("listing_archetype", "article_list")
                url_entries = list(
                    self._discover_from_listing(listing_url, archetype, run_id)
                )

            for entry in url_entries:
                self._process_item(entry, section, run, records_path)

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

    # ── Discovery: paginated listing pages ────────────────────────────────────

    def _discover_from_listing(
        self, listing_url: str, archetype: str, run_id: str
    ) -> Iterator[dict]:
        """
        Walk paginated MCMC listing pages and yield URL entries.

        Pagination: ?page=N (increment until empty page or max_pages reached).
        Archetype selects the extraction function.
        """
        page = 1
        pages_fetched = 0

        while True:
            if self.max_pages and pages_fetched >= self.max_pages:
                log.info(
                    {
                        "event": "max_pages_reached",
                        "max_pages": self.max_pages,
                        "crawl_run_id": run_id,
                    }
                )
                return

            current_url = _build_listing_url(listing_url, page)

            log.info(
                {
                    "event": "fetch_listing",
                    "url": current_url,
                    "archetype": archetype,
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

            if archetype == "media_box":
                items = extract_media_box_items(resp.text, current_url)
            else:
                items = extract_article_list_items(resp.text, current_url)

            if not items:
                log.info(
                    {
                        "event": "listing_empty_stop",
                        "url": current_url,
                        "crawl_run_id": run_id,
                    }
                )
                break

            for item in items:
                yield {
                    "url": make_absolute(item["href"], self.base_url),
                    "source_url": current_url,
                    "title": item.get("title", ""),
                    "date_text": item.get("date_text", ""),
                    "pdf_href": item.get("pdf_href", ""),
                    "crawl_run_id": run_id,
                }

            # Detect last page via pagination
            next_page_num = get_next_page_number(resp.text)
            if next_page_num is None:
                log.info(
                    {
                        "event": "pagination_end",
                        "url": current_url,
                        "crawl_run_id": run_id,
                    }
                )
                break

            page = next_page_num

    # ── Discovery: acts hub (single non-paginated page) ──────────────────────

    def _discover_from_acts_hub(self, hub_url: str, run_id: str) -> Iterator[dict]:
        """
        Fetch /en/legal/acts and yield one entry per Act.

        Each Act entry carries:
          - url        → the Act detail page (will be archived as HTML)
          - doc_hrefs  → direct PDF/DOC links found on the hub row

        When a direct document URL is in ``doc_hrefs`` it is yielded as a
        separate entry so ``_process_item`` can route it to
        ``_process_embedded_doc`` (detected by file extension).
        """
        can_hub = canonical_url(hub_url)
        log.info({"event": "fetch_acts_hub", "url": can_hub, "crawl_run_id": run_id})
        try:
            resp = self.http.get(can_hub)
        except Exception as exc:
            log.error({"event": "acts_hub_fetch_error", "url": can_hub,
                       "error": str(exc), "category": "network",
                       "crawl_run_id": run_id})
            return

        items = extract_acts_hub_items(resp.text, can_hub)

        for item in items:
            # Yield the detail page URL (will be fetched and archived as HTML)
            if item["detail_href"]:
                yield {
                    "url": make_absolute(item["detail_href"], self.base_url),
                    "source_url": can_hub,
                    "title": item["title"],
                    "date_text": "",
                    "pdf_href": "",
                    "doc_hrefs": [],
                    "crawl_run_id": run_id,
                }

            # Yield each direct document found on the hub listing row
            for doc_href in item["doc_hrefs"]:
                yield {
                    "url": make_absolute(doc_href, self.base_url),
                    "source_url": can_hub,
                    "title": item["title"],
                    "date_text": "",
                    "pdf_href": "",
                    "doc_hrefs": [],
                    "crawl_run_id": run_id,
                }

    # ── Discovery: single static content page ────────────────────────────────

    def _discover_from_static_page(self, page_url: str, run_id: str) -> Iterator[dict]:
        """
        Yield the static page itself as a single entry.

        The page HTML is archived and all embedded document links are
        extracted inside ``_process_item`` (same code path as article pages).
        """
        log.info({"event": "static_page_queued", "url": page_url,
                  "crawl_run_id": run_id})
        yield {
            "url": canonical_url(page_url),
            "source_url": page_url,
            "title": "",        # extracted when the page is fetched
            "date_text": "",
            "pdf_href": "",
            "doc_hrefs": [],
            "crawl_run_id": run_id,
        }

    # ── Item processing ───────────────────────────────────────────────────────

    def _process_item(
        self,
        entry: dict,
        section: dict,
        run: CrawlRun,
        records_path: Path,
    ) -> None:
        """
        Fetch an article detail page, archive it, and process embedded documents.

        If the entry URL itself ends with a document extension (PDF, DOC, …) it
        is routed directly to ``_process_embedded_doc`` without an HTML fetch.
        This handles direct document links yielded by ``_discover_from_acts_hub``.
        """
        article_url = canonical_url(entry["url"])
        doc_type = section.get("doc_type", "other")
        language = section.get("language", "en")

        # Shortcut: entry URL is itself a document (e.g. direct PDF from acts hub)
        url_lower = article_url.lower().split("?")[0]
        if any(url_lower.endswith(ext) for ext in (".pdf", ".doc", ".docx",
                                                    ".xls", ".xlsx", ".ppt",
                                                    ".pptx", ".zip")):
            self._process_embedded_doc(
                doc_url=article_url,
                article_url=entry.get("source_url", article_url),
                title=entry.get("title", ""),
                published_at="",
                doc_type=doc_type,
                language=language,
                run=run,
                records_path=records_path,
            )
            return

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
            log.debug({"event": "skip_known_url", "url": article_url})
            run.skipped_count += 1
            return

        # Early --since filter using date discovered on listing page
        date_text = entry.get("date_text", "")
        if self.since and date_text:
            early_date = parse_mcmc_date(date_text)
            if early_date and early_date < self.since:
                log.debug(
                    {
                        "event": "skip_before_since_early",
                        "url": article_url,
                        "date": early_date,
                        "since": self.since,
                    }
                )
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
            resp.headers.get("Content-Type", "text/html").split(";")[0].strip()
        ) or "text/html"

        is_html = actual_ct.startswith("text/html") or actual_ct == "application/xhtml+xml"

        if is_html:
            meta = extract_article_meta(resp.text, article_url)
        else:
            meta = {"title": "", "published_at": ""}

        title = meta.get("title") or entry.get("title", "")
        published_at = meta.get("published_at", "")

        # Fallback: use date_text from listing if detail page has no date
        if not published_at and date_text:
            published_at = parse_mcmc_date(date_text)

        # Post-discovery --since filter
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
            spaces_path = spaces_object_path(self.site_slug, sha256_hex, article_url)
            spaces_url = self.archiver.upload(html_bytes, spaces_path, actual_ct)

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
            spaces_bucket=self.archiver.bucket_name,
            spaces_path=spaces_path,
            spaces_url=spaces_url,
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

        # Process direct PDF link found on the listing row (article_list only)
        pdf_href = entry.get("pdf_href", "")
        if pdf_href:
            pdf_url = make_absolute(pdf_href, self.base_url)
            self._process_embedded_doc(
                doc_url=pdf_url,
                article_url=article_url,
                title=title,
                published_at=published_at,
                doc_type=doc_type,
                language=language,
                run=run,
                records_path=records_path,
            )

        # Process embedded documents from article HTML
        embedded_urls = (
            extract_embedded_doc_links(resp.text, self.base_url) if is_html else []
        )
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

        # Follow redirect URL as canonical (handles getattachment redirects)
        final_url = canonical_url(doc_resp.url)

        # Post-fetch dedup by sha256
        existing_spaces_url = self.state.get_spaces_url_by_sha256(sha256_hex)
        if existing_spaces_url:
            spaces_url = existing_spaces_url
            spaces_path = self.state.get_spaces_path_by_sha256(sha256_hex) or ""
        else:
            spaces_path = spaces_object_path(self.site_slug, sha256_hex, final_url)
            spaces_url = self.archiver.upload(data, spaces_path, actual_ct)

        record_id = f"{sha256_hex[:16]}-{uuid.uuid4().hex[:8]}"
        record = Record(
            record_id=record_id,
            source_url=article_url,
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
                "url": final_url,
                "content_type": actual_ct,
                "parent_article": article_url,
            }
        )
