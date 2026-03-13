"""
CLI entry point for the MCMC scraper.

Usage:
    mcmc-scraper [OPTIONS]

    # Full run (requires DO_SPACES_* env vars):
    mcmc-scraper --site-config configs/mcmc.yaml

    # Dry run – fetch and parse, no Spaces upload, no state write:
    mcmc-scraper --dry-run

    # Incremental – only articles published on or after 2025-01-01:
    mcmc-scraper --since 2025-01-01

    # Limit to 3 listing pages for quick smoke test:
    mcmc-scraper --dry-run --max-pages 3
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import click

from .archiver import SpacesArchiver
from .crawler import HTTPClient
from .pipeline import MCMCPipeline, load_config
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
    default="configs/mcmc.yaml",
    show_default=True,
    help="Path to site config YAML.",
)
@click.option(
    "--since",
    default=None,
    metavar="YYYY-MM-DD",
    help="Skip articles published before this date (inclusive lower bound).",
)
@click.option(
    "--max-pages",
    default=0,
    type=int,
    show_default=True,
    help="Limit number of listing pages fetched per section (0 = unlimited).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help=(
        "Fetch and parse but do NOT upload to Spaces or write to the state DB. "
        "records.jsonl is still written so you can inspect output."
    ),
)
@click.option(
    "--db-path",
    default="data/state.db",
    show_default=True,
    envvar="MCMC_DB_PATH",
    help="SQLite state database path.",
)
@click.option(
    "--manifest-dir",
    default="data/manifests/mcmc",
    show_default=True,
    envvar="MCMC_MANIFEST_DIR",
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
    default=1.5,
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
    """MCMC Government Site Scraper – archives public documents to DigitalOcean Spaces."""
    _setup_logging(log_level)
    log = logging.getLogger(__name__)

    # Validate Spaces credentials for non-dry-run
    spaces_key = os.environ.get("DO_SPACES_KEY", "")
    spaces_secret = os.environ.get("DO_SPACES_SECRET", "")
    spaces_bucket = os.environ.get("DO_SPACES_BUCKET", "")
    spaces_region = os.environ.get("DO_SPACES_REGION", "sgp1")
    spaces_endpoint = os.environ.get(
        "DO_SPACES_ENDPOINT", f"https://{spaces_region}.digitaloceanspaces.com"
    )

    if not dry_run and not all([spaces_key, spaces_secret, spaces_bucket]):
        click.echo(
            "ERROR: set DO_SPACES_KEY, DO_SPACES_SECRET, DO_SPACES_BUCKET "
            "environment variables or use --dry-run.",
            err=True,
        )
        sys.exit(1)

    config = load_config(site_config)
    state = StateStore(db_path)
    allowed_hosts = frozenset(config.get("allowed_hosts", []))
    http = HTTPClient(allowed_hosts=allowed_hosts, request_delay=request_delay)
    archiver = SpacesArchiver(
        bucket_name=spaces_bucket or "dry-run-bucket",
        region=spaces_region,
        endpoint_url=spaces_endpoint,
        access_key=spaces_key or "dry-run-key",
        secret_key=spaces_secret or "dry-run-secret",
        dry_run=dry_run,
    )
    pipeline = MCMCPipeline(
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
        click.echo("  Mode     : DRY RUN (no Spaces upload, no state written)")
    click.echo("")

    if run.failed_count > 0:
        sys.exit(1)
