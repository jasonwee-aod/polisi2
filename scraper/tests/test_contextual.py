"""Tests for contextual retrieval — LLM-generated chunk context prefixes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from polisi_scraper.indexer.contextual import (
    generate_chunk_context,
    generate_chunk_contexts_batch,
    _MAX_DOC_CHARS,
)


# ---------------------------------------------------------------------------
# Mock Anthropic client
# ---------------------------------------------------------------------------


@dataclass
class FakeContentBlock:
    text: str


@dataclass
class FakeResponse:
    content: list[FakeContentBlock]


class FakeAnthropicMessages:
    """Minimal mock matching the AnthropicMessagesClient protocol."""

    def __init__(self, response_text: str = "This chunk discusses budget allocations.") -> None:
        self.response_text = response_text
        self.calls: list[dict[str, Any]] = []

    def create(self, *, model: str, max_tokens: int, system: str, messages: list[dict[str, Any]]) -> FakeResponse:
        self.calls.append({"model": model, "max_tokens": max_tokens, "system": system, "messages": messages})
        return FakeResponse(content=[FakeContentBlock(text=self.response_text)])


class ErrorAnthropicMessages:
    """Mock that raises an exception on every call."""

    def create(self, **kwargs: Any) -> Any:
        raise RuntimeError("API error")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGenerateChunkContext:
    def test_returns_context_string(self):
        client = FakeAnthropicMessages("This chunk covers fuel subsidies.")
        result = generate_chunk_context(
            "Full document text here.",
            "Fuel subsidy continues for 2026.",
            client=client,
            model="claude-3-5-haiku-latest",
        )
        assert result == "This chunk covers fuel subsidies."
        assert len(client.calls) == 1
        assert client.calls[0]["model"] == "claude-3-5-haiku-latest"

    def test_truncates_long_documents(self):
        long_doc = "X" * 10000
        client = FakeAnthropicMessages("Context.")
        generate_chunk_context(
            long_doc,
            "Chunk text.",
            client=client,
            model="claude-3-5-haiku-latest",
        )
        # Verify the document text in the message was truncated
        user_msg = client.calls[0]["messages"][0]["content"]
        # The document portion should be at most _MAX_DOC_CHARS
        assert f"{'X' * _MAX_DOC_CHARS}" in user_msg
        assert f"{'X' * (_MAX_DOC_CHARS + 1)}" not in user_msg

    def test_graceful_error_handling(self):
        client = ErrorAnthropicMessages()
        result = generate_chunk_context(
            "Document.",
            "Chunk.",
            client=client,
            model="claude-3-5-haiku-latest",
        )
        assert result == ""

    def test_empty_response_content(self):
        """Handle response with empty content list."""

        class EmptyResponseClient:
            def create(self, **kwargs: Any) -> Any:
                return FakeResponse(content=[])

        result = generate_chunk_context(
            "Document.", "Chunk.",
            client=EmptyResponseClient(),
            model="claude-3-5-haiku-latest",
        )
        assert result == ""


class TestGenerateChunkContextsBatch:
    def test_processes_all_chunks(self):
        client = FakeAnthropicMessages("Context for chunk.")
        results = generate_chunk_contexts_batch(
            "Full document.",
            ["Chunk 1", "Chunk 2", "Chunk 3"],
            client=client,
            model="claude-3-5-haiku-latest",
        )
        assert len(results) == 3
        assert all(r == "Context for chunk." for r in results)
        assert len(client.calls) == 3

    def test_empty_chunk_list(self):
        client = FakeAnthropicMessages()
        results = generate_chunk_contexts_batch(
            "Document.",
            [],
            client=client,
            model="claude-3-5-haiku-latest",
        )
        assert results == []
        assert len(client.calls) == 0


class TestConfig:
    def test_default_config(self):
        with patch.dict("os.environ", {}, clear=True):
            from polisi_scraper.indexer.contextual import _get_config

            enabled, model = _get_config()
            assert enabled is False
            assert model == "claude-3-5-haiku-latest"

    def test_enabled_config(self):
        with patch.dict(
            "os.environ",
            {"CONTEXTUAL_RETRIEVAL_ENABLED": "true", "CONTEXTUAL_RETRIEVAL_MODEL": "claude-3-haiku-20240307"},
        ):
            from polisi_scraper.indexer.contextual import _get_config

            enabled, model = _get_config()
            assert enabled is True
            assert model == "claude-3-haiku-20240307"
