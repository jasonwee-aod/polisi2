"""Embedding client fixed to the production retrieval model."""

from __future__ import annotations

from typing import Protocol

from openai import OpenAI


EMBEDDING_MODEL = "text-embedding-3-large"


class EmbeddingsProtocol(Protocol):
    def create(self, *, model: str, input: list[str]) -> object:
        """Return an OpenAI-style embeddings response."""


class OpenAIEmbeddingsClient:
    """Small wrapper around the OpenAI embeddings API."""

    def __init__(
        self,
        api_key: str,
        *,
        client: EmbeddingsProtocol | None = None,
        model: str = EMBEDDING_MODEL,
    ) -> None:
        self.model = model
        self._client = client or OpenAI(api_key=api_key).embeddings

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.create(model=self.model, input=texts)
        return [list(item.embedding) for item in response.data]
