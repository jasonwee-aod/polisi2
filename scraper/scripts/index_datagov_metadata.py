#!/usr/bin/env python3
"""Index data.gov.my dataset metadata into the Supabase vector store.

Run once (or whenever the catalog changes) to embed dataset descriptions
so the chatbot can discover relevant live-data sources via semantic search.

Usage:
    python -m scripts.index_datagov_metadata [--dry-run]

Requires: OPENAI_API_KEY, SUPABASE_DB_URL in the environment (or .env).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

# Ensure project root on sys.path
_project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_project_root / "src"))

from polisi_scraper.config import ScraperSettings
from polisi_scraper.indexer.embeddings import OpenAIEmbeddingsClient
from polisi_scraper.indexer.store import DocumentsStore
from polisi_scraper.indexer.manifest import PendingIndexItem

# Import the catalog from the API package — add api/src to path
_api_root = Path(__file__).resolve().parents[2] / "api" / "src"
sys.path.insert(0, str(_api_root))

from polisi_api.chat.datagov import CATALOG, build_metadata_text


AGENCY = "data.gov.my"
STORAGE_PREFIX = "datagov-metadata/"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Index data.gov.my catalog metadata")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be indexed")
    args = parser.parse_args(argv)

    if args.dry_run:
        print(f"Would index {len(CATALOG)} dataset metadata entries:\n")
        for entry in CATALOG:
            text = build_metadata_text(entry)
            print(f"--- {entry.dataset_id} ({entry.title_en}) ---")
            print(text)
            print()
        return

    settings = ScraperSettings.from_env(require_indexer=True).require_indexer()
    embeddings_client = OpenAIEmbeddingsClient(settings.openai_api_key or "")
    store = DocumentsStore(settings.supabase_db_url)

    texts = []
    items = []
    for entry in CATALOG:
        text = build_metadata_text(entry)
        texts.append(text)

        storage_path = f"{STORAGE_PREFIX}{entry.dataset_id}.metadata"
        items.append(
            PendingIndexItem(
                storage_path=storage_path,
                agency=AGENCY,
                year_month="",
                filename=f"{entry.dataset_id}.metadata",
                file_type="metadata",
                version_token="v1",
                title=entry.title_en,
                source_url=f"https://data.gov.my/data-catalogue/{entry.dataset_id}",
                size_bytes=len(text.encode()),
                last_modified=None,
                metadata={
                    "datagov_dataset_id": entry.dataset_id,
                    "datagov_endpoint": entry.endpoint,
                    "source_type": "datagov_metadata",
                    "frequency": entry.frequency,
                    "category": entry.category,
                    "columns": ",".join(entry.columns),
                },
            )
        )

    print(f"Embedding {len(texts)} dataset metadata entries...")
    all_embeddings = embeddings_client.embed_texts(texts)
    print(f"Got {len(all_embeddings)} embeddings.")

    indexed = 0
    for item, text, embedding in zip(items, texts, all_embeddings, strict=True):
        sha256 = hashlib.sha256(text.encode()).hexdigest()
        store.persist_chunks(
            item,
            sha256=sha256,
            chunks=[text],
            embeddings=[embedding],
            chunk_metadata=[dict(item.metadata)],
        )
        indexed += 1
        print(f"  [{indexed}/{len(items)}] {item.title}")

    print(f"\nDone. Indexed {indexed} dataset metadata entries into Supabase.")


if __name__ == "__main__":
    main()
