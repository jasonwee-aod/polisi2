"""
Orchestration pipeline for www.moh.gov.my (Joomla 4 CMS).

Site architecture
─────────────────
www.moh.gov.my runs Joomla 4 with com_content. All sections render static
HTML — no JavaScript required. There is no sitemap.xml; discovery uses
seeded listing URLs with Joomla offset-based pagination (?start=N).

Source type supported: listing (default, only type needed)

Per-section listing URL formats
────────────────────────────────
  listing_url          – single seed URL string
  listing_urls         – explicit list of seed URLs
  listing_url_template – URL with a {year} placeholder, paired with
                         year_from / year_to to generate year-based URLs
                         (used for media_statements, e.g. .../media-statement/2026)

Pagination: offset-based ?start=N, increments by page_size (default 10).
Stops when a listing page returns zero items (one extra empty request per
section at the end).

Run flow per article URL
────────────────────────
  a. Canonicalize URL.
  b. If URL is a direct document (PDF/DOCX/…) → archive without HTML fetch.
  c. Pre-fetch dedup by canonical_url.
  d. Early --since filter using date_text discovered on the listing page.
  e. Fetch article HTML.
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
    extract_embedded_doc_links,
    extract_joomla_listing_items,
    extract_moh_article_meta,
    guess_content_type,
    has_more_pages,
    parse_moh_date,
)
from .models import CrawlRun, Record
from .state import StateStore

log = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 10


# ── Helpers ───────────────────────────────────────────────────────────────────


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _build_listing_url(base: str, offset: int) -> str:
    """
    Append Joomla offset parameter to a listing URL.

    Examples:
        _build_listing_url("https://www.moh.gov.my/en/media-kkm/...", 0)
            → "https://www.moh.gov.my/en/media-kkm/..."
        _build_listing_url("https://www.moh.gov.my/en/media-kkm/...", 10)
            → "https://www.moh.gov.my/en/media-kkm/...?start=10"
    """
    if offset == 0:
        return base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}start={offset}"


def _get_listing_urls(section: dict) -> list:
    """
    Return all seed listing URLs for a section.

    Supports three config forms:
      1. listing_url: "https://..."             → single URL
      2. listing_urls: [...]                    → explicit list
      3. listing_url_template: "...{year}..."   → generated from year_from..year_to
         (years are yielded newest-first)
    """
    # Form 3: year-range template
    template = section.get("listing_url_template", "")
    if template:
        year_from = int(section.get("year_from", 2020))
        year_to = int(section.get("year_to", 2026))
        # Iterate newest year first so incremental --since works well
        return [template.format(year=y) for y in range(year_to, year_from - 1, -1)]

    # Form 2: explicit list
    urls = section.get("listing_urls", [])
    if urls:
        return list(urls)

    # Form 1: single URL
    single = section.get("listing_url", "")
    return [single] if single else []


# ── Pipeline ──────────────────────────────────────────────────────────────────


class MOHPipeline:
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
        self.base_url: str = config["base_url"]
        self.allowed_hosts: frozenset = frozenset(config.get("allowed_hosts", []))

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

            if source_type != "listing":
                log.warning(
                    {
                        "event": "unknown_source_type",
                        "source_type": source_type,
                        "section": section.get("name"),
                        "category": "policy",
                    }
                )
                continue

            seed_urls = _get_listing_urls(section)
            if not seed_urls:
                log.warning(
                    {
                        "event": "section_no_urls",
                        "section": section.get("name"),
                        "category": "policy",
                    }
                )
                continue

            page_size = int(section.get("page_size", _DEFAULT_PAGE_SIZE))

            for seed_url in seed_urls:
                for entry in self._discover_from_listing(
                    seed_url, page_size, run_id
                ):
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

    # ── Discovery: paginated Joomla listing ───────────────────────────────────

    def _discover_from_listing(
        self, seed_url: str, page_size: int, run_id: str
    ) -> Iterator[dict]:
        """
        Walk a Joomla 4 category listing page with ?start=N offset pagination.

        Stops when:
          - The extracted item list is empty (definitive end-of-listing).
          - has_more_pages() returns False (early-stop from pagination widget).
          - max_pages limit is reached.
        """
        offset = 0
        pages_fetched = 0

        while True:
            if self.max_pages and pages_fetched >= self.max_pages:
                log.info(
                    {
                        "event": "max_pages_reached",
                        "max_pages": self.max_pages,
                        "seed_url": seed_url,
                        "crawl_run_id": run_id,
                    }
                )
                return

            current_url = _build_listing_url(seed_url, offset)

            log.info(
                {
                    "event": "fetch_listing",
                    "url": current_url,
                    "offset": offset,
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

            items = extract_joomla_listing_items(resp.text, current_url)

            if not items:
                log.info(
                    {
                        "event": "listing_empty_stop",
                        "url": current_url,
                        "crawl_run_id": run_id,
                    }
                )
                break

            pages_fetched += 1

            for item in items:
                yield {
                    "url": make_absolute(item["href"], self.base_url),
                    "source_url": current_url,
                    "title": item.get("title", ""),
                    "date_text": item.get("date_text", ""),
                    "crawl_run_id": run_id,
                }

            # Early stop: pagination widget has no further pages
            if not has_more_pages(resp.text, offset):
                log.info(
                    {
                        "event": "pagination_end",
                        "url": current_url,
                        "offset": offset,
                        "crawl_run_id": run_id,
                    }
                )
                break

            offset += page_size

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
        is routed directly to _process_embedded_doc without an HTML fetch.
        """
        article_url = canonical_url(entry["url"])
        doc_type = section.get("doc_type", "other")
        language = section.get("language", "ms")

        # Direct document: route to embedded-doc handler
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

        # Pre-fetch dedup
        if self.state.get_by_url(article_url):
            log.debug({"event": "skip_known_url", "url": article_url})
            run.skipped_count += 1
            return

        # Early --since filter using date from listing
        date_text = entry.get("date_text", "")
        if self.since and date_text:
            early_date = parse_moh_date(date_text)
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

        # Fetch article HTML
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
            meta = extract_moh_article_meta(resp.text, article_url)
        else:
            meta = {"title": "", "published_at": ""}

        title = meta.get("title") or entry.get("title", "")
        published_at = meta.get("published_at", "")

        # Fallback: use listing date_text if detail page has no date
        if not published_at and date_text:
            published_at = parse_moh_date(date_text)

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

        # Process embedded documents from article HTML
        if is_html:
            embedded_urls = extract_embedded_doc_links(resp.text, self.base_url)
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

        # Host allowlist check
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
        ) or guess_content_type(can)

        # Use final (post-redirect) URL as canonical
        final_url = canonical_url(doc_resp.url)

        # Post-fetch dedup
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
