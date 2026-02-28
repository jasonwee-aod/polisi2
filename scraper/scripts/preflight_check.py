from __future__ import annotations

import argparse
import importlib
import json
import os
import pathlib
import socket
from urllib.parse import urlparse
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polisi_scraper.config import ScraperSettings, SettingsError


SCRAPER_ENV_VARS = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "DO_SPACES_KEY",
    "DO_SPACES_SECRET",
    "DO_SPACES_BUCKET",
    "DO_SPACES_REGION",
    "DO_SPACES_ENDPOINT",
]
INDEXER_ENV_VARS = SCRAPER_ENV_VARS + [
    "OPENAI_API_KEY",
    "SUPABASE_DB_URL",
]
SCRAPER_IMPORTS = [
    "polisi_scraper.runner",
    "polisi_scraper.adapters",
    "polisi_scraper.core.state_store",
]
INDEXER_IMPORTS = [
    "polisi_scraper.indexer.runner",
    "polisi_scraper.indexer.pipeline",
    "polisi_scraper.indexer.parsers",
    "polisi_scraper.indexer.embeddings",
    "polisi_scraper.indexer.store",
]


def _normalize_components(raw: str) -> list[str]:
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        return ["scraper"]
    allowed = {"scraper", "indexer", "all"}
    if any(part not in allowed for part in parts):
        raise ValueError("components must be scraper, indexer, or all")
    if "all" in parts:
        return ["scraper", "indexer"]
    return parts


def _required_env_vars(components: list[str]) -> list[str]:
    required: list[str] = []
    if "scraper" in components:
        required.extend(SCRAPER_ENV_VARS)
    if "indexer" in components:
        required.extend(INDEXER_ENV_VARS)
    return sorted(set(required))


def _required_imports(components: list[str]) -> list[str]:
    required: list[str] = []
    if "scraper" in components:
        required.extend(SCRAPER_IMPORTS)
    if "indexer" in components:
        required.extend(INDEXER_IMPORTS)
    return required


def _check_env(components: list[str]) -> dict[str, Any]:
    missing = [k for k in _required_env_vars(components) if not os.environ.get(k)]
    result = {
        "missing": missing,
        "ok": len(missing) == 0,
    }
    if result["ok"]:
        ScraperSettings.from_env(dict(os.environ), require_indexer="indexer" in components)
    return result


def _check_imports(components: list[str]) -> dict[str, Any]:
    failed: list[str] = []
    for module_name in _required_imports(components):
        try:
            importlib.import_module(module_name)
        except Exception:
            failed.append(module_name)
    return {"failed": failed, "ok": len(failed) == 0}


def _check_dns(components: list[str]) -> dict[str, Any]:
    targets = {"www.mof.gov.my", "www.moe.gov.my", "api.supabase.com"}
    if "indexer" in components:
        targets.add("api.openai.com")
        db_url = os.environ.get("SUPABASE_DB_URL", "")
        parsed = urlparse(db_url)
        if parsed.hostname:
            targets.add(parsed.hostname)
    failed: list[str] = []
    for host in sorted(targets):
        try:
            socket.gethostbyname(host)
        except Exception:
            failed.append(host)
    return {"failed": failed, "ok": len(failed) == 0}


def run_preflight(*, components: list[str], dry_run: bool = False) -> tuple[int, dict[str, Any]]:
    report: dict[str, Any] = {
        "components": components,
        "env": _check_env(components),
        "imports": _check_imports(components),
    }

    if dry_run:
        report["dns"] = {"skipped": True}
        all_ok = report["env"]["ok"] and report["imports"]["ok"]
    else:
        report["dns"] = _check_dns(components)
        all_ok = report["env"]["ok"] and report["imports"]["ok"] and report["dns"]["ok"]

    return (0 if all_ok else 1), report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate scraper runtime readiness")
    parser.add_argument(
        "--components",
        default="scraper",
        help="Comma-separated components: scraper, indexer, or all",
    )
    parser.add_argument("--dry-run", action="store_true", help="Skip external connectivity checks")
    args = parser.parse_args()

    try:
        code, report = run_preflight(
            components=_normalize_components(args.components),
            dry_run=args.dry_run,
        )
    except SettingsError as err:
        print(json.dumps({"ok": False, "error": str(err)}, indent=2))
        raise SystemExit(1)
    except ValueError as err:
        print(json.dumps({"ok": False, "error": str(err)}, indent=2))
        raise SystemExit(1)

    print(json.dumps(report, indent=2))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
