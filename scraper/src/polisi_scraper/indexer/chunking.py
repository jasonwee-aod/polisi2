"""Chunk assembly for parsed documents — section-based semantic chunking."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import groupby

from polisi_scraper.indexer.parsers.base import ParsedBlock, ParsedDocument


@dataclass(frozen=True)
class DocumentChunk:
    """Retrieval-ready chunk with locator metadata."""

    chunk_index: int
    text: str
    metadata: dict[str, object] = field(default_factory=dict)
    parent_text: str | None = None


def build_chunks(
    document: ParsedDocument,
    *,
    target_chars: int = 1400,
) -> list[DocumentChunk]:
    """Build retrieval chunks using section-based semantic grouping.

    Blocks sharing the same ``section_heading`` are kept together up to
    *target_chars*.  Table blocks are always emitted as separate chunks
    (with header-preserving splits for very large tables).

    ``parent_text`` on each chunk contains the full section content (up to
    3000 chars) for Parent Document Retrieval.
    """
    chunks: list[DocumentChunk] = []

    # ---- group consecutive blocks by section_heading --------------------
    section_groups = _group_blocks_by_section(document.blocks)

    for heading, blocks in section_groups:
        # Build full section text for parent document retrieval
        section_text = "\n\n".join(b.text.strip() for b in blocks if b.text.strip())
        parent_text = section_text[:3000] if section_text else None

        # Separate table blocks from prose blocks
        accumulated_blocks: list[ParsedBlock] = []
        accumulated_texts: list[str] = []

        for block in blocks:
            text = block.text.strip()
            if not text:
                continue

            if block.block_type == "table":
                # Flush any accumulated prose first
                if accumulated_texts:
                    _flush_prose(
                        chunks, accumulated_blocks, accumulated_texts,
                        document, parent_text, target_chars,
                    )
                    accumulated_blocks = []
                    accumulated_texts = []

                # Emit table chunk(s)
                _emit_table_chunks(
                    chunks, block, text, heading, document, parent_text,
                )
            else:
                # Hard-split blocks that are individually larger than target_chars
                sub_texts = _split_text(text, target_chars)
                for sub_text in sub_texts:
                    projected = "\n\n".join(accumulated_texts + [sub_text])
                    if accumulated_texts and len(projected) > target_chars:
                        _flush_prose(
                            chunks, accumulated_blocks, accumulated_texts,
                            document, parent_text, target_chars,
                        )
                        accumulated_blocks = []
                        accumulated_texts = []
                    accumulated_blocks.append(block)
                    accumulated_texts.append(sub_text)

        # Flush remaining prose in section
        if accumulated_texts:
            _flush_prose(
                chunks, accumulated_blocks, accumulated_texts,
                document, parent_text, target_chars,
            )

    # ---- handle parent_text for chunks without a section heading --------
    # For chunks whose blocks had no section_heading, use surrounding context
    _backfill_parent_text(chunks)

    return chunks


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _group_blocks_by_section(
    blocks: list[ParsedBlock],
) -> list[tuple[str | None, list[ParsedBlock]]]:
    """Group consecutive blocks sharing the same section_heading."""
    groups: list[tuple[str | None, list[ParsedBlock]]] = []
    for heading, group_iter in groupby(blocks, key=lambda b: b.section_heading):
        groups.append((heading, list(group_iter)))
    return groups


def _flush_prose(
    chunks: list[DocumentChunk],
    blocks: list[ParsedBlock],
    texts: list[str],
    document: ParsedDocument,
    parent_text: str | None,
    target_chars: int,
) -> None:
    """Emit one prose chunk from accumulated blocks/texts."""
    chunks.append(
        _emit_chunk(chunks, blocks, texts, document, parent_text)
    )


def _emit_table_chunks(
    chunks: list[DocumentChunk],
    block: ParsedBlock,
    text: str,
    heading: str | None,
    document: ParsedDocument,
    parent_text: str | None,
    max_table_chars: int = 3000,
) -> None:
    """Emit one or more table chunks, splitting large tables by rows."""
    prefix = f"Table from section: {heading}\n\n" if heading else ""

    if len(prefix + text) <= max_table_chars:
        table_texts = [prefix + text]
    else:
        parts = _split_table_text(text, max_table_chars - len(prefix))
        table_texts = [prefix + part for part in parts]

    for table_text in table_texts:
        metadata = dict(document.metadata)
        metadata["file_type"] = document.file_type
        if document.title:
            metadata["title"] = document.title
        metadata["is_table"] = True
        metadata["locators"] = [block.chunk_metadata()]
        metadata["block_count"] = 1
        chunks.append(
            DocumentChunk(
                chunk_index=len(chunks),
                text=table_text,
                metadata=metadata,
                parent_text=parent_text,
            )
        )


def _split_table_text(text: str, max_chars: int) -> list[str]:
    """Split a markdown table by rows, preserving the header in each part.

    Detects the header row (first line) and optional separator row (second
    line starting with ``|--`` or ``---``).  Remaining rows are grouped into
    sub-tables that fit within *max_chars* (including the header).
    """
    lines = text.split("\n")
    if not lines:
        return [text]

    # Identify header lines (header row + optional separator)
    header_lines: list[str] = [lines[0]]
    data_start = 1
    if len(lines) > 1 and _is_separator_row(lines[1]):
        header_lines.append(lines[1])
        data_start = 2

    header = "\n".join(header_lines)
    data_rows = lines[data_start:]

    if not data_rows:
        return [text]

    parts: list[str] = []
    current_rows: list[str] = []
    current_len = len(header)

    for row in data_rows:
        row_len = len(row) + 1  # +1 for newline
        if current_rows and current_len + row_len > max_chars:
            parts.append(header + "\n" + "\n".join(current_rows))
            current_rows = []
            current_len = len(header)
        current_rows.append(row)
        current_len += row_len

    if current_rows:
        parts.append(header + "\n" + "\n".join(current_rows))

    return parts if parts else [text]


def _is_separator_row(line: str) -> bool:
    """Check if a line is a markdown table separator (e.g. |---|---|)."""
    stripped = line.strip()
    return stripped.startswith("|--") or stripped.startswith("---")


def _split_text(text: str, target_chars: int) -> list[str]:
    """Return text as a list of at most target_chars-sized pieces."""
    if len(text) <= target_chars:
        return [text]
    return [text[i : i + target_chars] for i in range(0, len(text), target_chars)]


def _emit_chunk(
    existing: list[DocumentChunk],
    blocks: list[ParsedBlock],
    texts: list[str],
    document: ParsedDocument,
    parent_text: str | None,
) -> DocumentChunk:
    text = "\n\n".join(texts)
    metadata = dict(document.metadata)
    metadata["file_type"] = document.file_type
    if document.title:
        metadata["title"] = document.title
    metadata["locators"] = [block.chunk_metadata() for block in blocks]
    metadata["block_count"] = len(blocks)
    return DocumentChunk(
        chunk_index=len(existing),
        text=text,
        metadata=metadata,
        parent_text=parent_text,
    )


def _backfill_parent_text(chunks: list[DocumentChunk]) -> None:
    """For chunks without parent_text, use surrounding +-2 chunks as context."""
    for i, chunk in enumerate(chunks):
        if chunk.parent_text is not None:
            continue
        # Gather text from surrounding +-2 chunks
        neighbours: list[str] = []
        for j in range(max(0, i - 2), min(len(chunks), i + 3)):
            neighbours.append(chunks[j].text)
        context = "\n\n".join(neighbours)[:3000]
        # Replace the chunk with an updated copy (frozen dataclass)
        chunks[i] = DocumentChunk(
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            metadata=chunk.metadata,
            parent_text=context,
        )
