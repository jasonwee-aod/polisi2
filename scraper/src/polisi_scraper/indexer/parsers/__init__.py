"""Parser registry for all supported indexer document types."""

from __future__ import annotations

from polisi_scraper.indexer.parsers.base import DocumentParser, ParsedBlock, ParsedDocument
from polisi_scraper.indexer.parsers.csv_parser import CsvParser
from polisi_scraper.indexer.parsers.docx import DocxParser
from polisi_scraper.indexer.parsers.html import HtmlParser
from polisi_scraper.indexer.parsers.pdf import PdfParser
from polisi_scraper.indexer.parsers.xlsx import XlsxParser


_PARSERS: dict[str, DocumentParser] = {
    "html": HtmlParser(),
    "pdf": PdfParser(),
    "docx": DocxParser(),
    "xlsx": XlsxParser(),
    "xls": XlsxParser(),
    "csv": CsvParser(),
}


def get_parser(file_type: str) -> DocumentParser:
    try:
        return _PARSERS[file_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported parser file type: {file_type}") from exc


__all__ = [
    "CsvParser",
    "DocxParser",
    "DocumentParser",
    "HtmlParser",
    "ParsedBlock",
    "ParsedDocument",
    "PdfParser",
    "XlsxParser",
    "get_parser",
]
