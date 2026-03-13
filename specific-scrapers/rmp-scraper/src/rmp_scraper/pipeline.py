"""
Orchestration pipeline for www.rmp.gov.my (Sitefinity 6 CMS).

Site architecture
─────────────────
www.rmp.gov.my runs Telerik Sitefinity 6.3.5000.0 PE (ASP.NET). All sections
render static HTML — no JavaScript required. There is no usable sitemap.xml;
discovery uses seeded listing URLs.

Two source types supported
───────────────────────────

  listing      – Paginated news/media statement listing (Sitefinity news widget).
                 Each item is an HTML article page that may embed PDFs.
                 Pagination: path-based /page/N (sf_pagerNumeric widget).

  publications – Paginated document grid (Telerik RadGrid / rgMasterTable).
                 Each item is a direct file download (PDF/DOCX/etc.).
                 No HTML article page is fetched; files are archived directly.

Pagination strategy
────────────────────
Sitefinity appends /page/N to the base listing URL:
  Page 1: https://www.rmp.gov.my/arkib-berita/berita
  Page 2: https://www.rmp.gov.my/arkib-berita/berita/page/2
  Page 3: https://www.rmp.gov.my/arkib-berita/berita/page/3

The scraper tracks the current page number and looks for a link to page N+1
in the sf_pagerNumeric div. Stops when no such link exists or when items
are empty (whichever comes first).

Run flow per article URL (listing source_type)
───────────────────────────────────────────────
  a. Canonicalize URL.
  b. Pre-fetch dedup by canonical_url.
  c. Early --since filter using date_text from listing (if available).
  d. Fetch article HTML.
  e. Extract metadata (title, published_at).
  f. Re-apply --since filter on extracted date.
  g. Compute sha256; post-fetch dedup → reuse spaces_url if already stored.
  h. Upload HTML to Spaces.
  i. Write record to records.jsonl + state DB.
  j. Extract embedded document links; archive each.

Run flow per document URL (publications source_type)
──────────────────────────────────────────────────────
  a. Canonicalize download URL.
  b. Pre-fetch dedup by canonical_url.
  c. Fetch binary file.
  d. Compute sha256; post-fetch dedup → reuse spaces_url if already stored.
  e. Upload file to Spaces.
  f. Write record to records.jsonl + state DB.

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
    date_from_url,
    extract_embedded_doc_links,
    extract_rmp_article_meta,
    extract_sitefinity_listing_items,
    extract_sitefinity_publications,
    get_next_page_url,
    guess_content_type,
    parse_rmp_date,
)
from .models import CrawlRun, Record
from .state import StateStore

log = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 10  # kept for config compatibility; not used in path-paging


# ── Helpers ───────────────────────────────────────────────────────────────────


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _get_listing_urls(section: dict) -> list:
    """Return all seed listing URLs for a section (single or list form)."""
    urls = section.get("listing_urls", [])
    if urls:
        return list(urls)
    single = section.get("listing_url", "")
    return [single] if single else []


# ── Pipeline ──────────────────────────────────────────────────────────────────


class RMPPipeline:
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

            for seed_url in seed_urls:
                if source_type == "listing":
                    discover_fn = self._discover_from_listing
                elif source_type == "publications":
                    discover_fn = self._discover_from_publications
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

                for entry in discover_fn(seed_url, run_id):
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

    # ── Discovery: paginated Sitefinity news listing ───────────────────────────

    def _discover_from_listing(
        self, seed_url: str, run_id: str
    ) -> Iterator[dict]:
        """
        Walk a Sitefinity news listing with /page/N path-based pagination.

        Page 1 URL is the seed URL itself (no /page/1 appended).
        Subsequent pages are fetched by following the sf_pagerNumeric links.

        Stops when:
          - The extracted item list is empty.
          - No next-page link is found in the pager.
          - max_pages limit is reached.
        """
        current_url = seed_url
        current_page = 1
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

            log.info(
                {
                    "event": "fetch_listing",
                    "url": current_url,
                    "page": current_page,
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

            items = extract_sitefinity_listing_items(resp.text, current_url)

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

            # Follow next-page link from sf_pagerNumeric
            next_url = get_next_page_url(resp.text, current_url, current_page)
            if not next_url:
                log.info(
                    {
                        "event": "pagination_end",
                        "url": current_url,
                        "page": current_page,
                        "crawl_run_id": run_id,
                    }
                )
                break

            current_url = make_absolute(next_url, self.base_url)
            current_page += 1

    # ── Discovery: Sitefinity publications grid ────────────────────────────────

    def _discover_from_publications(
        self, seed_url: str, run_id: str
    ) -> Iterator[dict]:
        """
        Walk a Sitefinity RadGrid publications listing.

        Uses the same /page/N pagination as the news listing.
        Each discovered item is a direct file download URL.
        """
        current_url = seed_url
        current_page = 1
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

            log.info(
                {
                    "event": "fetch_publications_listing",
                    "url": current_url,
                    "page": current_page,
                    "crawl_run_id": run_id,
                }
            )

            try:
                resp = self.http.get(current_url)
            except Exception as exc:
                log.error(
                    {
                        "event": "publications_fetch_error",
                        "url": current_url,
                        "error": str(exc),
                        "category": "network",
                        "crawl_run_id": run_id,
                    }
                )
                break

            items = extract_sitefinity_publications(resp.text, current_url)

            if not items:
                log.info(
                    {
                        "event": "publications_empty_stop",
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
                    "_direct_file": True,
                }

            next_url = get_next_page_url(resp.text, current_url, current_page)
            if not next_url:
                log.info(
                    {
                        "event": "publications_pagination_end",
                        "url": current_url,
                        "page": current_page,
                        "crawl_run_id": run_id,
                    }
                )
                break

            current_url = make_absolute(next_url, self.base_url)
            current_page += 1

    # ── Item processing ───────────────────────────────────────────────────────

    def _process_item(
        self,
        entry: dict,
        section: dict,
        run: CrawlRun,
        records_path: Path,
    ) -> None:
        """
        Process one discovered item.

        If entry['_direct_file'] is True (publications), skip HTML fetch and
        archive the file directly. Otherwise, fetch the article HTML page,
        extract metadata, archive HTML, and process embedded documents.
        """
        item_url = canonical_url(entry["url"])
        doc_type = section.get("doc_type", "other")
        language = section.get("language", "ms")

        # Direct file (publications grid) — route without HTML fetch
        if entry.get("_direct_file"):
            self._process_embedded_doc(
                doc_url=item_url,
                article_url=entry.get("source_url", item_url),
                title=entry.get("title", ""),
                published_at=parse_rmp_date(entry.get("date_text", "")),
                doc_type=doc_type,
                language=language,
                run=run,
                records_path=records_path,
            )
            return

        # Detect direct document URLs (in case a listing embeds PDF links)
        url_lower = item_url.lower().split("?")[0]
        if any(url_lower.endswith(ext) for ext in (".pdf", ".doc", ".docx",
                                                    ".xls", ".xlsx", ".ppt",
                                                    ".pptx", ".zip")):
            self._process_embedded_doc(
                doc_url=item_url,
                article_url=entry.get("source_url", item_url),
                title=entry.get("title", ""),
                published_at=parse_rmp_date(entry.get("date_text", "")),
                doc_type=doc_type,
                language=language,
                run=run,
                records_path=records_path,
            )
            return

        # Enforce host allowlist
        if self.allowed_hosts and not is_allowed_host(item_url, self.allowed_hosts):
            log.warning(
                {
                    "event": "skip_disallowed_host",
                    "url": item_url,
                    "category": "policy",
                }
            )
            run.skipped_count += 1
            return

        # Pre-fetch dedup
        if self.state.get_by_url(item_url):
            log.debug({"event": "skip_known_url", "url": item_url})
            run.skipped_count += 1
            return

        # Early --since filter using date embedded in URL or listing date_text
        date_text = entry.get("date_text", "")
        early_date = date_from_url(item_url) or parse_rmp_date(date_text)
        if self.since and early_date and early_date < self.since:
            log.debug(
                {
                    "event": "skip_before_since_early",
                    "url": item_url,
                    "date": early_date,
                    "since": self.since,
                }
            )
            run.skipped_count += 1
            return

        # Fetch article HTML
        log.info({"event": "fetch_article", "url": item_url})
        try:
            resp = self.http.get(item_url)
        except Exception as exc:
            log.error(
                {
                    "event": "article_fetch_error",
                    "url": item_url,
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
            meta = extract_rmp_article_meta(resp.text, item_url)
        else:
            meta = {"title": "", "published_at": ""}

        title = meta.get("title") or entry.get("title", "")
        published_at = meta.get("published_at", "")

        # Fallback: use listing date_text
        if not published_at and date_text:
            published_at = parse_rmp_date(date_text)

        # Post-discovery --since filter
        if self.since and published_at and published_at < self.since:
            log.debug(
                {
                    "event": "skip_before_since",
                    "url": item_url,
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
            spaces_path = spaces_object_path(self.site_slug, sha256_hex, item_url)
            if not self.dry_run:
                spaces_url = self.archiver.upload(html_bytes, spaces_path, actual_ct)
            else:
                spaces_url = self.archiver.upload(html_bytes, spaces_path, actual_ct)

        record_id = f"{sha256_hex[:16]}-{uuid.uuid4().hex[:8]}"
        record = Record(
            record_id=record_id,
            source_url=entry.get("source_url", item_url),
            canonical_url=item_url,
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
                "url": item_url,
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
                    article_url=item_url,
                    title=title,
                    published_at=published_at,
                    doc_type=doc_type,
                    language=language,
                    run=run,
                    records_path=records_path,
                )

    # ── Embedded / direct document processing ─────────────────────────────────

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
        """Fetch and archive a single binary document."""
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
