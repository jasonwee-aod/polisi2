from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from moe_scraper.config import load_site_config
from moe_scraper.crawler import MoeCrawler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MOE gov.my scraper")
    parser.add_argument("--site-config", required=True, help="Path to site config JSON")
    parser.add_argument("--since", default=None, help="Only process records on/after YYYY-MM-DD")
    parser.add_argument("--max-pages", type=int, default=None, help="Max pages to process")
    parser.add_argument("--dry-run", action="store_true", help="Run without GCS uploads")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Root directory for manifest output files (default: SCRAPER_OUTPUT_DIR env or data/manifests)",
    )
    parser.add_argument(
        "--state-path",
        default=None,
        help="Path to state SQLite database (default: SCRAPER_STATE_PATH env or data/state/<slug>.sqlite3)",
    )
    return parser.parse_args()


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def main() -> None:
    args = parse_args()
    configure_logging()

    config = load_site_config(args.site_config)
    crawl_run_id = f"{datetime.utcnow():%Y-%m-%d}-{config.site_slug}"

    output_base = Path(args.output_dir or os.getenv("SCRAPER_OUTPUT_DIR", "data/manifests"))
    output_dir = output_base / config.site_slug

    raw_state = args.state_path or os.getenv("SCRAPER_STATE_PATH") or f"data/state/{config.site_slug}.sqlite3"
    state_path = Path(raw_state)

    max_pages = args.max_pages or config.max_pages_default

    crawler = MoeCrawler(config=config, output_root=output_dir, state_path=state_path, crawl_run_id=crawl_run_id)
    try:
        stats = crawler.run(since=args.since, max_pages=max_pages, dry_run=args.dry_run)
    finally:
        crawler.close()

    print(
        json.dumps(
            {
                "crawl_run_id": crawl_run_id,
                "summary": stats.as_dict(),
                "output_records": str(output_dir / "records.jsonl"),
                "output_runs": str(output_dir / "crawl_runs.jsonl"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
