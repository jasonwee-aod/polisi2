"""Shared parser contracts for indexable documents."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedBlock:
    """One extracted text block with locator metadata."""

    text: str
    block_type: str = "paragraph"
    page_number: int | None = None
    section_heading: str | None = None
    sheet_name: str | None = None
    row_number: int | None = None
    row_label: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def chunk_metadata(self) -> dict[str, object]:
        metadata = dict(self.metadata)
        metadata["block_type"] = self.block_type
        if self.page_number is not None:
            metadata["page_number"] = self.page_number
        if self.section_heading:
            metadata["section_heading"] = self.section_heading
        if self.sheet_name:
            metadata["sheet_name"] = self.sheet_name
        if self.row_number is not None:
            metadata["row_number"] = self.row_number
        if self.row_label:
            metadata["row_label"] = self.row_label
        return metadata


@dataclass(frozen=True)
class ParsedDocument:
    """Normalized parser output for all supported file types."""

    file_type: str
    blocks: list[ParsedBlock]
    title: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(block.text for block in self.blocks if block.text.strip())

    def is_empty(self) -> bool:
        return not any(block.text.strip() for block in self.blocks)


class DocumentParser:
    """Base class for file-type parsers."""

    file_type: str

    def parse_bytes(
        self,
        payload: bytes,
        *,
        metadata: dict[str, object] | None = None,
    ) -> ParsedDocument:
        raise NotImplementedError
