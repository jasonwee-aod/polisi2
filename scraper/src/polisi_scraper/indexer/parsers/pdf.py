"""PDF parser — LlamaParse when LLAMA_CLOUD_API_KEY is set, pypdf fallback otherwise."""

from __future__ import annotations

import os
import tempfile
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
        api_key = os.environ.get("LLAMA_CLOUD_API_KEY")
        if api_key:
            try:
                return self._parse_llamaparse(payload, api_key, metadata=metadata)
            except Exception:
                pass  # fall through to pypdf
        return self._parse_pypdf(payload, metadata=metadata)

    def _parse_llamaparse(
        self,
        payload: bytes,
        api_key: str,
        *,
        metadata: dict[str, object] | None = None,
    ) -> ParsedDocument:
        from llama_parse import LlamaParse  # type: ignore[import-untyped]

        parser = LlamaParse(
            api_key=api_key,
            result_type="markdown",
            split_by_page=True,
            verbose=False,
        )

        fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        try:
            os.write(fd, payload)
            os.close(fd)
            documents = parser.load_data(tmp_path)
        finally:
            os.unlink(tmp_path)

        blocks: list[ParsedBlock] = []
        for index, doc in enumerate(documents, start=1):
            text = doc.text.strip()
            if text:
                blocks.append(
                    ParsedBlock(text=text, block_type="page", page_number=index)
                )

        return ParsedDocument(
            file_type=self.file_type,
            title=(metadata or {}).get("title") if metadata else None,
            blocks=blocks,
            metadata=dict(metadata or {}),
        )

    def _parse_pypdf(
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
