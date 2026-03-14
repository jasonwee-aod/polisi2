"""Persistence layer for indexed document chunks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import json
import math
from typing import Any, Callable

import psycopg

from polisi_scraper.indexer.manifest import PendingIndexItem
from polisi_scraper.indexer.state import IndexedFingerprintRecord, IndexedFingerprintStore


@dataclass(frozen=True)
class StoredChunk:
    title: str
    source_url: str | None
    agency: str
    published_at: date | None
    file_type: str
    sha256: str
    storage_path: str
    version_token: str
    chunk_index: int
    chunk_text: str
    embedding: list[float]
    metadata: dict[str, object] = field(default_factory=dict)
    parent_chunk_text: str | None = None


@dataclass(frozen=True)
class SearchResult:
    title: str
    agency: str
    source_url: str | None
    storage_path: str
    chunk_index: int
    chunk_text: str
    metadata: dict[str, object]
    similarity: float


class DocumentsStore(IndexedFingerprintStore):
    """Chunk persistence backed by either memory or Postgres."""

    def __init__(
        self,
        db_url: str | None = None,
        *,
        records: list[StoredChunk] | None = None,
        connection_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._db_url = db_url
        self._records = records if records is not None else []
        self._connection_factory = connection_factory

    def has_fingerprint(self, storage_path: str, version_token: str) -> bool:
        if self._db_url or self._connection_factory:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    select 1
                    from public.documents
                    where storage_path = %s and version_token = %s
                    limit 1
                    """,
                    (storage_path, version_token),
                ).fetchone()
            return row is not None

        return any(
            record.storage_path == storage_path and record.version_token == version_token
            for record in self._records
        )

    def mark_indexed(
        self,
        storage_path: str,
        version_token: str,
        *,
        document_count: int = 0,
    ) -> IndexedFingerprintRecord:
        return IndexedFingerprintRecord(
            storage_path=storage_path,
            version_token=version_token,
            document_count=document_count,
        )

    def persist_chunks(
        self,
        item: PendingIndexItem,
        *,
        sha256: str,
        chunks: list[str],
        embeddings: list[list[float]],
        chunk_metadata: list[dict[str, object]],
        parent_texts: list[str | None] | None = None,
    ) -> list[StoredChunk]:
        stored: list[StoredChunk] = []
        _parent_texts = parent_texts or [None] * len(chunks)
        for index, (chunk_text, embedding, metadata, parent_text) in enumerate(
            zip(chunks, embeddings, chunk_metadata, _parent_texts, strict=True)
        ):
            stored.append(
                StoredChunk(
                    title=item.title,
                    source_url=item.source_url,
                    agency=item.agency,
                    published_at=None,
                    file_type=item.file_type,
                    sha256=sha256,
                    storage_path=item.storage_path,
                    version_token=item.version_token,
                    chunk_index=index,
                    chunk_text=chunk_text,
                    embedding=embedding,
                    metadata=dict(metadata),
                    parent_chunk_text=parent_text,
                )
            )

        if self._db_url or self._connection_factory:
            with self._connect() as conn:
                for record in stored:
                    conn.execute(
                        """
                        insert into public.documents (
                          title,
                          source_url,
                          agency,
                          published_at,
                          file_type,
                          sha256,
                          storage_path,
                          version_token,
                          chunk_index,
                          chunk_text,
                          embedding,
                          metadata,
                          parent_chunk_text
                        ) values (
                          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s::jsonb, %s
                        )
                        on conflict (storage_path, version_token, chunk_index)
                        do update set
                          title = excluded.title,
                          source_url = excluded.source_url,
                          agency = excluded.agency,
                          published_at = excluded.published_at,
                          file_type = excluded.file_type,
                          sha256 = excluded.sha256,
                          chunk_text = excluded.chunk_text,
                          embedding = excluded.embedding,
                          metadata = excluded.metadata,
                          parent_chunk_text = excluded.parent_chunk_text
                        """,
                        (
                            record.title,
                            record.source_url,
                            record.agency,
                            record.published_at,
                            record.file_type,
                            record.sha256,
                            record.storage_path,
                            record.version_token,
                            record.chunk_index,
                            record.chunk_text,
                            _vector_literal(record.embedding),
                            json.dumps(record.metadata, sort_keys=True),
                            record.parent_chunk_text,
                        ),
                    )
                conn.commit()
        else:
            self._records.extend(stored)

        return stored

    def match_documents(self, query_embedding: list[float], *, limit: int = 5) -> list[SearchResult]:
        if self._db_url or self._connection_factory:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    select title, agency, source_url, storage_path, chunk_index, chunk_text, metadata, similarity
                    from public.match_documents(%s::vector, %s)
                    """,
                    (_vector_literal(query_embedding), limit),
                ).fetchall()
            return [
                SearchResult(
                    title=row[0],
                    agency=row[1],
                    source_url=row[2],
                    storage_path=row[3],
                    chunk_index=row[4],
                    chunk_text=row[5],
                    metadata=row[6] if isinstance(row[6], dict) else json.loads(row[6]),
                    similarity=float(row[7]),
                )
                for row in rows
            ]

        ranked = []
        for record in self._records:
            similarity = _cosine_similarity(query_embedding, record.embedding)
            ranked.append(
                SearchResult(
                    title=record.title,
                    agency=record.agency,
                    source_url=record.source_url,
                    storage_path=record.storage_path,
                    chunk_index=record.chunk_index,
                    chunk_text=record.chunk_text,
                    metadata=dict(record.metadata),
                    similarity=similarity,
                )
            )
        ranked.sort(key=lambda item: item.similarity, reverse=True)
        return ranked[:limit]

    def _connect(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory()
        if self._db_url is None:
            raise RuntimeError("DocumentsStore requires a db_url or connection_factory")
        return psycopg.connect(self._db_url)


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.12g}" for value in values) + "]"


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
