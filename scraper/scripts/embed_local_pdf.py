"""Embed a local PDF file and store chunks in pgvector.

Usage:
    cd scraper
    source .env
    python scripts/embed_local_pdf.py path/to/file.pdf [--agency test] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from dataclasses import asdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polisi_scraper.config import ScraperSettings
from polisi_scraper.core.dedup import compute_sha256
from polisi_scraper.indexer.chunking import build_chunks
from polisi_scraper.indexer.embeddings import OpenAIEmbeddingsClient
from polisi_scraper.indexer.manifest import PendingIndexItem
from polisi_scraper.indexer.parsers.pdf import PdfParser
from polisi_scraper.indexer.store import DocumentsStore


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Embed a local PDF and store in pgvector")
    p.add_argument("pdf", metavar="PDF", help="Path to the local PDF file")
    p.add_argument("--agency", default="local-test", help="Agency label (default: local-test)")
    p.add_argument("--dry-run", action="store_true", help="Parse and embed but do not write to DB")
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    pdf_path = pathlib.Path(args.pdf).resolve()
    if not pdf_path.exists():
        print(f"ERROR: file not found: {pdf_path}", file=sys.stderr)
        raise SystemExit(1)
    if pdf_path.suffix.lower() != ".pdf":
        print(f"ERROR: expected a .pdf file, got: {pdf_path.suffix}", file=sys.stderr)
        raise SystemExit(1)

    settings = ScraperSettings.from_env(require_indexer=True).require_indexer()

    payload = pdf_path.read_bytes()
    sha256 = compute_sha256(payload)
    print(f"File   : {pdf_path.name}")
    print(f"Size   : {len(payload):,} bytes")
    print(f"SHA256 : {sha256}")

    # Parse
    parser = PdfParser()
    parsed = parser.parse_bytes(
        payload,
        metadata={
            "title": pdf_path.stem.replace("_", " "),
            "source_url": None,
            "agency": args.agency,
            "storage_path": f"local/{pdf_path.name}",
            "version_token": sha256,
        },
    )
    print(f"Pages  : {len(parsed.blocks)} non-empty page(s) extracted")

    if not parsed.blocks:
        print("WARNING: no text extracted — PDF may be scanned/image-only")
        raise SystemExit(0)

    # Chunk
    chunks = build_chunks(parsed)
    print(f"Chunks : {len(chunks)}")
    for i, chunk in enumerate(chunks):
        print(f"  [{i}] {len(chunk.text)} chars  metadata={json.dumps(chunk.metadata, default=str)[:120]}")

    if args.dry_run:
        print("\n[dry-run] Skipping embed + DB write.")
        raise SystemExit(0)

    # Embed
    embeddings_client = OpenAIEmbeddingsClient(settings.openai_api_key or "")
    chunk_texts = [chunk.text for chunk in chunks]
    print(f"\nEmbedding {len(chunk_texts)} chunk(s) with text-embedding-3-large …")
    embeddings = embeddings_client.embed_texts(chunk_texts)
    print(f"Embedding dim : {len(embeddings[0]) if embeddings else 0}")

    # Store
    item = PendingIndexItem(
        storage_path=f"local/{pdf_path.name}",
        agency=args.agency,
        year_month="0000-00",
        filename=pdf_path.name,
        file_type="pdf",
        version_token=sha256,
        title=pdf_path.stem.replace("_", " "),
        source_url=f"file://{pdf_path}",
        metadata={},
    )
    store = DocumentsStore(settings.supabase_db_url)
    stored = store.persist_chunks(
        item,
        sha256=sha256,
        chunks=chunk_texts,
        embeddings=embeddings,
        chunk_metadata=[chunk.metadata for chunk in chunks],
    )
    print(f"\nStored {len(stored)} chunk(s) in pgvector.")
    print("Done.")


if __name__ == "__main__":
    main()
