"""Retrieval adapters for the policy corpus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx
import psycopg

from polisi_api.config import Settings


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: str | None
    title: str
    agency: str
    source_url: str
    chunk_text: str
    similarity: float
    chunk_index: int | None = None
    metadata: dict[str, object] | None = None


class Retriever(Protocol):
    async def retrieve(self, question: str, *, limit: int) -> list[RetrievedChunk]: ...


class OpenAIEmbeddingClient:
    """Minimal async embeddings client using the OpenAI HTTP API."""

    def __init__(self, api_key: str, *, model: str = "text-embedding-3-large") -> None:
        self._api_key = api_key
        self._model = model

    async def embed(self, text: str) -> list[float]:
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


class PostgresRetriever:
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

    async def retrieve(self, question: str, *, limit: int) -> list[RetrievedChunk]:
        embedding = await self._embedding_client.embed(question)
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


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.12g}" for value in values) + "]"
