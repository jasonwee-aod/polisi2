"""Retrieval adapters for the policy corpus."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import httpx
import psycopg

from polisi_api.config import Settings


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: str | None
    title: str
    agency: str
    source_url: str | None
    chunk_text: str
    similarity: float
    chunk_index: int | None = None
    metadata: dict[str, object] | None = None
    fts_rank: float = 0.0
    rrf_score: float = 0.0

    @property
    def effective_similarity(self) -> float:
        """Similarity score used for threshold decisions.

        For chunks found only via full-text search (cosine similarity ≈ 0),
        returns a configurable floor so they land in "limited-support" mode
        rather than being discarded.
        """
        if self.similarity > 0:
            return self.similarity
        if self.fts_rank > 0:
            return _FTS_SIMILARITY_FLOOR
        return 0.0


# Floor similarity assigned to FTS-only matches for threshold routing.
# Overridden via Settings.retrieval_fts_min_similarity at runtime.
_FTS_SIMILARITY_FLOOR = 0.50


@dataclass(frozen=True)
class RetrievalFilters:
    agency: str | None = None
    date_from: str | None = None
    date_to: str | None = None


class Retriever(Protocol):
    async def retrieve(
        self,
        question: str,
        *,
        limit: int,
        filters: RetrievalFilters | None = None,
    ) -> list[RetrievedChunk]: ...


class OpenAIEmbeddingClient:
    """Minimal async embeddings client using the OpenAI HTTP API."""

    def __init__(self, api_key: str, *, model: str = "text-embedding-3-large") -> None:
        self._api_key = api_key
        self._model = model

    async def embed(self, text: str) -> list[float]:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"input": text, "model": self._model},
                )
                response.raise_for_status()
            payload = response.json()
            return [float(value) for value in payload["data"][0]["embedding"]]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                return []
            raise


class PostgresRetriever:
    """Vector-only retriever (legacy). Use HybridPostgresRetriever for new work."""

    def __init__(
        self,
        settings: Settings,
        *,
        embedding_client: OpenAIEmbeddingClient | None = None,
    ) -> None:
        self._settings = settings
        self._embedding_client = embedding_client or OpenAIEmbeddingClient(
            settings.openai_api_key or ""
        )

    async def retrieve(
        self,
        question: str,
        *,
        limit: int,
        filters: RetrievalFilters | None = None,
    ) -> list[RetrievedChunk]:
        embedding = await self._embedding_client.embed(question)
        if not embedding:
            return []
        with psycopg.connect(self._settings.supabase_db_url) as conn:
            rows = conn.execute(
                """
                select id, title, source_url, agency, chunk_index, chunk_text, metadata, similarity
                from public.match_documents(%s::vector, %s)
                """,
                (_vector_literal(embedding), limit),
            ).fetchall()

        return [
            RetrievedChunk(
                document_id=str(row[0]) if row[0] is not None else None,
                title=row[1],
                source_url=row[2],
                agency=row[3],
                chunk_index=row[4],
                chunk_text=row[5],
                metadata=row[6] if isinstance(row[6], dict) else {},
                similarity=float(row[7]),
            )
            for row in rows
        ]


class HybridPostgresRetriever:
    """Hybrid retriever combining vector similarity and full-text search via RRF."""

    def __init__(
        self,
        settings: Settings,
        *,
        embedding_client: OpenAIEmbeddingClient | None = None,
    ) -> None:
        self._settings = settings
        self._embedding_client = embedding_client or OpenAIEmbeddingClient(
            settings.openai_api_key or ""
        )
        global _FTS_SIMILARITY_FLOOR
        _FTS_SIMILARITY_FLOOR = settings.retrieval_fts_min_similarity

    async def retrieve(
        self,
        question: str,
        *,
        limit: int,
        filters: RetrievalFilters | None = None,
    ) -> list[RetrievedChunk]:
        embedding = await self._embedding_client.embed(question)
        if not embedding:
            return []

        f = filters or RetrievalFilters()

        with psycopg.connect(self._settings.supabase_db_url) as conn:
            rows = conn.execute(
                """
                select id, title, source_url, agency,
                       chunk_index, chunk_text, metadata,
                       similarity, fts_rank, rrf_score
                from public.hybrid_match_documents(
                    %s::vector, %s, %s, %s, %s::date, %s::date, %s
                )
                """,
                (
                    _vector_literal(embedding),
                    question,
                    limit,
                    f.agency,
                    f.date_from,
                    f.date_to,
                    self._settings.retrieval_rrf_k,
                ),
            ).fetchall()

        return [
            RetrievedChunk(
                document_id=str(row[0]) if row[0] is not None else None,
                title=row[1],
                source_url=row[2],
                agency=row[3],
                chunk_index=row[4],
                chunk_text=row[5],
                metadata=row[6] if isinstance(row[6], dict) else {},
                similarity=float(row[7]),
                fts_rank=float(row[8]),
                rrf_score=float(row[9]),
            )
            for row in rows
        ]


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.12g}" for value in values) + "]"
