"""Orchestrator: runs adapters in parallel waves using ThreadPoolExecutor."""

from __future__ import annotations

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from polisi_scraper.adapters.base import (
    AdapterStateStore,
    BaseSiteAdapter,
    CrawlRun,
    DocumentCandidate,
    HTTPClient,
    Record,
    SpacesArchiver,
    sha256_of_bytes,
    spaces_object_path,
)
from polisi_scraper.adapters.registry import get_adapter_class, get_adapter_registry
from polisi_scraper.core.browser import BrowserPool
from polisi_scraper.core.urls import canonical_url, guess_content_type

log = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_record_id(url: str) -> str:
    import hashlib
    return hashlib.sha256(url.encode()).hexdigest()[:24]


def load_adapter_config(config_dir: str, slug: str) -> dict:
    """Load YAML config for an adapter."""
    config_path = Path(config_dir) / f"{slug}.yaml"
    if not config_path.exists():
        # Try with hyphens
        config_path = Path(config_dir) / f"{slug.replace('_', '-')}.yaml"
    if not config_path.exists():
        log.warning(f"No config file found for {slug} at {config_path}")
        return {}
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def build_adapter(
    slug: str,
    config_dir: str,
    archiver: SpacesArchiver,
    browser_pool: BrowserPool,
    request_delay: float = 1.5,
) -> BaseSiteAdapter:
    """Instantiate an adapter with all its dependencies."""
    cls = get_adapter_class(slug)
    config = load_adapter_config(config_dir, slug)

    allowed_hosts = config.get("allowed_hosts", [])
    http = HTTPClient(
        allowed_hosts=frozenset(allowed_hosts) if allowed_hosts else None,
        request_delay=config.get("request_delay", request_delay),
        verify_ssl=config.get("verify_ssl", True),
    )

    state_dir = Path("data/state")
    state_dir.mkdir(parents=True, exist_ok=True)
    state = AdapterStateStore(str(state_dir / f"{slug}.sqlite3"))

    return cls(
        config=config,
        http=http,
        state=state,
        archiver=archiver,
        browser_pool=browser_pool,
    )


def run_single_adapter(
    adapter: BaseSiteAdapter,
    since: date | None,
    max_pages: int,
    dry_run: bool,
    browser_lock: threading.Lock,
    manifest_dir: str = "data/manifests",
) -> dict:
    """Run a single adapter end-to-end. Returns result dict."""
    crawl_run_id = f"{_utcnow()[:10]}-{adapter.slug}"
    run = CrawlRun(
        crawl_run_id=crawl_run_id,
        site_slug=adapter.slug,
        started_at=_utcnow(),
    )

    output_dir = Path(manifest_dir) / adapter.slug
    output_dir.mkdir(parents=True, exist_ok=True)
    records_path = output_dir / "records.jsonl"

    try:
        for item in adapter.discover(since=since, max_pages=max_pages):
            if adapter.should_skip(item):
                run.skipped_count += 1
                continue

            try:
                # Fetch and extract: serialize Playwright access
                if adapter.requires_browser:
                    with browser_lock:
                        candidates = list(adapter.fetch_and_extract(item))
                else:
                    candidates = list(adapter.fetch_and_extract(item))

                for candidate in candidates:
                    try:
                        _process_candidate(
                            adapter=adapter,
                            candidate=candidate,
                            run=run,
                            crawl_run_id=crawl_run_id,
                            dry_run=dry_run,
                            records_path=records_path,
                        )
                    except Exception as e:
                        run.failed_count += 1
                        run.errors.append(str(e))
                        log.error(f"[{adapter.slug}] Failed to process {candidate.url}: {e}")

            except Exception as e:
                run.failed_count += 1
                run.errors.append(str(e))
                log.error(f"[{adapter.slug}] Failed to process item {item.source_url}: {e}")

    except Exception as e:
        run.errors.append(f"Discovery failed: {e}")
        log.error(f"[{adapter.slug}] Discovery failed: {e}")

    run.completed_at = _utcnow()

    # Save crawl run
    if adapter.state:
        adapter.state.save_crawl_run(run)

    runs_path = Path(manifest_dir) / adapter.slug / "crawl_runs.jsonl"
    with open(runs_path, "a") as f:
        f.write(run.to_json() + "\n")

    total = run.new_count + run.changed_count
    log.info(
        f"[{adapter.slug}] Done: {total} processed, "
        f"{run.skipped_count} skipped, {run.failed_count} failed"
    )

    return {
        "slug": adapter.slug,
        "status": "ok" if not run.errors else "partial",
        "new": run.new_count,
        "changed": run.changed_count,
        "skipped": run.skipped_count,
        "failed": run.failed_count,
        "errors": run.errors[:5],  # Limit error messages
    }


def _process_candidate(
    adapter: BaseSiteAdapter,
    candidate: DocumentCandidate,
    run: CrawlRun,
    crawl_run_id: str,
    dry_run: bool,
    records_path: Path,
) -> None:
    """Download, dedup, archive, and record a single document candidate."""
    c_url = canonical_url(candidate.url)
    fetched_at = _utcnow()

    # Pre-fetch dedup: skip if we already have this URL with unchanged ETag
    if adapter.state:
        existing = adapter.state.get_by_url(c_url)
        if existing and existing.get("sha256"):
            run.skipped_count += 1
            return

    # Fetch the document bytes
    raw_bytes, headers = adapter.http.get_bytes(candidate.url)
    sha256 = sha256_of_bytes(raw_bytes)

    # Post-fetch dedup: if sha256 already exists, reuse existing Spaces path
    spaces_url = ""
    spaces_path = ""
    is_reuse = False

    if adapter.state and adapter.state.sha256_exists(sha256):
        spaces_url = adapter.state.get_spaces_url_by_sha256(sha256) or ""
        spaces_path = adapter.state.get_spaces_path_by_sha256(sha256) or ""
        is_reuse = True
        run.skipped_count += 1
    else:
        # Upload to Spaces
        obj_path = spaces_object_path(adapter.slug, sha256, candidate.url)
        ct = candidate.content_type or headers.get("content-type", "") or guess_content_type(candidate.url)
        if adapter.archiver:
            spaces_url = adapter.archiver.upload(raw_bytes, obj_path, ct)
            spaces_path = obj_path
        run.new_count += 1

    # Update state
    if adapter.state and not dry_run:
        adapter.state.upsert_record(
            canonical_url=c_url,
            source_url=candidate.source_page_url,
            sha256=sha256,
            spaces_url=spaces_url,
            spaces_path=spaces_path,
            http_etag=headers.get("etag", ""),
            http_last_modified=headers.get("last-modified", ""),
            fetched_at=fetched_at,
        )

    # Write record to JSONL
    if not is_reuse:
        record = Record(
            record_id=_stable_record_id(c_url),
            source_url=candidate.source_page_url,
            canonical_url=c_url,
            title=candidate.title,
            published_at=candidate.published_at or "",
            agency=adapter.agency,
            doc_type=candidate.doc_type,
            content_type=candidate.content_type or guess_content_type(candidate.url),
            language=candidate.language,
            sha256=sha256,
            spaces_bucket=adapter.archiver.bucket if adapter.archiver else "",
            spaces_path=spaces_path,
            spaces_url=spaces_url,
            http_etag=headers.get("etag", ""),
            http_last_modified=headers.get("last-modified", ""),
            fetched_at=fetched_at,
            crawl_run_id=crawl_run_id,
        )
        record = adapter.post_process(record)
        with open(records_path, "a") as f:
            f.write(record.to_json() + "\n")


def run_scrape(
    sites: list[str] | None = None,
    config_dir: str = "configs",
    since: date | None = None,
    max_pages: int = 0,
    dry_run: bool = False,
    max_workers: int = 3,
    request_delay: float = 1.5,
    manifest_dir: str = "data/manifests",
) -> dict:
    """Run scraper for selected adapters (or all) with parallel execution."""
    registry = get_adapter_registry()

    if sites:
        slugs = sites
        missing = [s for s in slugs if s not in registry]
        if missing:
            raise ValueError(f"Unknown adapter slug(s): {', '.join(missing)}")
    else:
        slugs = sorted(registry.keys())

    # Build archiver (shared, thread-safe via boto3)
    bucket = os.getenv("DO_SPACES_BUCKET", "polisi-gov-docs")
    archiver = SpacesArchiver(
        bucket=bucket,
        region=os.getenv("DO_SPACES_REGION", "sgp1"),
        endpoint=os.getenv("DO_SPACES_ENDPOINT", f"https://sgp1.digitaloceanspaces.com"),
        key=os.getenv("DO_SPACES_KEY", ""),
        secret=os.getenv("DO_SPACES_SECRET", ""),
        dry_run=dry_run,
    )

    browser_pool = BrowserPool()
    browser_lock = threading.Lock()

    # Build adapters
    adapters = []
    for slug in slugs:
        try:
            adapter = build_adapter(slug, config_dir, archiver, browser_pool, request_delay)
            adapters.append(adapter)
        except Exception as e:
            log.error(f"Failed to build adapter {slug}: {e}")

    # Sort heaviest first (by estimated_pages if available)
    adapters.sort(
        key=lambda a: a.config.get("estimated_pages", 0),
        reverse=True,
    )

    results = {}

    if max_workers <= 1:
        # Sequential execution
        for adapter in adapters:
            result = run_single_adapter(
                adapter, since, max_pages, dry_run, browser_lock, manifest_dir
            )
            results[result["slug"]] = result
    else:
        # Parallel execution
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    run_single_adapter,
                    adapter, since, max_pages, dry_run, browser_lock, manifest_dir,
                ): adapter.slug
                for adapter in adapters
            }
            for future in as_completed(futures):
                slug = futures[future]
                try:
                    result = future.result()
                    results[slug] = result
                except Exception as e:
                    results[slug] = {"slug": slug, "status": "error", "error": str(e)}
                    log.error(f"Adapter {slug} failed: {e}")

    browser_pool.close()
    return results
