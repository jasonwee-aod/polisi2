from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from moe_scraper.config import SiteConfig
from moe_scraper.discovery import discover_listing_items, discover_urls
from moe_scraper.http_client import HttpClient, HttpResult, RobotsPolicy
from moe_scraper.models import CrawlStats, ListingItem
from moe_scraper.parser import parse_detail_page
from moe_scraper.state import StateStore, UrlState
from moe_scraper.storage import DoSpacesArchiver
from moe_scraper.utils import (
    canonicalize_url,
    doc_type_from_text,
    is_allowed_host,
    is_downloadable_url,
    parse_publication_date,
    sha256_bytes,
    stable_record_id,
    utc_now_iso,
)


class MoeCrawler:
    def __init__(self, config: SiteConfig, output_root: Path, state_path: Path, crawl_run_id: str) -> None:
        self.config = config
        self.output_root = output_root
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.records_path = self.output_root / "records.jsonl"
        self.runs_path = self.output_root / "crawl_runs.jsonl"

        self.state = StateStore(state_path)
        self.http = HttpClient(
            user_agent="moe-gov-my-scraper/0.1 (+https://www.moe.gov.my)",
            crawl_run_id=crawl_run_id,
            warmup_url=config.base_url,
        )
        self.robots = RobotsPolicy(config.base_url, "*")
        self.crawl_run_id = crawl_run_id
        self.logger = logging.getLogger(__name__)

    def close(self) -> None:
        self.http.close()
        self.state.close()

    def run(self, since: str | None, max_pages: int, dry_run: bool) -> CrawlStats:
        stats = CrawlStats()
        since_date = date.fromisoformat(since) if since else None
        allowed_hosts = set(self.config.allowed_hosts)

        bucket_name = os.getenv("DO_SPACES_BUCKET", "")
        archiver = (
            DoSpacesArchiver(
                bucket_name=bucket_name,
                region=os.getenv("DO_SPACES_REGION", "sgp1"),
                endpoint=os.getenv("DO_SPACES_ENDPOINT", ""),
                key=os.getenv("DO_SPACES_KEY", ""),
                secret=os.getenv("DO_SPACES_SECRET", ""),
            )
            if (bucket_name and not dry_run)
            else None
        )

        # Primary discovery: listing pages carry reliable title + date metadata.
        listing_items = discover_listing_items(self.config, self.http, max_pages=max_pages)
        listing_meta: dict[str, ListingItem] = {
            canonicalize_url(item.url): item for item in listing_items
        }

        # Secondary discovery: sitemaps/feeds — adds URLs without listing metadata.
        # For MOE the sitemaps are unavailable, but this keeps the pipeline general.
        for url in discover_urls(self.config, self.http, max_pages=max_pages):
            canonical = canonicalize_url(url)
            if canonical not in listing_meta:
                listing_meta[canonical] = ListingItem(url=url, title="", date_str=None)

        discovered = list(listing_meta.keys())
        stats.discovered = len(discovered)

        seen_canonical: set[str] = set()

        for canonical in discovered[:max_pages]:
            seen_canonical.add(canonical)
            item = listing_meta[canonical]
            url = item.url

            if not is_allowed_host(canonical, allowed_hosts):
                self._log_policy_skip(url, "host_not_allowed")
                stats.skipped += 1
                continue
            if not self.robots.can_fetch(url):
                self._log_policy_skip(url, "robots_disallow")
                stats.skipped += 1
                continue

            try:
                response = self.http.fetch(url)
                stats.fetched += 1

                if "html" in response.content_type:
                    detail = parse_detail_page(response.content, response.url)

                    # Prefer listing metadata: more reliable than the detail page
                    # which has an empty <h1> and a generic title tag.
                    title = item.title or detail.title
                    if item.date_str:
                        published_at = parse_publication_date(item.date_str)
                    else:
                        published_at = detail.published_at
                    language = detail.language or self.config.default_language

                    if since_date and published_at and date.fromisoformat(published_at) < since_date:
                        stats.skipped += 1
                        continue

                    changed = self._archive_response(
                        response=response,
                        source_url=url,
                        title=title,
                        published_at=published_at,
                        language=language,
                        dry_run=dry_run,
                        archiver=archiver,
                        stats=stats,
                    )
                    if changed is True:
                        stats.changed += 1

                    for file_url in detail.file_links:
                        if not self.robots.can_fetch(file_url):
                            self._log_policy_skip(file_url, "robots_disallow")
                            stats.skipped += 1
                            continue
                        if not is_allowed_host(file_url, allowed_hosts):
                            self._log_policy_skip(file_url, "host_not_allowed")
                            stats.skipped += 1
                            continue
                        try:
                            file_response = self.http.fetch(file_url)
                            stats.fetched += 1
                            changed_file = self._archive_response(
                                response=file_response,
                                source_url=url,
                                title=title,
                                published_at=published_at,
                                language=language,
                                dry_run=dry_run,
                                archiver=archiver,
                                stats=stats,
                            )
                            if changed_file is True:
                                stats.changed += 1
                        except Exception as exc:  # noqa: BLE001
                            self._log_error(file_url, "network", str(exc))
                            stats.failed += 1

                elif is_downloadable_url(response.url):
                    fallback_title = item.title or urlparse(url).path.rsplit("/", 1)[-1] or "Document"
                    changed = self._archive_response(
                        response=response,
                        source_url=url,
                        title=fallback_title,
                        published_at=parse_publication_date(item.date_str),
                        language=self.config.default_language,
                        dry_run=dry_run,
                        archiver=archiver,
                        stats=stats,
                    )
                    if changed is True:
                        stats.changed += 1
                else:
                    stats.skipped += 1

            except Exception as exc:  # noqa: BLE001
                self._log_error(url, "network", str(exc))
                stats.failed += 1

        self.state.mark_inactive_missing(seen_canonical, utc_now_iso())
        self._write_run_summary(stats, dry_run=dry_run, since=since, max_pages=max_pages)
        return stats

    def _archive_response(
        self,
        response: HttpResult,
        source_url: str,
        title: str,
        published_at: str | None,
        language: str,
        dry_run: bool,
        archiver: DoSpacesArchiver | None,
        stats: CrawlStats,
    ) -> bool | None:
        fetched_at = utc_now_iso()
        canonical = canonicalize_url(response.url)
        record_id = stable_record_id(canonical)

        existing_url_state = self.state.get_url_state(canonical)
        header_etag = response.headers.get("etag")
        header_last_modified = response.headers.get("last-modified")

        if self._is_unchanged(existing_url_state, header_etag, header_last_modified):
            stats.skipped += 1
            return None

        sha256 = sha256_bytes(response.content)
        payload_state = self.state.get_payload(sha256)

        gcs_bucket = None
        gcs_object = None
        gcs_uri = None

        if payload_state:
            stats.deduped += 1
            gcs_bucket = payload_state.gcs_bucket
            gcs_object = payload_state.gcs_object
            gcs_uri = payload_state.gcs_uri
        elif archiver is not None:
            filename = urlparse(response.url).path.rsplit("/", 1)[-1] or "index.html"
            upload = archiver.upload_bytes(
                site_slug=self.config.site_slug,
                sha256=sha256,
                original_filename=filename,
                payload=response.content,
                fetched_at=fetched_at,
                content_type=response.content_type,
                source_url=source_url,
            )
            if upload is not None:
                gcs_bucket = upload.bucket
                gcs_object = upload.object_path
                gcs_uri = upload.uri
                stats.uploaded += 1

        self.state.upsert_payload(
            sha256=sha256,
            gcs_bucket=gcs_bucket,
            gcs_object=gcs_object,
            gcs_uri=gcs_uri,
            created_at=fetched_at,
        )
        self.state.upsert_record(
            canonical_url=canonical,
            source_url=source_url,
            sha256=sha256,
            http_etag=header_etag,
            http_last_modified=header_last_modified,
            gcs_bucket=gcs_bucket,
            gcs_object=gcs_object,
            gcs_uri=gcs_uri,
            fetched_at=fetched_at,
        )

        final_published = published_at or parse_publication_date(header_last_modified)
        doc_type = doc_type_from_text(response.url, title)

        record = {
            "record_id": record_id,
            "source_url": source_url,
            "canonical_url": canonical,
            "title": title,
            "published_at": final_published,
            "agency": self.config.agency,
            "doc_type": doc_type,
            "content_type": response.content_type,
            "language": language,
            "sha256": sha256,
            "gcs_bucket": gcs_bucket,
            "gcs_object": gcs_object,
            "gcs_uri": gcs_uri,
            "http_etag": header_etag,
            "http_last_modified": header_last_modified,
            "fetched_at": fetched_at,
            "crawl_run_id": self.crawl_run_id,
            "parser_version": self.config.parser_version,
        }
        self._append_jsonl(self.records_path, record)

        return existing_url_state is not None

    @staticmethod
    def _is_unchanged(existing: UrlState | None, etag: str | None, last_modified: str | None) -> bool:
        if not existing:
            return False
        if etag and existing.http_etag and etag == existing.http_etag:
            return True
        if last_modified and existing.http_last_modified and last_modified == existing.http_last_modified:
            return True
        return False

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _write_run_summary(self, stats: CrawlStats, dry_run: bool, since: str | None, max_pages: int) -> None:
        run_payload = {
            "crawl_run_id": self.crawl_run_id,
            "site_slug": self.config.site_slug,
            "base_url": self.config.base_url,
            "dry_run": dry_run,
            "since": since,
            "max_pages": max_pages,
            "fetched_at": utc_now_iso(),
            **stats.as_dict(),
        }
        self._append_jsonl(self.runs_path, run_payload)

    def _log_error(self, url: str, reason: str, error: str) -> None:
        self.logger.error(
            json.dumps(
                {
                    "crawl_run_id": self.crawl_run_id,
                    "url": url,
                    "status": reason,
                    "reason": error,
                }
            )
        )

    def _log_policy_skip(self, url: str, reason: str) -> None:
        self.logger.warning(
            json.dumps(
                {
                    "crawl_run_id": self.crawl_run_id,
                    "url": url,
                    "status": "policy",
                    "reason": reason,
                }
            )
        )
