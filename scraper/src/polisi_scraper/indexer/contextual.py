"""Contextual retrieval — LLM-generated chunk context prefixes.

Uses Anthropic Claude Haiku to generate a short context sentence for each
chunk, situating it within the overall document.  This is an **opt-in**
feature controlled by the ``CONTEXTUAL_RETRIEVAL_ENABLED`` env var.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

_SYSTEM_PROMPT = (
    "You will be given a document and a chunk from that document. "
    "Please give a short succinct context (1-2 sentences) to situate "
    "this chunk within the overall document for the purposes of improving "
    "search retrieval of the chunk. Return only the context, nothing else."
)

# Maximum chars of document text sent to the LLM
_MAX_DOC_CHARS = 6000


class AnthropicMessagesClient(Protocol):
    """Minimal interface matching ``anthropic.Anthropic().messages``."""

    def create(self, *, model: str, max_tokens: int, system: str, messages: list[dict[str, Any]]) -> Any: ...


def _get_config() -> tuple[bool, str]:
    """Read contextual-retrieval config from environment."""
    enabled = os.environ.get("CONTEXTUAL_RETRIEVAL_ENABLED", "false").lower() == "true"
    model = os.environ.get("CONTEXTUAL_RETRIEVAL_MODEL", "claude-3-5-haiku-latest")
    return enabled, model


def generate_chunk_context(
    full_document_text: str,
    chunk_text: str,
    *,
    client: AnthropicMessagesClient,
    model: str,
) -> str:
    """Return a 1-2 sentence context prefix for *chunk_text*.

    On any API error the function returns an empty string so the indexing
    pipeline can continue unaffected.
    """
    truncated_doc = full_document_text[:_MAX_DOC_CHARS]
    user_message = (
        f"<document>\n{truncated_doc}\n</document>\n\n"
        f"<chunk>\n{chunk_text}\n</chunk>"
    )
    try:
        response = client.create(
            model=model,
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        # Anthropic SDK returns response.content as a list of ContentBlock
        if hasattr(response, "content") and response.content:
            block = response.content[0]
            return getattr(block, "text", "").strip()
        return ""
    except Exception:
        return ""


def generate_chunk_contexts_batch(
    full_document_text: str,
    chunk_texts: list[str],
    *,
    client: AnthropicMessagesClient,
    model: str,
) -> list[str]:
    """Generate context prefixes for a list of chunks sequentially.

    This is designed for the synchronous indexer pipeline which processes
    one document at a time.
    """
    contexts: list[str] = []
    for chunk_text in chunk_texts:
        ctx = generate_chunk_context(
            full_document_text,
            chunk_text,
            client=client,
            model=model,
        )
        contexts.append(ctx)
    return contexts
