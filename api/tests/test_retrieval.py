"""Tests for retrieval dataclasses and scoring logic."""

from polisi_api.chat.retrieval import RetrievedChunk


def _chunk(similarity: float, fts_rank: float = 0.0) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=None,
        title="Test",
        agency="TEST",
        source_url=None,
        chunk_text="text",
        similarity=similarity,
        fts_rank=fts_rank,
    )


def test_effective_similarity_uses_cosine_when_present() -> None:
    c = _chunk(similarity=0.78, fts_rank=0.1)
    assert c.effective_similarity == 0.78


def test_effective_similarity_floor_for_fts_only() -> None:
    c = _chunk(similarity=0.0, fts_rank=0.05)
    assert c.effective_similarity == 0.50  # FTS floor default


def test_effective_similarity_zero_when_no_match() -> None:
    c = _chunk(similarity=0.0, fts_rank=0.0)
    assert c.effective_similarity == 0.0
