"""CLI entry point for Perpaduan scraper."""
import argparse
import logging
from pathlib import Path
import sys

from src.scraper import PerpaduanScraper


def setup_logging(log_level=logging.INFO):
    """Configure logging."""
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Scraper for Kementerian Perpaduan Negara (perpaduan.gov.my)"
    )
    parser.add_argument(
        "--site-config",
        required=True,
        help="Path to site config YAML",
    )
    parser.add_argument(
        "--state-db",
        default=".cache/scraper_state.sqlite3",
        help="Path to state database",
    )
    parser.add_argument(
        "--output-dir",
        default="data/manifests/perpaduan",
        help="Output directory for records and runs",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        help="Maximum pages to crawl per section",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't upload to Spaces, just crawl and output",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    setup_logging(getattr(logging, args.log_level))

    # Validate config
    if not Path(args.site_config).exists():
        print(f"Error: Config file not found: {args.site_config}", file=sys.stderr)
        sys.exit(1)

    # Run scraper
    scraper = PerpaduanScraper(
        config_path=args.site_config,
        state_db=args.state_db,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
    )

    try:
        summary = scraper.run(max_pages=args.max_pages)
        print("\n" + "=" * 60)
        print("SCRAPE SUMMARY")
        print("=" * 60)
        for key, value in summary.items():
            print(f"{key:20s}: {value}")
        print("=" * 60)
    except Exception as e:
        logging.error(f"Scraper failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
