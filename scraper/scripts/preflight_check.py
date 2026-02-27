from __future__ import annotations

import argparse
import importlib
import json
import os
import pathlib
import socket
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polisi_scraper.config import ScraperSettings, SettingsError


REQUIRED_ENV_VARS = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "DO_SPACES_KEY",
    "DO_SPACES_SECRET",
    "DO_SPACES_BUCKET",
    "DO_SPACES_REGION",
    "DO_SPACES_ENDPOINT",
]
REQUIRED_IMPORTS = [
    "polisi_scraper.runner",
    "polisi_scraper.adapters",
    "polisi_scraper.core.state_store",
]


def _check_env() -> dict[str, Any]:
    missing = [k for k in REQUIRED_ENV_VARS if not os.environ.get(k)]
    result = {
        "missing": missing,
        "ok": len(missing) == 0,
    }
    if result["ok"]:
        ScraperSettings.from_env(dict(os.environ))
    return result


def _check_imports() -> dict[str, Any]:
    failed: list[str] = []
    for module_name in REQUIRED_IMPORTS:
        try:
            importlib.import_module(module_name)
        except Exception:
            failed.append(module_name)
    return {"failed": failed, "ok": len(failed) == 0}


def _check_dns() -> dict[str, Any]:
    targets = ["www.mof.gov.my", "www.moe.gov.my", "api.supabase.com"]
    failed: list[str] = []
    for host in targets:
        try:
            socket.gethostbyname(host)
        except Exception:
            failed.append(host)
    return {"failed": failed, "ok": len(failed) == 0}


def run_preflight(dry_run: bool = False) -> tuple[int, dict[str, Any]]:
    report: dict[str, Any] = {
        "env": _check_env(),
        "imports": _check_imports(),
    }

    if dry_run:
        report["dns"] = {"skipped": True}
        all_ok = report["imports"]["ok"]
    else:
        report["dns"] = _check_dns()
        all_ok = report["env"]["ok"] and report["imports"]["ok"] and report["dns"]["ok"]

    return (0 if all_ok else 1), report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate scraper runtime readiness")
    parser.add_argument("--dry-run", action="store_true", help="Skip external connectivity checks")
    args = parser.parse_args()

    try:
        code, report = run_preflight(dry_run=args.dry_run)
    except SettingsError as err:
        print(json.dumps({"ok": False, "error": str(err)}, indent=2))
        raise SystemExit(1)

    print(json.dumps(report, indent=2))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
