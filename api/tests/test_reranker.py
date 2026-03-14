"""Tests for the reranker module."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from polisi_api.chat.reranker import ClaudeReranker, NoOpReranker
from polisi_api.chat.retrieval import RetrievedChunk


def _chunk(index: int, similarity: float = 0.8) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=f"doc-{index}",
        title=f"Title {index}",
        agency="AGY",
        source_url=None,
        chunk_text=f"Content of chunk {index} about government policy matters",
        similarity=similarity,
        chunk_index=index,
    )


def test_noop_reranker_truncates() -> None:
    asyncio.run(_run_noop())


async def _run_noop() -> None:
    reranker = NoOpReranker()
    chunks = [_chunk(i) for i in range(10)]
    result = await reranker.rerank("query", chunks, top_n=5)
    assert len(result) == 5
    # Order preserved
    assert result[0].document_id == "doc-0"
    assert result[4].document_id == "doc-4"


def test_noop_reranker_empty() -> None:
    asyncio.run(_run_noop_empty())


async def _run_noop_empty() -> None:
    reranker = NoOpReranker()
    result = await reranker.rerank("query", [], top_n=5)
    assert result == []


# --- Fake Anthropic client for ClaudeReranker tests ---


@dataclass
class FakeTextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class FakeResponse:
    content: list[Any] = None  # type: ignore

    def __post_init__(self) -> None:
        if self.content is None:
            self.content = []


@dataclass
class FakeMessages:
    response_text: str = ""

    async def create(self, **kwargs: Any) -> FakeResponse:
        return FakeResponse(content=[FakeTextBlock(text=self.response_text)])


@dataclass
class FakeAnthropicClient:
    messages: FakeMessages = None  # type: ignore

    def __post_init__(self) -> None:
        if self.messages is None:
            self.messages = FakeMessages()


def test_claude_reranker_reorders_by_score() -> None:
    asyncio.run(_run_claude_reranker())


async def _run_claude_reranker() -> None:
    # Fake client returns scores that reverse the original order
    fake_client = FakeAnthropicClient(
        messages=FakeMessages(
            response_text='[{"index": 0, "score": 2}, {"index": 1, "score": 8}, {"index": 2, "score": 5}]'
        )
    )
    reranker = ClaudeReranker(fake_client, model="test-model")  # type: ignore
    chunks = [_chunk(0, 0.9), _chunk(1, 0.7), _chunk(2, 0.5)]
    result = await reranker.rerank("query", chunks, top_n=3)

    assert len(result) == 3
    assert result[0].document_id == "doc-1"  # score 8
    assert result[1].document_id == "doc-2"  # score 5
    assert result[2].document_id == "doc-0"  # score 2


def test_claude_reranker_respects_top_n() -> None:
    asyncio.run(_run_claude_reranker_top_n())


async def _run_claude_reranker_top_n() -> None:
    fake_client = FakeAnthropicClient(
        messages=FakeMessages(
            response_text='[{"index": 0, "score": 9}, {"index": 1, "score": 8}, {"index": 2, "score": 7}]'
        )
    )
    reranker = ClaudeReranker(fake_client, model="test-model")  # type: ignore
    chunks = [_chunk(0), _chunk(1), _chunk(2)]
    result = await reranker.rerank("query", chunks, top_n=2)
    assert len(result) == 2


def test_claude_reranker_fallback_on_error() -> None:
    asyncio.run(_run_claude_reranker_error())


async def _run_claude_reranker_error() -> None:
    @dataclass
    class ErrorMessages:
        async def create(self, **kwargs: Any) -> None:
            raise RuntimeError("API error")

    fake_client = FakeAnthropicClient(messages=ErrorMessages())  # type: ignore
    reranker = ClaudeReranker(fake_client, model="test-model")  # type: ignore
    chunks = [_chunk(0), _chunk(1)]
    result = await reranker.rerank("query", chunks, top_n=2)
    # Fallback: original order truncated
    assert len(result) == 2
    assert result[0].document_id == "doc-0"


def test_claude_reranker_single_chunk() -> None:
    asyncio.run(_run_single())


async def _run_single() -> None:
    fake_client = FakeAnthropicClient()
    reranker = ClaudeReranker(fake_client, model="test-model")  # type: ignore
    chunks = [_chunk(0)]
    result = await reranker.rerank("query", chunks, top_n=5)
    assert len(result) == 1


def test_claude_reranker_parse_scores_bad_json() -> None:
    scores = ClaudeReranker._parse_scores("not json at all", 3)
    # Fallback: descending order scores
    assert scores == [3, 2, 1]
