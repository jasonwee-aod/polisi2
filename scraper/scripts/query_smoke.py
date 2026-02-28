from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polisi_scraper.config import ScraperSettings
from polisi_scraper.indexer.embeddings import OpenAIEmbeddingsClient
from polisi_scraper.indexer.store import DocumentsStore


DEFAULT_QUERIES = {
    "bm": "apakah bantuan kewangan untuk isi rumah berpendapatan rendah",
    "en": "what education support is available for students",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a BM/EN vector retrieval smoke query")
    parser.add_argument("--language", choices=["bm", "en"], default="bm")
    parser.add_argument("--query", default="")
    parser.add_argument("--limit", type=int, default=5)
    return parser


def run_smoke_query(
    query: str,
    *,
    limit: int,
    embeddings: OpenAIEmbeddingsClient,
    store: DocumentsStore,
) -> list[dict[str, object]]:
    query_embedding = embeddings.embed_texts([query])[0]
    results = store.match_documents(query_embedding, limit=limit)
    return [
        {
            "title": result.title,
            "agency": result.agency,
            "source_url": result.source_url,
            "storage_path": result.storage_path,
            "chunk_index": result.chunk_index,
            "similarity": result.similarity,
        }
        for result in results
    ]


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    settings = ScraperSettings.from_env(require_indexer=True).require_indexer()
    query = args.query or DEFAULT_QUERIES[args.language]

    embeddings = OpenAIEmbeddingsClient(settings.openai_api_key or "")
    store = DocumentsStore(settings.supabase_db_url)
    print(json.dumps(run_smoke_query(query, limit=args.limit, embeddings=embeddings, store=store), indent=2))
