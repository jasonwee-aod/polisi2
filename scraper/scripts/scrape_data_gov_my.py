#!/usr/bin/env python3
"""Standalone scraper for archive.data.gov.my — runs locally, uploads to DO Spaces.

Usage:
    python scraper/scripts/scrape_data_gov_my.py [--max-datasets N] [--dry-run]

Discovers datasets via the CKAN API, downloads CSV/XLSX resources,
and uploads them to DO Spaces under gov-docs/data_gov_my/raw/.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import boto3
import requests
from dotenv import load_dotenv

# Load env
for _env in [
    Path(__file__).resolve().parents[1] / ".env",   # scraper/.env
    Path(__file__).resolve().parents[2] / ".env",   # repo root/.env
    Path("/opt/polisigpt/.env"),                     # Droplet
]:
    if _env.exists():
        load_dotenv(_env)
        break

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("data_gov_my")

API_BASE = "https://archive.data.gov.my/data/api/3/action"
ROWS_PER_PAGE = 1000
WANTED_FORMATS = {"csv", "xlsx", "xls", "pdf", "json", "xml", "doc", "docx"}
REQUEST_DELAY = 0.3
SLUG = "data_gov_my"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def spaces_path(sha256: str, filename: str) -> str:
    now = datetime.now(timezone.utc)
    return f"gov-docs/{SLUG}/raw/{now:%Y/%m/%d}/{sha256}_{filename}"


def build_s3_client():
    return boto3.client(
        "s3",
        region_name=os.environ["DO_SPACES_REGION"],
        endpoint_url=os.environ["DO_SPACES_ENDPOINT"],
        aws_access_key_id=os.environ["DO_SPACES_KEY"],
        aws_secret_access_key=os.environ["DO_SPACES_SECRET"],
    )


def discover_resources(max_datasets: int = 0) -> list[dict]:
    """Fetch all dataset resources from the CKAN API."""
    resources = []
    start = 0
    total = None
    session = requests.Session()
    session.headers["User-Agent"] = "PolisiScraper/2.0 (+https://polisigpt.local)"

    while True:
        url = f"{API_BASE}/package_search?rows={ROWS_PER_PAGE}&start={start}"
        log.info("Fetching datasets start=%d", start)

        resp = session.get(url, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            log.error("API returned success=false")
            break

        result = data["result"]
        if total is None:
            total = result["count"]
            log.info("Total datasets: %d", total)

        datasets = result.get("results", [])
        if not datasets:
            break

        for ds in datasets:
            ds_title = ds.get("title", ds.get("name", ""))
            ds_name = ds.get("name", "")
            ds_modified = ds.get("metadata_modified", "")[:10]
            org = ds.get("organization") or {}
            org_name = org.get("title", org.get("name", ""))

            for res in ds.get("resources", []):
                fmt = (res.get("format") or "").lower().strip()
                if fmt not in WANTED_FORMATS:
                    continue
                res_url = res.get("url", "")
                if not res_url:
                    continue

                res_name = res.get("name", "") or res.get("description", "") or ds_title
                resources.append({
                    "url": res_url,
                    "title": f"{ds_title} — {res_name}".strip(" —"),
                    "dataset_name": ds_name,
                    "dataset_id": ds.get("id", ""),
                    "resource_id": res.get("id", ""),
                    "format": fmt,
                    "organization": org_name,
                    "modified": (res.get("last_modified") or ds_modified)[:10],
                    "size": res.get("size"),
                })

        start += ROWS_PER_PAGE
        if max_datasets and start >= max_datasets:
            log.info("Reached max_datasets=%d", max_datasets)
            break
        if start >= total:
            break
        time.sleep(REQUEST_DELAY)

    log.info("Discovered %d resources from %d datasets", len(resources), total or 0)
    return resources


def download_and_upload(resources: list[dict], dry_run: bool = False) -> dict:
    """Download each resource and upload to DO Spaces."""
    s3 = build_s3_client() if not dry_run else None
    bucket = os.environ.get("DO_SPACES_BUCKET", "") if not dry_run else ""
    session = requests.Session()
    session.headers["User-Agent"] = "PolisiScraper/2.0 (+https://polisigpt.local)"

    stats = {"downloaded": 0, "uploaded": 0, "skipped": 0, "failed": 0}

    for i, res in enumerate(resources):
        url = res["url"]
        fmt = res["format"]

        # Derive filename
        url_path = urlparse(url).path
        filename = Path(url_path).name or f"{res['resource_id']}.{fmt}"
        if not Path(filename).suffix:
            filename = f"{filename}.{fmt}"

        try:
            log.info("[%d/%d] Downloading %s (%s)", i + 1, len(resources), filename[:60], fmt)
            resp = session.get(url, timeout=60, stream=True)
            resp.raise_for_status()
            payload = resp.content

            if len(payload) < 10:
                log.warning("Skipping empty file: %s", url)
                stats["skipped"] += 1
                continue

            stats["downloaded"] += 1

            if dry_run:
                log.info("  [dry-run] Would upload %d bytes as %s", len(payload), filename)
                continue

            sha = sha256_bytes(payload)
            obj_path = spaces_path(sha, filename)
            ct = resp.headers.get("content-type", f"application/{fmt}")

            s3.put_object(
                Bucket=bucket,
                Key=obj_path,
                Body=payload,
                ContentType=ct,
                ACL="private",
            )
            stats["uploaded"] += 1

            if stats["uploaded"] % 100 == 0:
                log.info("Progress: %d uploaded, %d failed", stats["uploaded"], stats["failed"])

        except Exception as exc:
            stats["failed"] += 1
            log.warning("Failed %s: %s", url[:80], exc)

        time.sleep(REQUEST_DELAY)

    return stats


def main():
    parser = argparse.ArgumentParser(description="Scrape archive.data.gov.my to DO Spaces")
    parser.add_argument("--max-datasets", type=int, default=0, help="Limit API pagination (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="Download but don't upload")
    args = parser.parse_args()

    log.info("=== data.gov.my scraper ===")
    resources = discover_resources(max_datasets=args.max_datasets)

    if not resources:
        log.info("No resources found")
        return

    log.info("Starting download/upload of %d resources...", len(resources))
    stats = download_and_upload(resources, dry_run=args.dry_run)

    log.info("=== DONE ===")
    log.info("Downloaded: %d", stats["downloaded"])
    log.info("Uploaded: %d", stats["uploaded"])
    log.info("Skipped: %d", stats["skipped"])
    log.info("Failed: %d", stats["failed"])


if __name__ == "__main__":
    main()
