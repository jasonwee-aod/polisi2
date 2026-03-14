"""Tests for prompt building and lost-in-the-middle reordering."""

from polisi_api.chat.prompting import _format_context_block, reorder_for_attention
from polisi_api.chat.retrieval import RetrievedChunk


def _chunk(index: int, similarity: float = 0.8) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=f"doc-{index}",
        title=f"Title {index}",
        agency="AGY",
        source_url=None,
        chunk_text=f"Content of chunk {index}",
        similarity=similarity,
        chunk_index=index,
    )


def test_reorder_1_chunk() -> None:
    chunks = [_chunk(1)]
    result = reorder_for_attention(chunks)
    assert len(result) == 1
    assert result[0] == (1, chunks[0])


def test_reorder_2_chunks() -> None:
    chunks = [_chunk(1, 0.9), _chunk(2, 0.7)]
    result = reorder_for_attention(chunks)
    assert len(result) == 2
    assert result[0][0] == 1  # rank-1 first
    assert result[1][0] == 2  # rank-2 last


def test_reorder_3_chunks() -> None:
    chunks = [_chunk(1, 0.9), _chunk(2, 0.8), _chunk(3, 0.7)]
    result = reorder_for_attention(chunks)
    # Expected: [1, 3, 2] — best first, worst in middle, second-best last
    assert [idx for idx, _ in result] == [1, 3, 2]


def test_reorder_4_chunks() -> None:
    chunks = [_chunk(i, 0.9 - i * 0.1) for i in range(1, 5)]
    result = reorder_for_attention(chunks)
    # Expected: [1, 4, 3, 2]
    assert [idx for idx, _ in result] == [1, 4, 3, 2]


def test_reorder_5_chunks() -> None:
    chunks = [_chunk(i, 0.9 - i * 0.05) for i in range(1, 6)]
    result = reorder_for_attention(chunks)
    # Expected: [1, 5, 4, 3, 2]
    assert [idx for idx, _ in result] == [1, 5, 4, 3, 2]


def test_citation_indices_stable_in_format() -> None:
    """Citation [n] markers match the original position, not the reordered position."""
    chunks = [_chunk(1, 0.9), _chunk(2, 0.8), _chunk(3, 0.7)]
    reordered = reorder_for_attention(chunks)
    formatted = _format_context_block(chunks, reordered=reordered)

    # The format should contain [1], [3], [2] in that order (reordered)
    lines = formatted.split("\n\n")
    assert lines[0].startswith("[1]")  # rank-1 first
    assert lines[1].startswith("[3]")  # rank-3 (worst) in middle
    assert lines[2].startswith("[2]")  # rank-2 last


def test_format_context_block_empty_reordered() -> None:
    result = _format_context_block([], reordered=[])
    assert result == ""


def test_format_context_block_backwards_compat() -> None:
    """When reordered is None, falls back to sequential numbering."""
    chunks = [_chunk(1), _chunk(2)]
    result = _format_context_block(chunks)
    assert "[1]" in result
    assert "[2]" in result
