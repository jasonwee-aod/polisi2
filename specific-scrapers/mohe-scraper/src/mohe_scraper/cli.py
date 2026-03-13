"""Command-line interface for MOHE scraper."""

import argparse
import logging
import json
import sys
from pathlib import Path
from datetime import datetime

import yaml

from mohe_scraper.crawler import MOHECrawler
from mohe_scraper.state_manager import StateManager
from mohe_scraper.storage import StorageFactory
from mohe_scraper.models import CrawlRun


def setup_logging(log_level: str = "INFO"):
    """Configure logging with JSON format."""
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def load_config(config_path: str) -> dict:
    """Load site configuration from YAML."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def save_records(records: list, output_dir: str, crawl_run_id: str):
    """Save records to records.jsonl."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    records_file = output_dir / "records.jsonl"
    with open(records_file, "a") as f:
        for record in records:
            f.write(record.to_jsonl() + "\n")

    logging.getLogger(__name__).info(f"Saved {len(records)} records to {records_file}")


def save_crawl_run(crawl_run: CrawlRun, output_dir: str):
    """Save crawl run metadata."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    runs_file = output_dir / "crawl_runs.jsonl"
    with open(runs_file, "a") as f:
        f.write(crawl_run.to_jsonl() + "\n")

    logging.getLogger(__name__).info(f"Saved crawl run metadata to {runs_file}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="MOHE (Malaysia Ministry of Higher Education) web scraper"
    )

    parser.add_argument(
        "--site-config",
        type=str,
        default="configs/mohe_site_config.yaml",
        help="Path to site configuration YAML"
    )

    parser.add_argument(
        "--state-db",
        type=str,
        default="./data/mohe_state.db",
        help="Path to SQLite state database"
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="./data/manifests/mohe",
        help="Output directory for records.jsonl and crawl_runs.jsonl"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without writing files to storage"
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=1000,
        help="Maximum pages to crawl"
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    try:
        # Load configuration
        logger.info(f"Loading configuration from {args.site_config}")
        if not Path(args.site_config).exists():
            logger.error(f"Configuration file not found: {args.site_config}")
            sys.exit(1)

        config = load_config(args.site_config)

        # Initialize components
        logger.info("Initializing state manager")
        state_manager = StateManager(args.state_db)

        logger.info("Initializing storage backend")
        storage = StorageFactory.create()

        logger.info("Initializing crawler")
        crawler = MOHECrawler(config, state_manager, storage, dry_run=args.dry_run)

        # Run RSS crawl
        logger.info("Starting RSS feed crawl")
        records = crawler.crawl_rss_feeds()

        # Run HTML listing page crawl (staff downloads, DOCman)
        logger.info("Starting HTML listing page crawl")
        html_records = crawler.crawl_html_listing_pages()
        records.extend(html_records)
        logger.info(f"HTML crawl produced {len(html_records)} records")

        # Finalize
        crawler.finalize_crawl_run()
        crawl_summary = crawler.get_crawl_run_summary()

        # Save output
        if records:
            save_records(records, args.output_dir, crawler.crawl_run_id)

        save_crawl_run(crawler.crawl_run, args.output_dir)

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("CRAWL RUN SUMMARY")
        logger.info("=" * 60)
        for key, value in crawl_summary.items():
            if key != "errors":
                logger.info(f"{key}: {value}")

        if crawl_summary.get("errors"):
            logger.info(f"\nFirst {len(crawl_summary['errors'])} errors:")
            for i, error in enumerate(crawl_summary["errors"], 1):
                logger.error(f"  {i}. {error.get('url')}: {error.get('error')}")

        logger.info("=" * 60)

        if args.dry_run:
            logger.info("DRY RUN: No files were written")

        # Exit with error code if there were failures
        if crawl_summary.get("total_items_failed", 0) > 0:
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Crawl interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
