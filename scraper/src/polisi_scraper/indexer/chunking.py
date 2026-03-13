"""Chunk assembly for parsed documents."""

from __future__ import annotations

from dataclasses import dataclass, field

from polisi_scraper.indexer.parsers.base import ParsedBlock, ParsedDocument


@dataclass(frozen=True)
class DocumentChunk:
    """Retrieval-ready chunk with locator metadata."""

    chunk_index: int
    text: str
    metadata: dict[str, object] = field(default_factory=dict)


def build_chunks(
    document: ParsedDocument,
    *,
    target_chars: int = 1400,
    overlap_chars: int = 250,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    current_blocks: list[ParsedBlock] = []
    current_texts: list[str] = []
    carryover = ""

    for block in document.blocks:
        text = block.text.strip()
        if not text:
            continue

        # Hard-split blocks that are individually larger than target_chars so
        # no single chunk ever exceeds the embedding model's token limit.
        sub_texts = _split_text(text, target_chars)

        for sub_text in sub_texts:
            projected = "\n\n".join(current_texts + [sub_text])
            if current_texts and len(projected) > target_chars:
                chunks.append(_emit_chunk(chunks, current_blocks, current_texts, carryover, document))
                carryover = chunks[-1].text[-overlap_chars:] if overlap_chars > 0 else ""
                current_blocks = []
                current_texts = []

            current_blocks.append(block)
            current_texts.append(sub_text)

    if current_texts:
        chunks.append(_emit_chunk(chunks, current_blocks, current_texts, carryover, document))

    return chunks


def _split_text(text: str, target_chars: int) -> list[str]:
    """Return text as a list of at most target_chars-sized pieces."""
    if len(text) <= target_chars:
        return [text]
    return [text[i : i + target_chars] for i in range(0, len(text), target_chars)]


def _emit_chunk(
    existing: list[DocumentChunk],
    blocks: list[ParsedBlock],
    texts: list[str],
    carryover: str,
    document: ParsedDocument,
) -> DocumentChunk:
    text = "\n\n".join(texts)
    if carryover:
        text = f"{carryover}\n\n{text}"
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
    )
