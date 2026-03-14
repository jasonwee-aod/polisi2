"""Tests for section-based semantic chunking with table awareness."""

from __future__ import annotations

from polisi_scraper.indexer.chunking import (
    DocumentChunk,
    build_chunks,
    _split_table_text,
)
from polisi_scraper.indexer.parsers.base import ParsedBlock, ParsedDocument


def _doc(blocks: list[ParsedBlock], title: str = "Test") -> ParsedDocument:
    return ParsedDocument(file_type="html", blocks=blocks, title=title)


# ---------------------------------------------------------------------------
# Table-Aware Chunking (2.4)
# ---------------------------------------------------------------------------


class TestTableChunking:
    def test_table_block_emitted_as_separate_chunk(self):
        blocks = [
            ParsedBlock(text="Introduction paragraph.", section_heading="Intro"),
            ParsedBlock(
                text="| Col A | Col B |\n|---|---|\n| 1 | 2 |",
                block_type="table",
                section_heading="Intro",
            ),
            ParsedBlock(text="Conclusion paragraph.", section_heading="Intro"),
        ]
        chunks = build_chunks(_doc(blocks))

        # Should get at least 3 chunks: intro prose, table, conclusion prose
        table_chunks = [c for c in chunks if c.metadata.get("is_table")]
        assert len(table_chunks) == 1
        assert table_chunks[0].metadata["is_table"] is True
        assert "Table from section: Intro" in table_chunks[0].text
        assert "Col A" in table_chunks[0].text

    def test_table_without_section_heading_no_prefix(self):
        blocks = [
            ParsedBlock(
                text="| X | Y |\n|---|---|\n| a | b |",
                block_type="table",
                section_heading=None,
            ),
        ]
        chunks = build_chunks(_doc(blocks))
        table_chunks = [c for c in chunks if c.metadata.get("is_table")]
        assert len(table_chunks) == 1
        # No "Table from section:" prefix when heading is None
        assert not table_chunks[0].text.startswith("Table from section:")

    def test_large_table_split_preserves_headers(self):
        header = "| Name | Value | Description |"
        separator = "|------|-------|-------------|"
        rows = [f"| item{i} | {i * 100} | description of item {i} |" for i in range(50)]
        table_text = "\n".join([header, separator] + rows)

        parts = _split_table_text(table_text, max_chars=500)
        assert len(parts) > 1
        for part in parts:
            # Every part must start with the header row
            assert part.startswith(header)
            assert separator in part

    def test_table_flushes_accumulated_prose(self):
        """When a table appears mid-section, accumulated prose is flushed first."""
        blocks = [
            ParsedBlock(text="First paragraph.", section_heading="Section A"),
            ParsedBlock(text="Second paragraph.", section_heading="Section A"),
            ParsedBlock(
                text="| A | B |\n|---|---|\n| 1 | 2 |",
                block_type="table",
                section_heading="Section A",
            ),
        ]
        chunks = build_chunks(_doc(blocks))
        # The first chunk should be prose, the second should be the table
        assert chunks[0].metadata.get("is_table") is not True
        assert "First paragraph" in chunks[0].text
        assert chunks[1].metadata.get("is_table") is True


# ---------------------------------------------------------------------------
# Section-Based Semantic Chunking (2.1)
# ---------------------------------------------------------------------------


class TestSectionBasedChunking:
    def test_blocks_with_same_heading_grouped(self):
        blocks = [
            ParsedBlock(text="Block A1", section_heading="Section A"),
            ParsedBlock(text="Block A2", section_heading="Section A"),
            ParsedBlock(text="Block B1", section_heading="Section B"),
        ]
        chunks = build_chunks(_doc(blocks), target_chars=5000)
        # With a large target, Section A blocks should be in one chunk
        assert len(chunks) == 2
        assert "Block A1" in chunks[0].text
        assert "Block A2" in chunks[0].text
        assert "Block B1" in chunks[1].text

    def test_section_exceeding_target_splits_at_block_boundaries(self):
        blocks = [
            ParsedBlock(text="A" * 800, section_heading="Big Section"),
            ParsedBlock(text="B" * 800, section_heading="Big Section"),
        ]
        chunks = build_chunks(_doc(blocks), target_chars=1000)
        # Each block is 800 chars; together they exceed 1000, so they split
        assert len(chunks) == 2
        assert "A" * 800 == chunks[0].text
        assert "B" * 800 == chunks[1].text

    def test_blocks_without_heading_use_target_grouping(self):
        blocks = [
            ParsedBlock(text="Short A."),
            ParsedBlock(text="Short B."),
            ParsedBlock(text="Short C."),
        ]
        # All None heading = same group, all fit within target
        chunks = build_chunks(_doc(blocks), target_chars=5000)
        assert len(chunks) == 1
        assert "Short A." in chunks[0].text
        assert "Short B." in chunks[0].text
        assert "Short C." in chunks[0].text

    def test_no_overlap_carryover(self):
        """Verify there is no overlap text between chunks."""
        blocks = [
            ParsedBlock(text="X" * 800, section_heading="S1"),
            ParsedBlock(text="Y" * 800, section_heading="S2"),
        ]
        chunks = build_chunks(_doc(blocks), target_chars=1000)
        # Second chunk should NOT start with any text from the first
        assert chunks[1].text.startswith("Y")


# ---------------------------------------------------------------------------
# Parent Document Retrieval (2.2)
# ---------------------------------------------------------------------------


class TestParentText:
    def test_parent_text_from_section(self):
        blocks = [
            ParsedBlock(text="Para 1", section_heading="Introduction"),
            ParsedBlock(text="Para 2", section_heading="Introduction"),
        ]
        chunks = build_chunks(_doc(blocks), target_chars=5000)
        assert len(chunks) == 1
        assert chunks[0].parent_text is not None
        assert "Para 1" in chunks[0].parent_text
        assert "Para 2" in chunks[0].parent_text

    def test_parent_text_capped_at_3000(self):
        blocks = [
            ParsedBlock(text="W" * 2000, section_heading="Long Section"),
            ParsedBlock(text="X" * 2000, section_heading="Long Section"),
        ]
        chunks = build_chunks(_doc(blocks), target_chars=1500)
        for chunk in chunks:
            assert chunk.parent_text is not None
            assert len(chunk.parent_text) <= 3000

    def test_parent_text_backfill_for_no_heading(self):
        blocks = [
            ParsedBlock(text="Orphan block."),
        ]
        chunks = build_chunks(_doc(blocks))
        assert len(chunks) == 1
        # parent_text should be backfilled from surrounding context
        assert chunks[0].parent_text is not None
        assert "Orphan block." in chunks[0].parent_text


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_document(self):
        chunks = build_chunks(_doc([]))
        assert chunks == []

    def test_whitespace_only_blocks_skipped(self):
        blocks = [ParsedBlock(text="   "), ParsedBlock(text="\n")]
        chunks = build_chunks(_doc(blocks))
        assert chunks == []

    def test_chunk_index_sequential(self):
        blocks = [
            ParsedBlock(text="A" * 500, section_heading="S1"),
            ParsedBlock(text="B" * 500, section_heading="S2"),
            ParsedBlock(text="C" * 500, section_heading="S3"),
        ]
        chunks = build_chunks(_doc(blocks))
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i
