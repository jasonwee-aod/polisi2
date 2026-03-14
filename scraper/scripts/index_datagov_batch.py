#!/usr/bin/env python3
"""Batch indexer for data_gov_my — memory-efficient, processes N files at a time.

Avoids loading all 20K+ objects into memory. Lists Spaces objects in pages,
checks fingerprints in small batches, and processes immediately.

Usage:
    python scraper/scripts/index_datagov_batch.py [--batch-size 50] [--max-total 500]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

for _env in [
    Path(__file__).resolve().parents[1] / ".env",
    Path(__file__).resolve().parents[2] / ".env",
    Path("/opt/polisigpt/.env"),
]:
    if _env.exists():
        load_dotenv(_env)
        break

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("index_datagov")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=50, help="Files per batch")
    parser.add_argument("--max-total", type=int, default=0, help="Total files to process (0=all)")
    args = parser.parse_args()

    import boto3
    import psycopg

    from polisi_scraper.config import ScraperSettings
    from polisi_scraper.core.dedup import compute_sha256
    from polisi_scraper.indexer.chunking import build_chunks
    from polisi_scraper.indexer.embeddings import OpenAIEmbeddingsClient
    from polisi_scraper.indexer.manifest import ManifestError, SpacesObject
    from polisi_scraper.indexer.parsers import get_parser
    from polisi_scraper.indexer.store import DocumentsStore

    settings = ScraperSettings.from_env(require_indexer=True).require_indexer()

    s3 = boto3.client(
        "s3",
        region_name=settings.do_spaces_region,
        endpoint_url=settings.do_spaces_endpoint,
        aws_access_key_id=settings.do_spaces_key,
        aws_secret_access_key=settings.do_spaces_secret,
    )
    embeddings = OpenAIEmbeddingsClient(settings.openai_api_key or "")
    store = DocumentsStore(settings.supabase_db_url)

    prefix = "gov-docs/data_gov_my/"
    processed = 0
    skipped = 0
    failed = 0
    continuation_token = None

    while True:
        # Page through S3 objects
        request = {"Bucket": settings.do_spaces_bucket, "Prefix": prefix, "MaxKeys": args.batch_size}
        if continuation_token:
            request["ContinuationToken"] = continuation_token

        response = s3.list_objects_v2(**request)
        objects = response.get("Contents", [])
        if not objects:
            break

        for obj in objects:
            if args.max_total and processed + skipped >= args.max_total:
                log.info("Reached max_total=%d", args.max_total)
                break

            key = obj["Key"]
            parts = key.split("/")
            if len(parts) != 7 or parts[2] != "raw":
                continue

            filename = parts[6]
            suffix = Path(filename).suffix.lower().lstrip(".")
            if suffix not in ("csv", "xlsx", "xls"):
                skipped += 1
                continue
            # Treat .xls as .xlsx for the parser (openpyxl handles both via xlrd fallback)
            parser_type = "xlsx" if suffix == "xls" else suffix

            # Version token from ETag
            etag = (obj.get("ETag") or "").strip('"') or key

            # Check fingerprint
            if store.has_fingerprint(key, etag):
                skipped += 1
                continue

            # Process this file
            try:
                log.info("[%d processed, %d skipped] Indexing %s", processed, skipped, filename[:60])

                # Fetch
                resp = s3.get_object(Bucket=settings.do_spaces_bucket, Key=key)
                payload = resp["Body"].read()

                sha256 = compute_sha256(payload)
                file_parser = get_parser(parser_type)
                parsed = file_parser.parse_bytes(
                    payload,
                    metadata={
                        "title": filename,
                        "source_url": None,
                        "agency": "data_gov_my",
                        "storage_path": key,
                        "version_token": etag,
                    },
                )

                if parsed.is_empty():
                    log.warning("Empty parse result: %s", key)
                    skipped += 1
                    continue

                chunks = build_chunks(parsed)
                chunk_texts = [chunk.text for chunk in chunks]

                if not chunk_texts:
                    skipped += 1
                    continue

                # Batch embeddings to stay under OpenAI's 300K token limit
                # ~4 chars per token, 300K tokens = ~1.2M chars, use 800K as safe limit
                EMBED_CHAR_LIMIT = 800_000
                embeddings_list = []
                batch_texts: list[str] = []
                batch_chars = 0
                for ct in chunk_texts:
                    if batch_texts and batch_chars + len(ct) > EMBED_CHAR_LIMIT:
                        embeddings_list.extend(embeddings.embed_texts(batch_texts))
                        batch_texts = []
                        batch_chars = 0
                    batch_texts.append(ct)
                    batch_chars += len(ct)
                if batch_texts:
                    embeddings_list.extend(embeddings.embed_texts(batch_texts))

                # Build a minimal item for persist_chunks
                from polisi_scraper.indexer.manifest import PendingIndexItem
                item = PendingIndexItem(
                    storage_path=key,
                    agency="data_gov_my",
                    year_month=f"{parts[3]}-{parts[4]}",
                    filename=filename,
                    file_type=suffix,
                    version_token=etag,
                    title=filename,
                )

                store.persist_chunks(
                    item,
                    sha256=sha256,
                    chunks=chunk_texts,
                    embeddings=embeddings_list,
                    chunk_metadata=[chunk.metadata for chunk in chunks],
                )
                processed += 1

                if processed % 10 == 0:
                    log.info("Progress: %d processed, %d skipped, %d failed", processed, skipped, failed)

            except Exception as exc:
                failed += 1
                log.warning("Failed %s: %s", key[:80], str(exc)[:200])

        if args.max_total and processed + skipped >= args.max_total:
            break

        if not response.get("IsTruncated"):
            break
        continuation_token = response.get("NextContinuationToken")

    log.info("=== DONE ===")
    log.info("Processed: %d", processed)
    log.info("Skipped: %d", skipped)
    log.info("Failed: %d", failed)


if __name__ == "__main__":
    main()
