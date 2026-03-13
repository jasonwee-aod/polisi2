#!/usr/bin/env python3
"""Live dry-run: test discover() against real sites, limit items fetched.

Usage:
    python scripts/live_dry_run.py [--sites bheuu,moh] [--max-pages 1] [--max-items 5]
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date

import yaml

from polisi_scraper.adapters.base import HTTPClient, BaseSiteAdapter
from polisi_scraper.adapters.registry import get_adapter_registry, get_adapter_class
from polisi_scraper.runner import load_adapter_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def test_adapter(slug: str, config_dir: str, max_pages: int, max_items: int) -> dict:
    """Test a single adapter's discover() and optionally fetch_and_extract()."""
    cls = get_adapter_class(slug)
    config = load_adapter_config(config_dir, slug)

    allowed_hosts = config.get("allowed_hosts", [])
    http = HTTPClient(
        allowed_hosts=frozenset(allowed_hosts) if allowed_hosts else None,
        request_delay=config.get("request_delay", 1.5),
        verify_ssl=config.get("verify_ssl", True),
    )

    adapter = cls(config=config, http=http)
    result = {
        "slug": slug,
        "discovered": 0,
        "fetched": 0,
        "downloads_found": 0,
        "errors": [],
        "sample_items": [],
    }

    t0 = time.monotonic()

    # Phase 1: Discovery
    try:
        items = []
        for item in adapter.discover(since=None, max_pages=max_pages):
            items.append(item)
            if len(items) >= max_items * 5:  # Discover more than we fetch
                break
        result["discovered"] = len(items)
    except Exception as e:
        result["errors"].append(f"discover: {e}")
        log.error(f"  [{slug}] discover() failed: {e}")
        return result

    if not items:
        log.warning(f"  [{slug}] discover() returned 0 items")
        return result

    # Phase 2: Fetch + Extract (limited)
    fetch_count = min(max_items, len(items))
    for item in items[:fetch_count]:
        try:
            candidates = list(adapter.fetch_and_extract(item))
            result["fetched"] += 1
            dl_count = sum(1 for c in candidates if c.content_type != "text/html")
            result["downloads_found"] += dl_count

            if len(result["sample_items"]) < 3:
                result["sample_items"].append({
                    "title": item.title[:80] if item.title else "(no title)",
                    "url": item.source_url[:100],
                    "date": item.published_at,
                    "doc_type": item.doc_type,
                    "candidates": len(candidates),
                })
        except Exception as e:
            result["errors"].append(f"fetch: {e}")
            log.error(f"  [{slug}] fetch_and_extract failed for {item.source_url}: {e}")

    elapsed = time.monotonic() - t0
    result["elapsed_s"] = round(elapsed, 1)
    return result


def main():
    parser = argparse.ArgumentParser(description="Live dry-run smoke test")
    parser.add_argument("--sites", default="", help="Comma-separated slugs (default: all)")
    parser.add_argument("--config-dir", default="configs", help="Config directory")
    parser.add_argument("--max-pages", type=int, default=1, help="Max pages per section")
    parser.add_argument("--max-items", type=int, default=3, help="Max items to fetch per adapter")
    args = parser.parse_args()

    registry = get_adapter_registry()
    if args.sites:
        slugs = [s.strip() for s in args.sites.split(",") if s.strip()]
    else:
        slugs = sorted(registry.keys())

    log.info(f"Testing {len(slugs)} adapters: {', '.join(slugs)}")
    log.info(f"max_pages={args.max_pages}, max_items={args.max_items}")
    print()

    results = {}
    for slug in slugs:
        log.info(f"[{slug}] Starting...")
        try:
            result = test_adapter(slug, args.config_dir, args.max_pages, args.max_items)
            results[slug] = result
        except Exception as e:
            results[slug] = {"slug": slug, "errors": [str(e)]}
            log.error(f"[{slug}] CRASHED: {e}")

    # Summary
    print()
    print("=" * 80)
    print(f"{'ADAPTER':<20} {'DISC':>5} {'FETCH':>5} {'DL':>5} {'TIME':>7} {'STATUS'}")
    print("=" * 80)

    total_ok = 0
    total_fail = 0
    for slug in slugs:
        r = results.get(slug, {})
        disc = r.get("discovered", 0)
        fetch = r.get("fetched", 0)
        dl = r.get("downloads_found", 0)
        elapsed = r.get("elapsed_s", 0)
        errors = r.get("errors", [])

        if errors:
            status = f"FAIL ({len(errors)} errors)"
            total_fail += 1
        elif disc == 0:
            status = "WARN (0 discovered)"
            total_fail += 1
        else:
            status = "OK"
            total_ok += 1

        print(f"  {slug:<18} {disc:>5} {fetch:>5} {dl:>5} {elapsed:>6.1f}s {status}")

        # Print sample items
        for sample in r.get("sample_items", [])[:2]:
            print(f"    -> {sample['title'][:60]}")
            print(f"       {sample['url'][:80]}")

        for err in errors[:2]:
            print(f"    !! {err[:80]}")

    print("-" * 80)
    print(f"  OK: {total_ok}  FAIL: {total_fail}  TOTAL: {len(slugs)}")
    print("=" * 80)

    sys.exit(1 if total_fail > 0 else 0)


if __name__ == "__main__":
    main()
