"""Cross-encoder reranking for retrieved chunks."""

from __future__ import annotations

import json
import re
from typing import Protocol

from anthropic import AsyncAnthropic

from .retrieval import RetrievedChunk


class Reranker(Protocol):
    async def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        top_n: int,
    ) -> list[RetrievedChunk]: ...


class NoOpReranker:
    """Pass-through reranker that returns chunks unchanged (truncated to top_n)."""

    async def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        top_n: int,
    ) -> list[RetrievedChunk]:
        return chunks[:top_n]


class ClaudeReranker:
    """Reranker that uses Claude Haiku to score chunk relevance."""

    def __init__(self, client: AsyncAnthropic, *, model: str = "claude-3-5-haiku-latest") -> None:
        self._client = client
        self._model = model

    async def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        top_n: int,
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []
        if len(chunks) <= 1:
            return chunks[:top_n]

        # Build a single batched prompt asking for relevance scores
        chunk_descriptions = []
        for i, chunk in enumerate(chunks):
            text_preview = chunk.chunk_text[:300]
            chunk_descriptions.append(
                f"CHUNK {i}: [{chunk.title} | {chunk.agency}] {text_preview}"
            )

        chunks_text = "\n".join(chunk_descriptions)
        prompt = (
            f"Rate each chunk's relevance to the query on a scale of 0-10.\n"
            f"Query: {query}\n\n"
            f"{chunks_text}\n\n"
            f"Return ONLY a JSON array of objects with 'index' and 'score' keys, "
            f"e.g. [{{'index': 0, 'score': 8}}, ...]. No other text."
        )

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=512,
                system="You are a relevance scoring assistant. Return only valid JSON.",
                messages=[{"role": "user", "content": prompt}],
            )

            text = ""
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    text += block.text

            scores = self._parse_scores(text, len(chunks))

            # Pair chunks with scores and sort descending
            scored = sorted(
                zip(scores, chunks),
                key=lambda pair: pair[0],
                reverse=True,
            )
            return [chunk for _, chunk in scored][:top_n]

        except Exception:
            # Fallback: return original order truncated
            return chunks[:top_n]

    @staticmethod
    def _parse_scores(text: str, num_chunks: int) -> list[float]:
        """Parse the JSON scores from Claude's response."""
        # Try to extract JSON array from the response
        text = text.strip()
        # Find JSON array in the text
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return list(range(num_chunks, 0, -1))  # fallback: original order scores

        try:
            parsed = json.loads(match.group())
        except json.JSONDecodeError:
            return list(range(num_chunks, 0, -1))

        scores = [0.0] * num_chunks
        for item in parsed:
            if isinstance(item, dict) and "index" in item and "score" in item:
                idx = int(item["index"])
                if 0 <= idx < num_chunks:
                    scores[idx] = float(item["score"])

        return scores
