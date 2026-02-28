from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from polisi_scraper.indexer.parsers import HtmlParser, PdfParser


class _FakePdfPage:
    def __init__(self, text: str | None = None, *, raise_error: bool = False) -> None:
        self._text = text
        self._raise_error = raise_error

    def extract_text(self) -> str:
        if self._raise_error:
            raise ValueError("cannot extract")
        return self._text or ""


class _FakePdfReader:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.pages = [
            _FakePdfPage("Budget 2026 overview"),
            _FakePdfPage(raise_error=True),
            _FakePdfPage("Page 3 recovery text"),
        ]


def test_html_and_pdf_parsers_preserve_locators(monkeypatch) -> None:
    html_parser = HtmlParser()
    html = html_parser.parse_bytes(
        b"""
        <html>
          <head><title>Budget Highlights</title></head>
          <body>
            <h1>Subsidies</h1>
            <p>Fuel support continues in 2026.</p>
            <ul><li>Targeted households only.</li></ul>
          </body>
        </html>
        """
    )

    monkeypatch.setattr("polisi_scraper.indexer.parsers.pdf.PdfReader", _FakePdfReader)
    pdf = PdfParser().parse_bytes(b"%PDF-1.4", metadata={"title": "Budget PDF"})

    assert html.title == "Budget Highlights"
    assert html.blocks[0].section_heading == "Subsidies"
    assert html.blocks[1].block_type == "list_item"
    assert [block.page_number for block in pdf.blocks] == [1, 3]
    assert pdf.blocks[1].text == "Page 3 recovery text"
