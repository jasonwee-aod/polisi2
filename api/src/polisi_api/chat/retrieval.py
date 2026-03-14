"""Retrieval adapters for the policy corpus."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
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
    _fts_floor: float = 0.50

    @property
    def effective_similarity(self) -> float:
        """Similarity score used for threshold decisions.

        For chunks found only via full-text search (cosine similarity ≈ 0),
        returns the configured floor so they land in "limited-support" mode
        rather than being discarded.
        """
        if self.similarity > 0:
            return self.similarity
        if self.fts_rank > 0:
            return self._fts_floor
        return 0.0


@dataclass(frozen=True)
class RetrievalFilters:
    agency: str | None = None
    date_from: str | None = None
    date_to: str | None = None


def deduplicate_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Remove near-duplicate chunks.

    1. Adjacent chunks from the same document (chunk_index ±1) — keep higher score.
    2. Chunks with >70% Jaccard word-set overlap — keep higher score.
    """
    if len(chunks) <= 1:
        return list(chunks)

    # Pass 1: remove adjacent same-document duplicates
    keep: list[RetrievedChunk] = []
    removed_indices: set[int] = set()

    # Sort by (document_id, chunk_index) to identify adjacency, but we need
    # to compare every pair, so do pairwise checks on the original list.
    for i, chunk_i in enumerate(chunks):
        if i in removed_indices:
            continue
        for j in range(i + 1, len(chunks)):
            if j in removed_indices:
                continue
            chunk_j = chunks[j]
            if (
                chunk_i.document_id is not None
                and chunk_i.document_id == chunk_j.document_id
                and chunk_i.chunk_index is not None
                and chunk_j.chunk_index is not None
                and abs(chunk_i.chunk_index - chunk_j.chunk_index) <= 1
            ):
                # Keep the one with higher effective_similarity
                if chunk_i.effective_similarity >= chunk_j.effective_similarity:
                    removed_indices.add(j)
                else:
                    removed_indices.add(i)
                    break  # chunk_i is removed, stop comparing it

    surviving = [c for idx, c in enumerate(chunks) if idx not in removed_indices]

    # Pass 2: Jaccard word-set overlap > 70%
    removed_indices2: set[int] = set()
    word_sets = [set(c.chunk_text.lower().split()) for c in surviving]

    for i in range(len(surviving)):
        if i in removed_indices2:
            continue
        for j in range(i + 1, len(surviving)):
            if j in removed_indices2:
                continue
            ws_i, ws_j = word_sets[i], word_sets[j]
            union_size = len(ws_i | ws_j)
            if union_size == 0:
                continue
            jaccard = len(ws_i & ws_j) / union_size
            if jaccard > 0.70:
                if surviving[i].effective_similarity >= surviving[j].effective_similarity:
                    removed_indices2.add(j)
                else:
                    removed_indices2.add(i)
                    break

    return [c for idx, c in enumerate(surviving) if idx not in removed_indices2]


def apply_metadata_boost(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Boost chunks with recent publication dates.

    Recency boost: 1.0 + 0.1 * max(0, 5 - years_since_publication).
    Multiplied against rrf_score (or effective_similarity as fallback).
    Returns a new list sorted by boosted score descending.
    """
    if not chunks:
        return []

    today = date.today()
    scored: list[tuple[float, RetrievedChunk]] = []

    for chunk in chunks:
        boost = 1.0
        if chunk.metadata:
            published_raw = chunk.metadata.get("published_at")
            if published_raw is not None:
                try:
                    if isinstance(published_raw, date):
                        pub_date = published_raw
                    elif isinstance(published_raw, datetime):
                        pub_date = published_raw.date()
                    elif isinstance(published_raw, str):
                        pub_date = date.fromisoformat(published_raw[:10])
                    else:
                        pub_date = None

                    if pub_date is not None:
                        years_since = (today - pub_date).days / 365.25
                        boost = 1.0 + 0.1 * max(0.0, 5.0 - years_since)
                except (ValueError, TypeError):
                    pass  # Gracefully handle bad dates

        base_score = chunk.rrf_score if chunk.rrf_score > 0 else chunk.effective_similarity
        boosted = base_score * boost
        scored.append((boosted, chunk))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [chunk for _, chunk in scored]


def apply_adaptive_cutoff(
    chunks: list[RetrievedChunk],
    dropoff_ratio: float,
    max_chunks: int,
) -> list[RetrievedChunk]:
    """Drop chunks below top_similarity * dropoff_ratio, always keeping at least 1."""
    if not chunks:
        return []

    top_sim = chunks[0].effective_similarity
    threshold = top_sim * dropoff_ratio

    result = [c for c in chunks if c.effective_similarity >= threshold]
    if not result:
        result = [chunks[0]]

    return result[:max_chunks]


def _merge_rrf(
    result_lists: list[list[RetrievedChunk]],
    k: int = 60,
) -> list[RetrievedChunk]:
    """Merge multiple ranked result lists using Reciprocal Rank Fusion."""
    scores: dict[tuple[str | None, int | None], float] = defaultdict(float)
    best_chunk: dict[tuple[str | None, int | None], RetrievedChunk] = {}

    for results in result_lists:
        for rank, chunk in enumerate(results):
            key = (chunk.document_id, chunk.chunk_index)
            scores[key] += 1.0 / (k + rank + 1)
            if key not in best_chunk or chunk.effective_similarity > best_chunk[key].effective_similarity:
                best_chunk[key] = chunk

    sorted_keys = sorted(scores.keys(), key=lambda k_: scores[k_], reverse=True)
    return [best_chunk[k_] for k_ in sorted_keys]


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
        self._http = httpx.AsyncClient(timeout=30)

    async def embed(self, text: str) -> list[float]:
        try:
            response = await self._http.post(
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


def _row_to_chunk(
    row: tuple,
    *,
    fts_floor: float = 0.50,
    has_fts: bool = False,
) -> RetrievedChunk:
    """Map a database row to a RetrievedChunk."""
    return RetrievedChunk(
        document_id=str(row[0]) if row[0] is not None else None,
        title=row[1],
        source_url=row[2],
        agency=row[3],
        chunk_index=row[4],
        chunk_text=row[5],
        metadata=row[6] if isinstance(row[6], dict) else {},
        similarity=float(row[7]),
        fts_rank=float(row[8]) if has_fts else 0.0,
        rrf_score=float(row[9]) if has_fts else 0.0,
        _fts_floor=fts_floor,
    )


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

        return [_row_to_chunk(row) for row in rows]


class HybridPostgresRetriever:
    """Hybrid retriever combining vector similarity and full-text search via RRF.

    When ``fts_only`` is True (or auto-detected because no vector index exists),
    falls back to the fast ``fts_match_documents`` function that uses the GIN
    index only.  Set ``RETRIEVAL_FTS_ONLY=true`` to force this mode.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        embedding_client: OpenAIEmbeddingClient | None = None,
        fts_only: bool = False,
    ) -> None:
        self._settings = settings
        self._fts_floor = settings.retrieval_fts_min_similarity
        self._fts_only = fts_only or getattr(settings, "retrieval_fts_only", False)
        self._embedding_client = embedding_client or OpenAIEmbeddingClient(
            settings.openai_api_key or ""
        )

    async def _fts_retrieve(
        self, question: str, *, limit: int, filters: RetrievalFilters | None = None,
    ) -> list[RetrievedChunk]:
        """Fast full-text-search-only retrieval using the GIN index."""
        f = filters or RetrievalFilters()
        with psycopg.connect(self._settings.supabase_db_url) as conn:
            rows = conn.execute(
                """
                select id, title, source_url, agency,
                       chunk_index, chunk_text, metadata,
                       similarity, fts_rank, rrf_score,
                       parent_chunk_text
                from public.fts_match_documents(%s, %s, %s)
                """,
                (question, limit, f.agency),
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
                _fts_floor=self._fts_floor,
            )
            for row in rows
        ]

    async def retrieve(
        self,
        question: str,
        *,
        limit: int,
        filters: RetrievalFilters | None = None,
    ) -> list[RetrievedChunk]:
        if self._fts_only:
            return await self._fts_retrieve(question, limit=limit, filters=filters)

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
            _row_to_chunk(row, fts_floor=self._fts_floor, has_fts=True)
            for row in rows
        ]

    async def retrieve_multi(
        self,
        queries: list[str],
        *,
        limit: int,
        filters: RetrievalFilters | None = None,
    ) -> list[RetrievedChunk]:
        """Retrieve using multiple queries, merge via RRF."""
        if not queries:
            return []

        if self._fts_only:
            result_lists: list[list[RetrievedChunk]] = []
            for query_text in queries:
                chunks = await self._fts_retrieve(query_text, limit=limit, filters=filters)
                result_lists.append(chunks)
            return _merge_rrf(result_lists)[:limit]

        # Embed all queries concurrently
        embeddings = await asyncio.gather(
            *(self._embedding_client.embed(q) for q in queries)
        )

        f = filters or RetrievalFilters()

        result_lists = []
        for query_text, embedding in zip(queries, embeddings):
            if not embedding:
                continue
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
                        query_text,
                        limit,
                        f.agency,
                        f.date_from,
                        f.date_to,
                        self._settings.retrieval_rrf_k,
                    ),
                ).fetchall()
            result_lists.append([
                _row_to_chunk(row, fts_floor=self._fts_floor, has_fts=True)
                for row in rows
            ])

        if not result_lists:
            return []

        merged = _merge_rrf(result_lists, k=self._settings.retrieval_rrf_k)
        return merged[:limit]


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.12g}" for value in values) + "]"
