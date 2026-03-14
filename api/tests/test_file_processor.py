"""Tests for file attachment processing."""

from __future__ import annotations

import base64

import pytest

from polisi_api.chat.file_processor import (
    TOKENS_PER_ATTACHMENT,
    ProcessedAttachment,
    _rows_to_markdown,
    process_attachments,
)
from polisi_api.models import FileAttachment, MAX_ATTACHMENT_BASE64_SIZE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_attachment(
    filename: str,
    content_type: str,
    content: bytes | str,
) -> FileAttachment:
    """Build a FileAttachment from raw content (bytes or str)."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return FileAttachment(
        filename=filename,
        content_type=content_type,
        data=base64.b64encode(content).decode("ascii"),
    )


# ---------------------------------------------------------------------------
# Text file tests
# ---------------------------------------------------------------------------

class TestTextFile:
    def test_plain_text_extraction(self) -> None:
        att = _make_attachment("notes.txt", "text/plain", "Hello, world!")
        results = process_attachments([att])

        assert len(results) == 1
        pa = results[0]
        assert pa.filename == "notes.txt"
        assert pa.text_content is not None
        assert "Hello, world!" in pa.text_content
        assert pa.content_block is None

    def test_markdown_file(self) -> None:
        att = _make_attachment("readme.md", "text/markdown", "# Title\nBody text")
        results = process_attachments([att])

        assert len(results) == 1
        assert "# Title" in results[0].text_content
        assert results[0].content_block is None


# ---------------------------------------------------------------------------
# CSV tests
# ---------------------------------------------------------------------------

class TestCSV:
    def test_csv_to_markdown_table(self) -> None:
        csv_content = "Name,Age,City\nAlice,30,KL\nBob,25,Penang\n"
        att = _make_attachment("data.csv", "text/csv", csv_content)
        results = process_attachments([att])

        assert len(results) == 1
        pa = results[0]
        assert pa.content_block is None
        assert pa.text_content is not None
        # Should contain markdown table structure
        assert "| Name | Age | City |" in pa.text_content
        assert "| --- | --- | --- |" in pa.text_content
        assert "| Alice | 30 | KL |" in pa.text_content
        assert "| Bob | 25 | Penang |" in pa.text_content

    def test_csv_detected_by_extension(self) -> None:
        """Even with generic content-type, .csv extension triggers CSV parsing."""
        csv_content = "a,b\n1,2\n"
        att = _make_attachment("report.csv", "application/octet-stream", csv_content)
        results = process_attachments([att])

        assert len(results) == 1
        # Should still parse as CSV because of the .csv extension
        assert "| a | b |" in results[0].text_content


# ---------------------------------------------------------------------------
# Image tests
# ---------------------------------------------------------------------------

class TestImage:
    def test_png_produces_content_block(self) -> None:
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        att = _make_attachment("chart.png", "image/png", fake_png)
        results = process_attachments([att])

        assert len(results) == 1
        pa = results[0]
        assert pa.text_content is None
        assert pa.content_block is not None
        assert pa.content_block["type"] == "image"
        assert pa.content_block["source"]["type"] == "base64"
        assert pa.content_block["source"]["media_type"] == "image/png"
        # The data should be the base64-encoded content
        assert pa.content_block["source"]["data"] == att.data

    def test_jpeg_produces_content_block(self) -> None:
        fake_jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 50
        att = _make_attachment("photo.jpg", "image/jpeg", fake_jpg)
        results = process_attachments([att])

        assert len(results) == 1
        assert results[0].content_block["type"] == "image"
        assert results[0].content_block["source"]["media_type"] == "image/jpeg"

    def test_webp_produces_content_block(self) -> None:
        fake_webp = b"RIFF" + b"\x00" * 50
        att = _make_attachment("img.webp", "image/webp", fake_webp)
        results = process_attachments([att])

        assert len(results) == 1
        assert results[0].content_block["type"] == "image"


# ---------------------------------------------------------------------------
# PDF tests
# ---------------------------------------------------------------------------

class TestPDF:
    def test_pdf_without_pypdf_falls_back_to_document_block(self) -> None:
        """When pypdf is not installed, PDFs should become document content blocks."""
        # We're running in the API venv where pypdf is NOT installed.
        fake_pdf = b"%PDF-1.4 fake content"
        att = _make_attachment("report.pdf", "application/pdf", fake_pdf)
        results = process_attachments([att])

        assert len(results) == 1
        pa = results[0]
        # Should fall back to document block since pypdf is not available
        # (or if pypdf IS available, it might fail on fake content and also fall back)
        if pa.content_block is not None:
            assert pa.content_block["type"] == "document"
            assert pa.content_block["source"]["media_type"] == "application/pdf"
            assert pa.content_block["source"]["type"] == "base64"
        else:
            # pypdf managed to extract something (unlikely with fake content)
            assert pa.text_content is not None


# ---------------------------------------------------------------------------
# Size validation tests
# ---------------------------------------------------------------------------

class TestSizeValidation:
    def test_reject_oversized_attachment(self) -> None:
        """Attachments exceeding MAX_ATTACHMENT_BASE64_SIZE should be rejected."""
        oversized_data = "A" * (MAX_ATTACHMENT_BASE64_SIZE + 1)
        with pytest.raises(Exception):
            FileAttachment(
                filename="huge.bin",
                content_type="application/octet-stream",
                data=oversized_data,
            )

    def test_accept_within_limit(self) -> None:
        small_data = base64.b64encode(b"small file").decode("ascii")
        att = FileAttachment(
            filename="tiny.txt",
            content_type="text/plain",
            data=small_data,
        )
        assert att.filename == "tiny.txt"


# ---------------------------------------------------------------------------
# Multiple attachments
# ---------------------------------------------------------------------------

class TestMultipleAttachments:
    def test_mixed_attachments(self) -> None:
        """Process a mix of text and image attachments."""
        txt = _make_attachment("notes.txt", "text/plain", "Some notes")
        img = _make_attachment("chart.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
        csv_att = _make_attachment("data.csv", "text/csv", "x,y\n1,2\n")

        results = process_attachments([txt, img, csv_att])
        assert len(results) == 3

        # Text file
        assert results[0].text_content is not None
        assert results[0].content_block is None

        # Image
        assert results[1].text_content is None
        assert results[1].content_block is not None

        # CSV
        assert results[2].text_content is not None
        assert results[2].content_block is None


# ---------------------------------------------------------------------------
# Markdown table helper
# ---------------------------------------------------------------------------

class TestRowsToMarkdown:
    def test_basic_table(self) -> None:
        rows = [("Name", "Age"), ("Alice", "30"), ("Bob", "25")]
        md = _rows_to_markdown(rows)
        assert "| Name | Age |" in md
        assert "| --- | --- |" in md
        assert "| Alice | 30 |" in md

    def test_empty_rows(self) -> None:
        assert _rows_to_markdown([]) == ""


# ---------------------------------------------------------------------------
# Token cost constant
# ---------------------------------------------------------------------------

class TestTokenCost:
    def test_tokens_per_attachment_positive(self) -> None:
        assert TOKENS_PER_ATTACHMENT > 0
        assert TOKENS_PER_ATTACHMENT == 2000


# ---------------------------------------------------------------------------
# DOCX fallback (python-docx not installed)
# ---------------------------------------------------------------------------

class TestDocxFallback:
    def test_docx_without_library_gives_note(self) -> None:
        """When python-docx is not installed, DOCX files produce a fallback note."""
        fake_docx = b"PK\x03\x04" + b"\x00" * 100  # fake zip header
        att = _make_attachment(
            "doc.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            fake_docx,
        )
        results = process_attachments([att])

        assert len(results) == 1
        pa = results[0]
        assert pa.content_block is None
        assert pa.text_content is not None
        assert "doc.docx" in pa.text_content


# ---------------------------------------------------------------------------
# XLSX fallback (openpyxl not installed)
# ---------------------------------------------------------------------------

class TestXlsxFallback:
    def test_xlsx_without_library_gives_note(self) -> None:
        """When openpyxl is not installed, XLSX files produce a fallback note."""
        fake_xlsx = b"PK\x03\x04" + b"\x00" * 100
        att = _make_attachment(
            "sheet.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            fake_xlsx,
        )
        results = process_attachments([att])

        assert len(results) == 1
        pa = results[0]
        assert pa.content_block is None
        assert pa.text_content is not None
        assert "sheet.xlsx" in pa.text_content
