from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polisi_scraper.adapters import get_adapter_registry
from polisi_scraper.config import ScraperSettings
from polisi_scraper.runner import run_scrape


class DryRunUploader:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def upload_bytes(self, data: bytes, object_key: str, content_type: str | None = None) -> str:
        self.keys.append(object_key)
        return object_key


def parse_site_slugs_from_config(config_path: Path) -> list[str]:
    content = config_path.read_text(encoding="utf-8")
    return re.findall(r"^\s*-\s+slug:\s*([a-z0-9_-]+)\s*$", content, flags=re.MULTILINE)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded smoke crawl for selected adapters")
    parser.add_argument("--sites", default="", help="Comma-separated site slugs")
    parser.add_argument("--max-docs", type=int, default=1, help="Maximum docs per adapter")
    parser.add_argument("--dry-run", action="store_true", help="Use deterministic local payloads")
    args = parser.parse_args()

    registry = get_adapter_registry()
    configured = parse_site_slugs_from_config(ROOT / "config" / "sites.yml")

    selected = [slug.strip() for slug in args.sites.split(",") if slug.strip()] or configured
    missing = [slug for slug in selected if slug not in registry]
    if missing:
        raise SystemExit(f"Unknown site slug(s): {', '.join(missing)}")

    adapters = [registry[slug]() for slug in selected]

    uploader = DryRunUploader()
    if args.dry_run:
        fetcher = lambda url: url.encode("utf-8")
    else:
        fetcher = None

    settings = ScraperSettings.from_env(
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role",
            "DO_SPACES_KEY": "spaces-key",
            "DO_SPACES_SECRET": "spaces-secret",
            "DO_SPACES_BUCKET": "gov-docs",
            "DO_SPACES_REGION": "sgp1",
            "DO_SPACES_ENDPOINT": "https://sgp1.digitaloceanspaces.com",
            "SCRAPER_STATE_DB_PATH": str(ROOT / ".cache" / "smoke_state.sqlite3"),
        }
    )

    summary = run_scrape(
        adapters,
        max_docs=args.max_docs,
        dry_run=args.dry_run,
        settings=settings,
        uploader=uploader,
        fetcher=fetcher,
    )

    payload = {
        "selected_sites": selected,
        "max_docs": args.max_docs,
        "dry_run": args.dry_run,
        "uploaded_keys": uploader.keys,
        "summary": asdict(summary),
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
