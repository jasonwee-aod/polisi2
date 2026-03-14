"""CSV parser — reads rows with header-value pairs, falls back to raw rows."""

from __future__ import annotations

import csv
import io
import logging
import os
import tempfile
import threading

from polisi_scraper.indexer.parsers.base import DocumentParser, ParsedBlock, ParsedDocument

log = logging.getLogger(__name__)

# Reuse the LlamaParse budget from the PDF parser module.
from polisi_scraper.indexer.parsers.pdf import (
    _get_llamaparse_budget,
    _llamaparse_lock,
    _llamaparse_pages_used,
)


class CsvParser(DocumentParser):
    file_type = "csv"

    def parse_bytes(
        self,
        payload: bytes,
        *,
        metadata: dict[str, object] | None = None,
    ) -> ParsedDocument:
        api_key = os.environ.get("LLAMA_CLOUD_API_KEY")
        budget = _get_llamaparse_budget()

        if api_key:
            with _llamaparse_lock:
                global _llamaparse_pages_used
                if budget and _llamaparse_pages_used >= budget:
                    return self._parse_stdlib(payload, metadata=metadata)
            try:
                result = self._parse_llamaparse(payload, api_key, metadata=metadata)
                with _llamaparse_lock:
                    _llamaparse_pages_used += max(len(result.blocks), 1)
                    if budget:
                        log.info("[csv] LlamaParse pages used: %d/%d", _llamaparse_pages_used, budget)
                return result
            except Exception as exc:
                log.warning("[csv] LlamaParse failed, falling back to stdlib: %s", exc)

        return self._parse_stdlib(payload, metadata=metadata)

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
            spreadsheet_extract_sub_tables=True,
            output_tables_as_HTML=False,
        )

        fd, tmp_path = tempfile.mkstemp(suffix=".csv")
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
                blocks.append(ParsedBlock(text=text, block_type="table", page_number=index))

        return ParsedDocument(
            file_type=self.file_type,
            title=(metadata or {}).get("title") if metadata else None,
            blocks=blocks,
            metadata=dict(metadata or {}),
        )

    def _parse_stdlib(
        self,
        payload: bytes,
        *,
        metadata: dict[str, object] | None = None,
    ) -> ParsedDocument:
        """Parse CSV using Python stdlib — header-value pairs per row."""
        # Try common encodings
        text = None
        for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                text = payload.decode(enc)
                break
            except (UnicodeDecodeError, ValueError):
                continue
        if text is None:
            text = payload.decode("utf-8", errors="replace")

        # Detect dialect
        try:
            dialect = csv.Sniffer().sniff(text[:4096])
        except csv.Error:
            dialect = csv.excel

        reader = csv.reader(io.StringIO(text), dialect)
        rows = list(reader)
        if not rows:
            return ParsedDocument(file_type=self.file_type, blocks=[], metadata=dict(metadata or {}))

        headers = rows[0]
        blocks: list[ParsedBlock] = []

        for row_number, row in enumerate(rows[1:], start=2):
            if not any(cell.strip() for cell in row):
                continue
            pairs = []
            for header, value in zip(headers, row):
                value = value.strip()
                if value:
                    label = header.strip() or f"Column {len(pairs) + 1}"
                    pairs.append(f"{label}: {value}")
            text = " | ".join(pairs) if pairs else " | ".join(row)
            row_label = row[0].strip() if row else f"Row {row_number}"
            blocks.append(
                ParsedBlock(
                    text=text,
                    block_type="row",
                    row_number=row_number,
                    row_label=row_label,
                )
            )

        return ParsedDocument(
            file_type=self.file_type,
            title=(metadata or {}).get("title") if metadata else None,
            blocks=blocks,
            metadata=dict(metadata or {}),
        )
