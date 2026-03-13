"""Tests for polisi_scraper.core.extractors — HTML document link extraction."""

from __future__ import annotations

import pytest

from polisi_scraper.core.extractors import DownloadLink, extract_document_links

BASE_URL = "https://example.gov.my/page"


class TestExtractDocumentLinks:
    """extract_document_links scans HTML for downloadable documents."""

    # --- Direct document link extensions ---

    def test_direct_pdf_link(self) -> None:
        html = '<html><body><a href="/docs/report.pdf">Annual Report</a></body></html>'
        links = extract_document_links(html, BASE_URL)
        assert len(links) == 1
        assert links[0].url == "https://example.gov.my/docs/report.pdf"
        assert links[0].label == "Annual Report"

    def test_docx_link(self) -> None:
        html = '<html><body><a href="/docs/form.docx">Download Form</a></body></html>'
        links = extract_document_links(html, BASE_URL)
        assert len(links) == 1
        assert links[0].url.endswith(".docx")

    def test_xlsx_link(self) -> None:
        html = '<html><body><a href="/data/stats.xlsx">Statistics</a></body></html>'
        links = extract_document_links(html, BASE_URL)
        assert len(links) == 1
        assert links[0].url.endswith(".xlsx")

    # --- Download keyword detection ---

    def test_malay_muat_turun_keyword(self) -> None:
        html = '''<html><body>
            <a href="/download/file123">Muat Turun</a>
        </body></html>'''
        links = extract_document_links(html, BASE_URL)
        assert len(links) == 1
        assert links[0].label == "Muat Turun"

    def test_english_download_keyword(self) -> None:
        html = '''<html><body>
            <a href="/get/file456">Download here</a>
        </body></html>'''
        links = extract_document_links(html, BASE_URL)
        assert len(links) == 1
        assert "Download" in links[0].label

    def test_muat_turun_with_space_variation(self) -> None:
        html = '''<html><body>
            <a href="/dl/file">Muat  Turun Dokumen</a>
        </body></html>'''
        links = extract_document_links(html, BASE_URL)
        # "muat\s*turun" regex should match "Muat  Turun"
        assert len(links) == 1

    # --- pdfjs-viewer iframes ---

    def test_pdfjs_viewer_iframe(self) -> None:
        html = '''<html><body>
            <iframe src="/pdfjs-viewer/web/viewer.html?file=%2Fuploads%2Freport.pdf"></iframe>
        </body></html>'''
        links = extract_document_links(html, BASE_URL)
        assert len(links) == 1
        assert links[0].url == "https://example.gov.my/uploads/report.pdf"
        assert links[0].label == "pdfjs-viewer embed"

    # --- CMS attachment patterns ---

    def test_getattachment_pattern(self) -> None:
        html = '''<html><body>
            <a href="/getattachment/abc-123/document.aspx">Policy Document</a>
        </body></html>'''
        links = extract_document_links(html, BASE_URL)
        assert len(links) == 1
        assert "/getattachment/" in links[0].url

    def test_file_endpoint_pattern(self) -> None:
        html = '''<html><body>
            <a href="/component/docman/file/42-annual-report">Annual Report</a>
        </body></html>'''
        links = extract_document_links(html, BASE_URL)
        assert len(links) == 1
        assert "/file" in links[0].url

    # --- Deduplication ---

    def test_duplicate_links_deduplicated(self) -> None:
        html = '''<html><body>
            <a href="/docs/report.pdf">Report v1</a>
            <a href="/docs/report.pdf">Report v2</a>
        </body></html>'''
        links = extract_document_links(html, BASE_URL)
        assert len(links) == 1

    # --- Relative URL resolution ---

    def test_relative_urls_resolved(self) -> None:
        html = '<html><body><a href="docs/report.pdf">Report</a></body></html>'
        links = extract_document_links(html, "https://example.gov.my/articles/index.html")
        assert len(links) == 1
        assert links[0].url == "https://example.gov.my/articles/docs/report.pdf"

    # --- Edge cases ---

    def test_empty_html(self) -> None:
        links = extract_document_links("", BASE_URL)
        assert links == []

    def test_no_document_links_page(self) -> None:
        html = '''<html><body>
            <a href="/about">About Us</a>
            <a href="/contact">Contact</a>
            <p>No documents here.</p>
        </body></html>'''
        links = extract_document_links(html, BASE_URL)
        assert links == []

    def test_empty_href_ignored(self) -> None:
        html = '<html><body><a href="">nothing</a></body></html>'
        links = extract_document_links(html, BASE_URL)
        assert links == []

    def test_multiple_different_documents(self) -> None:
        html = '''<html><body>
            <a href="/a.pdf">PDF</a>
            <a href="/b.docx">Word</a>
            <a href="/c.xlsx">Excel</a>
        </body></html>'''
        links = extract_document_links(html, BASE_URL)
        assert len(links) == 3
        urls = {dl.url for dl in links}
        assert "https://example.gov.my/a.pdf" in urls
        assert "https://example.gov.my/b.docx" in urls
        assert "https://example.gov.my/c.xlsx" in urls
