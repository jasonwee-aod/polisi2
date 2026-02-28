"""PDF parser with page-aware salvage behavior."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from polisi_scraper.indexer.parsers.base import DocumentParser, ParsedBlock, ParsedDocument


class PdfParser(DocumentParser):
    file_type = "pdf"

    def parse_bytes(
        self,
        payload: bytes,
        *,
        metadata: dict[str, object] | None = None,
    ) -> ParsedDocument:
        reader = PdfReader(BytesIO(payload))
        blocks: list[ParsedBlock] = []

        for index, page in enumerate(reader.pages, start=1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception:
                continue
            if not text:
                continue
            blocks.append(
                ParsedBlock(
                    text=text,
                    block_type="page",
                    page_number=index,
                )
            )

        return ParsedDocument(
            file_type=self.file_type,
            title=(metadata or {}).get("title") if metadata else None,
            blocks=blocks,
            metadata=dict(metadata or {}),
        )
