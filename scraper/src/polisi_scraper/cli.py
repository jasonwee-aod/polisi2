"""Click-based CLI entry point for the unified scraper."""

from __future__ import annotations

import json
import logging
import sys
from datetime import date

import click

from polisi_scraper.runner import run_scrape


def _setup_logging(level: str) -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


@click.command("polisi-scraper")
@click.option("--sites", default="", help="Comma-separated adapter slugs (default: all)")
@click.option("--all", "run_all", is_flag=True, help="Run all adapters")
@click.option("--site-config", default="configs", help="Path to configs directory")
@click.option("--since", default=None, help="Only process records on/after YYYY-MM-DD")
@click.option("--max-pages", default=0, type=int, help="Max pages per section (0=unlimited)")
@click.option("--dry-run", is_flag=True, help="Fetch and parse, but skip uploads and state writes")
@click.option("--workers", default=3, type=int, help="Concurrent adapter threads (default 3)")
@click.option("--request-delay", default=1.5, type=float, help="Seconds between HTTP requests")
@click.option("--log-level", default="INFO", type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]))
@click.option("--manifest-dir", default="data/manifests", help="Output directory for records")
def main(
    sites: str,
    run_all: bool,
    site_config: str,
    since: str | None,
    max_pages: int,
    dry_run: bool,
    workers: int,
    request_delay: float,
    log_level: str,
    manifest_dir: str,
) -> None:
    """Polisi Scraper - crawl government websites and archive documents."""
    _setup_logging(log_level)

    site_list = [s.strip() for s in sites.split(",") if s.strip()] if sites else None

    since_date = date.fromisoformat(since) if since else None

    results = run_scrape(
        sites=site_list,
        config_dir=site_config,
        since=since_date,
        max_pages=max_pages,
        dry_run=dry_run,
        max_workers=workers,
        request_delay=request_delay,
        manifest_dir=manifest_dir,
    )

    # Print summary
    click.echo("\n" + "=" * 60)
    click.echo("SCRAPE SUMMARY")
    click.echo("=" * 60)

    total_new = 0
    total_failed = 0
    for slug, result in sorted(results.items()):
        status = result.get("status", "unknown")
        new = result.get("new", 0)
        skipped = result.get("skipped", 0)
        failed = result.get("failed", 0)
        total_new += new
        total_failed += failed
        icon = "OK" if status == "ok" else "!!"
        click.echo(f"  [{icon}] {slug:20s}  new={new}  skipped={skipped}  failed={failed}")

    click.echo("-" * 60)
    click.echo(f"  TOTAL: {total_new} new documents, {total_failed} failures")
    click.echo("=" * 60)

    if total_failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
