"""Entrypoint that executes adapters through the shared pipeline."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Callable, Iterable

from polisi_scraper.adapters import get_adapter_registry
from polisi_scraper.adapters.base import BaseSiteAdapter, DocumentCandidate
from polisi_scraper.config import ScraperSettings
from polisi_scraper.core.dedup import compute_sha256, is_content_changed
from polisi_scraper.core.http_client import HttpClient, HttpClientConfig
from polisi_scraper.core.spaces import SpacesConfig, SpacesUploader
from polisi_scraper.core.state_store import CrawlStateStore

Fetcher = Callable[[str], bytes]


@dataclass(frozen=True)
class AdapterRunStats:
    adapter_slug: str
    processed: int
    skipped_unchanged: int
    errors: int
    checkpoint: str | None


@dataclass(frozen=True)
class ScrapeRunSummary:
    started_at: str
    finished_at: str
    adapters: list[AdapterRunStats]



def run_scrape(
    adapters: Iterable[BaseSiteAdapter],
    *,
    max_docs: int | None = None,
    dry_run: bool = False,
    settings: ScraperSettings | None = None,
    state_store: CrawlStateStore | None = None,
    uploader: SpacesUploader | None = None,
    fetcher: Fetcher | None = None,
) -> ScrapeRunSummary:
    resolved_settings = settings or ScraperSettings.from_env()

    http_client = HttpClient(
        HttpClientConfig(
            timeout_seconds=resolved_settings.scraper_timeout_seconds,
            max_retries=resolved_settings.scraper_max_retries,
            retry_backoff_seconds=resolved_settings.scraper_retry_backoff_seconds,
            user_agent=resolved_settings.scraper_user_agent,
        )
    )

    resolved_state_store = state_store or CrawlStateStore(resolved_settings.scraper_state_db_path)
    resolved_uploader = uploader or SpacesUploader(
        SpacesConfig(
            key=resolved_settings.do_spaces_key,
            secret=resolved_settings.do_spaces_secret,
            bucket=resolved_settings.do_spaces_bucket,
            region=resolved_settings.do_spaces_region,
            endpoint=resolved_settings.do_spaces_endpoint,
        )
    )
    resolved_fetcher = fetcher or http_client.get_bytes

    started = datetime.now(timezone.utc)
    adapter_stats: list[AdapterRunStats] = []

    for adapter in adapters:
        stats = _run_single_adapter(
            adapter,
            max_docs=max_docs,
            dry_run=dry_run,
            state_store=resolved_state_store,
            uploader=resolved_uploader,
            fetcher=resolved_fetcher,
        )
        adapter_stats.append(stats)

    finished = datetime.now(timezone.utc)
    return ScrapeRunSummary(
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        adapters=adapter_stats,
    )



def _run_single_adapter(
    adapter: BaseSiteAdapter,
    *,
    max_docs: int | None,
    dry_run: bool,
    state_store: CrawlStateStore,
    uploader: SpacesUploader,
    fetcher: Fetcher,
) -> AdapterRunStats:
    processed = 0
    skipped = 0
    errors = 0
    checkpoint: str | None = None

    candidates = adapter.iter_document_candidates(max_docs=max_docs)

    for candidate in candidates:
        checkpoint = candidate.document_url
        try:
            payload = fetcher(candidate.document_url)
            sha256 = compute_sha256(payload)
            previous_sha = state_store.get_latest_sha256(adapter.slug, candidate.document_url)

            if state_store.is_already_processed(adapter.slug, candidate.document_url, sha256):
                skipped += 1
                state_store.set_checkpoint(adapter.slug, candidate.document_url, {"status": "skipped"})
                continue

            changed_on = None
            if is_content_changed(previous_sha, sha256):
                changed_on = datetime.now(timezone.utc).date()

            record = adapter.to_record(candidate, sha256=sha256)
            storage_path = record.storage_path(changed_on=changed_on)

            if not dry_run:
                source_url_meta: dict[str, str] = {}
                if record.source_url:
                    source_url_meta = {"source_url": record.source_url}
                uploader.upload_bytes(
                    payload,
                    storage_path,
                    metadata=source_url_meta if source_url_meta else None,
                )

            state_store.mark_processed(adapter.slug, candidate.document_url, sha256, storage_path)
            state_store.set_checkpoint(
                adapter.slug,
                candidate.document_url,
                {
                    "status": "processed",
                    "storage_path": storage_path,
                    "changed": changed_on is not None,
                },
            )
            processed += 1
        except Exception:
            errors += 1
            state_store.set_checkpoint(
                adapter.slug,
                candidate.document_url,
                {"status": "error"},
            )

    return AdapterRunStats(
        adapter_slug=adapter.slug,
        processed=processed,
        skipped_unchanged=skipped,
        errors=errors,
        checkpoint=checkpoint,
    )



def _load_adapters_from_registry(site_slugs: list[str] | None) -> list[BaseSiteAdapter]:
    registry = get_adapter_registry()

    if site_slugs:
        missing = [slug for slug in site_slugs if slug not in registry]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Unknown adapter slug(s): {joined}")
        return [registry[slug]() for slug in site_slugs]

    return [factory() for factory in registry.values()]



def main() -> None:
    parser = argparse.ArgumentParser(description="Run Polisi scraper adapters")
    parser.add_argument("--sites", help="Comma-separated adapter slugs", default="")
    parser.add_argument("--max-docs", type=int, default=None, help="Cap docs per adapter")
    parser.add_argument("--dry-run", action="store_true", help="Do not upload files")
    args = parser.parse_args()

    site_slugs = [s.strip() for s in args.sites.split(",") if s.strip()] or None
    adapters = _load_adapters_from_registry(site_slugs)

    summary = run_scrape(adapters, max_docs=args.max_docs, dry_run=args.dry_run)
    print(json.dumps(summary, default=lambda x: x.__dict__, indent=2))


if __name__ == "__main__":
    main()
