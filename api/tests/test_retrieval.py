"""Tests for retrieval dataclasses and scoring logic."""

from polisi_api.chat.retrieval import (
    RetrievedChunk,
    apply_adaptive_cutoff,
    apply_metadata_boost,
    deduplicate_chunks,
)


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


# --- deduplicate_chunks ---


def _make_chunk(
    doc_id: str | None = "doc-1",
    chunk_index: int | None = 0,
    similarity: float = 0.8,
    text: str = "some chunk text",
    fts_rank: float = 0.0,
    rrf_score: float = 0.0,
) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=doc_id,
        title="Title",
        agency="AGY",
        source_url=None,
        chunk_text=text,
        similarity=similarity,
        chunk_index=chunk_index,
        fts_rank=fts_rank,
        rrf_score=rrf_score,
    )


def test_dedup_removes_adjacent_same_doc_chunks() -> None:
    c1 = _make_chunk(doc_id="d1", chunk_index=3, similarity=0.9)
    c2 = _make_chunk(doc_id="d1", chunk_index=4, similarity=0.7)
    result = deduplicate_chunks([c1, c2])
    assert len(result) == 1
    assert result[0].similarity == 0.9  # higher score kept


def test_dedup_keeps_nonadjacent_same_doc() -> None:
    c1 = _make_chunk(doc_id="d1", chunk_index=1, similarity=0.9, text="policy alpha beta gamma delta")
    c2 = _make_chunk(doc_id="d1", chunk_index=5, similarity=0.7, text="budget epsilon zeta theta iota")
    result = deduplicate_chunks([c1, c2])
    assert len(result) == 2


def test_dedup_removes_high_jaccard_overlap() -> None:
    shared = "the quick brown fox jumps over the lazy dog"
    c1 = _make_chunk(doc_id="d1", chunk_index=1, similarity=0.9, text=shared)
    c2 = _make_chunk(doc_id="d2", chunk_index=1, similarity=0.7, text=shared + " extra")
    result = deduplicate_chunks([c1, c2])
    assert len(result) == 1
    assert result[0].similarity == 0.9


def test_dedup_keeps_different_text() -> None:
    c1 = _make_chunk(doc_id="d1", chunk_index=1, similarity=0.9, text="alpha beta gamma")
    c2 = _make_chunk(doc_id="d2", chunk_index=1, similarity=0.7, text="delta epsilon zeta")
    result = deduplicate_chunks([c1, c2])
    assert len(result) == 2


def test_dedup_empty_list() -> None:
    assert deduplicate_chunks([]) == []


def test_dedup_single_chunk() -> None:
    c = _make_chunk()
    result = deduplicate_chunks([c])
    assert len(result) == 1


# --- apply_metadata_boost ---


def test_metadata_boost_recent_doc() -> None:
    c_recent = _make_chunk(
        doc_id="d1", similarity=0.7, rrf_score=0.05,
    )
    # Manually replace with metadata — since frozen, rebuild
    c_recent = RetrievedChunk(
        document_id="d1", title="Title", agency="AGY", source_url=None,
        chunk_text="text", similarity=0.7, chunk_index=0,
        metadata={"published_at": "2025-01-01"},
        rrf_score=0.05,
    )
    c_old = RetrievedChunk(
        document_id="d2", title="Title", agency="AGY", source_url=None,
        chunk_text="other text", similarity=0.8, chunk_index=0,
        metadata={"published_at": "2015-01-01"},
        rrf_score=0.04,
    )
    result = apply_metadata_boost([c_old, c_recent])
    # c_recent has recency boost, c_old does not (>5 years ago)
    # c_recent boosted: 0.05 * (1.0 + 0.1 * max(0, 5 - ~1.2)) = 0.05 * ~1.38 = ~0.069
    # c_old boosted: 0.04 * 1.0 = 0.04
    assert result[0].document_id == "d1"  # boosted recent doc should be first


def test_metadata_boost_missing_date_no_crash() -> None:
    c = _make_chunk(doc_id="d1", similarity=0.8, rrf_score=0.05)
    result = apply_metadata_boost([c])
    assert len(result) == 1


def test_metadata_boost_empty() -> None:
    assert apply_metadata_boost([]) == []


# --- apply_adaptive_cutoff ---


def test_adaptive_cutoff_drops_low_chunks() -> None:
    c1 = _make_chunk(similarity=0.9)
    c2 = _make_chunk(similarity=0.8)
    c3 = _make_chunk(similarity=0.3)
    result = apply_adaptive_cutoff([c1, c2, c3], dropoff_ratio=0.6, max_chunks=5)
    # threshold = 0.9 * 0.6 = 0.54
    # c1 (0.9) and c2 (0.8) pass, c3 (0.3) doesn't
    assert len(result) == 2


def test_adaptive_cutoff_keeps_at_least_one() -> None:
    c1 = _make_chunk(similarity=0.1)
    result = apply_adaptive_cutoff([c1], dropoff_ratio=0.6, max_chunks=5)
    assert len(result) == 1


def test_adaptive_cutoff_respects_max_chunks() -> None:
    chunks = [_make_chunk(similarity=0.9 - i * 0.01) for i in range(10)]
    result = apply_adaptive_cutoff(chunks, dropoff_ratio=0.5, max_chunks=3)
    assert len(result) <= 3


def test_adaptive_cutoff_empty() -> None:
    assert apply_adaptive_cutoff([], dropoff_ratio=0.6, max_chunks=5) == []
