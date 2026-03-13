"""End-to-end indexing orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from polisi_scraper.core.dedup import compute_sha256
from polisi_scraper.indexer.chunking import build_chunks
from polisi_scraper.indexer.manifest import PendingIndexItem, SpacesCorpusManifest
from polisi_scraper.indexer.parsers import get_parser
from polisi_scraper.indexer.store import DocumentsStore


class ObjectFetcher(Protocol):
    def get_bytes(self, storage_path: str) -> bytes:
        """Return raw file bytes for the given storage path."""


class EmbeddingsClient(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings for the provided texts."""


@dataclass(frozen=True)
class IndexingRunResult:
    processed_documents: int
    skipped_documents: int
    persisted_chunks: int
    failed_documents: int = 0


class IndexingPipeline:
    """Coordinates manifest discovery, parsing, embeddings, and persistence."""

    def __init__(
        self,
        manifest: SpacesCorpusManifest,
        fetcher: ObjectFetcher,
        embeddings: EmbeddingsClient,
        store: DocumentsStore,
    ) -> None:
        self._manifest = manifest
        self._fetcher = fetcher
        self._embeddings = embeddings
        self._store = store

    def run(
        self,
        *,
        max_items: int | None = None,
        mode: str = "incremental",
        storage_path: str | None = None,
    ) -> IndexingRunResult:
        pending_items = self._select_items(mode=mode)
        if storage_path:
            pending_items = [item for item in pending_items if item.storage_path == storage_path]
        if max_items is not None:
            pending_items = pending_items[:max_items]

        processed = 0
        persisted_chunks = 0
        failed = 0

        for item in pending_items:
            try:
                persisted_chunks += self._process_item(item)
                processed += 1
            except Exception as exc:
                failed += 1
                print(f"[indexer] skipped {item.storage_path}: {exc}")

        return IndexingRunResult(
            processed_documents=processed,
            skipped_documents=max(0, len(self._manifest.list_objects()) - processed - failed),
            persisted_chunks=persisted_chunks,
            failed_documents=failed,
        )

    def _select_items(self, *, mode: str) -> list[PendingIndexItem]:
        if mode == "full":
            return [
                PendingIndexItem(
                    storage_path=obj.storage_path,
                    agency=obj.agency,
                    year_month=obj.year_month,
                    filename=obj.filename,
                    file_type=obj.file_type,
                    version_token=obj.version_token,
                    title=obj.title,
                    source_url=obj.metadata.get("source_url") if isinstance(obj.metadata.get("source_url"), str) else None,
                    size_bytes=obj.size_bytes,
                    last_modified=obj.last_modified,
                    metadata=dict(obj.metadata),
                )
                for obj in self._manifest.list_objects()
            ]
        return self._manifest.pending_items(self._store)

    def _process_item(self, item: PendingIndexItem) -> int:
        payload = self._fetcher.get_bytes(item.storage_path)
        sha256 = compute_sha256(payload)
        parser = get_parser(item.file_type)
        parsed = parser.parse_bytes(
            payload,
            metadata={
                **item.metadata,
                "title": item.title,
                "source_url": item.source_url,
                "agency": item.agency,
                "storage_path": item.storage_path,
                "version_token": item.version_token,
            },
        )
        chunks = build_chunks(parsed)
        chunk_texts = [chunk.text for chunk in chunks]
        embeddings = self._embeddings.embed_texts(chunk_texts)
        self._store.persist_chunks(
            item,
            sha256=sha256,
            chunks=chunk_texts,
            embeddings=embeddings,
            chunk_metadata=[chunk.metadata for chunk in chunks],
        )
        return len(chunks)
