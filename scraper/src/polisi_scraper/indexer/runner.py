"""CLI runner for incremental indexing."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from typing import Any

import boto3

from polisi_scraper.config import ScraperSettings
from polisi_scraper.indexer.embeddings import OpenAIEmbeddingsClient
from polisi_scraper.indexer.manifest import SpacesCorpusManifest
from polisi_scraper.indexer.pipeline import IndexingPipeline
from polisi_scraper.indexer.store import DocumentsStore


class SpacesObjectFetcher:
    def __init__(self, settings: ScraperSettings, *, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client

    def get_bytes(self, storage_path: str) -> bytes:
        client = self._ensure_client()
        response = client.get_object(Bucket=self._settings.do_spaces_bucket, Key=storage_path)
        return response["Body"].read()

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        self._client = boto3.client(
            "s3",
            region_name=self._settings.do_spaces_region,
            endpoint_url=self._settings.do_spaces_endpoint,
            aws_access_key_id=self._settings.do_spaces_key,
            aws_secret_access_key=self._settings.do_spaces_secret,
        )
        return self._client


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Polisi indexing pipeline")
    parser.add_argument(
        "--mode",
        choices=["incremental", "full"],
        default="incremental",
        help="Incremental skips indexed versions; full reprocesses all discovered objects",
    )
    parser.add_argument("--max-items", type=int, default=None, help="Limit pending objects per run")
    parser.add_argument("--dry-run", action="store_true", help="List configuration without indexing")
    parser.add_argument(
        "--storage-path",
        default="",
        help="Optional exact storage path to index after manifest discovery",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = ScraperSettings.from_env(require_indexer=True).require_indexer()
    if args.dry_run:
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": "dry-run",
                    "run_mode": args.mode,
                    "max_items": args.max_items,
                    "storage_path": args.storage_path or None,
                    "settings": {
                        "indexer_spaces_prefix": settings.indexer_spaces_prefix,
                        "indexer_batch_size": settings.indexer_batch_size,
                    },
                },
                indent=2,
            )
        )
        return

    manifest = SpacesCorpusManifest(settings)
    store = DocumentsStore(settings.supabase_db_url)
    pipeline = IndexingPipeline(
        manifest,
        SpacesObjectFetcher(settings),
        OpenAIEmbeddingsClient(settings.openai_api_key or ""),
        store,
    )
    result = pipeline.run(
        max_items=args.max_items,
        mode=args.mode,
        storage_path=args.storage_path or None,
    )
    print(json.dumps(asdict(result), indent=2))
