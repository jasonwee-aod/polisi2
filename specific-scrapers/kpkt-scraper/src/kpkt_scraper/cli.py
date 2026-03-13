"""
CLI entry point for the KPKT scraper.

Usage:
    kpkt-scraper [OPTIONS]

    # Full run (requires GCS_BUCKET env var):
    kpkt-scraper --site-config configs/kpkt.yaml

    # Dry run – fetch and parse, no GCS upload, no state write:
    kpkt-scraper --dry-run

    # Incremental – only documents published on or after 2025-01-01:
    kpkt-scraper --since 2025-01-01

    # Limit to 2 listing pages for testing:
    kpkt-scraper --dry-run --max-pages 2
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import click

from .archiver import GCSArchiver
from .crawler import HTTPClient
from .pipeline import KPKTPipeline, load_config
from .state import StateStore


# ── Logging ───────────────────────────────────────────────────────────────────


def _setup_logging(level: str) -> None:
    """Configure structured JSON-like logging to stdout."""
    numeric = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt='{"ts":"%(asctime)s","lvl":"%(levelname)s","logger":"%(name)s","msg":%(message)s}',
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
    )
    logging.basicConfig(level=numeric, handlers=[handler])


# ── CLI ───────────────────────────────────────────────────────────────────────


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--site-config",
    default="configs/kpkt.yaml",
    show_default=True,
    help="Path to site config YAML.",
)
@click.option(
    "--since",
    default=None,
    metavar="YYYY-MM-DD",
    help="Skip documents published before this date (inclusive lower bound).",
)
@click.option(
    "--max-pages",
    default=0,
    type=int,
    show_default=True,
    help="Limit number of listing pages fetched (0 = unlimited).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help=(
        "Fetch and parse but do NOT upload to GCS or write to the state DB. "
        "records.jsonl is still written so you can inspect output."
    ),
)
@click.option(
    "--db-path",
    default="data/state.db",
    show_default=True,
    envvar="KPKT_DB_PATH",
    help="SQLite state database path.",
)
@click.option(
    "--manifest-dir",
    default="data/manifests/kpkt",
    show_default=True,
    envvar="KPKT_MANIFEST_DIR",
    help="Output directory for records.jsonl and crawl_runs.jsonl.",
)
@click.option(
    "--log-level",
    default="INFO",
    show_default=True,
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Logging verbosity.",
)
@click.option(
    "--request-delay",
    default=1.0,
    type=float,
    show_default=True,
    help="Seconds to wait between HTTP requests (polite crawling).",
)
def main(
    site_config: str,
    since: str | None,
    max_pages: int,
    dry_run: bool,
    db_path: str,
    manifest_dir: str,
    log_level: str,
    request_delay: float,
) -> None:
    """KPKT Government Site Scraper – archives public documents to GCS."""
    _setup_logging(log_level)
    log = logging.getLogger(__name__)

    gcs_bucket = os.environ.get("GCS_BUCKET", "")
    if not dry_run and not gcs_bucket:
        click.echo(
            "ERROR: set GCS_BUCKET environment variable or use --dry-run.",
            err=True,
        )
        sys.exit(1)

    config = load_config(site_config)
    state = StateStore(db_path)
    http = HTTPClient(request_delay=request_delay)
    archiver = GCSArchiver(
        bucket_name=gcs_bucket or "dry-run-bucket",
        dry_run=dry_run,
    )
    pipeline = KPKTPipeline(
        config=config,
        state=state,
        archiver=archiver,
        http=http,
        manifest_dir=Path(manifest_dir),
        dry_run=dry_run,
        since=since,
        max_pages=max_pages,
    )

    try:
        run = pipeline.run()
    finally:
        state.close()
        http.close()

    # ── Run summary ───────────────────────────────────────────────────────────
    click.echo("")
    click.echo("=== Crawl Summary ===")
    click.echo(f"  Run ID   : {run.crawl_run_id}")
    click.echo(f"  New      : {run.new_count}")
    click.echo(f"  Changed  : {run.changed_count}")
    click.echo(f"  Skipped  : {run.skipped_count}")
    click.echo(f"  Failed   : {run.failed_count}")
    click.echo(f"  Started  : {run.started_at}")
    click.echo(f"  Completed: {run.completed_at}")
    if dry_run:
        click.echo("  Mode     : DRY RUN (no GCS upload, no state written)")
    click.echo("")

    if run.failed_count > 0:
        sys.exit(1)
