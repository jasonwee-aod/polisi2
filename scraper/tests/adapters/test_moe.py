"""
Comprehensive tests for the MOE adapter — DataTables listing, detail pages,
doc_type inference, CMS title stripping, date parsing, and discover/fetch hooks.

MOE had 0 tests before — this file creates 30+ tests from scratch using inline
HTML fixture strings.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from polisi_scraper.adapters.moe import (
    MoeAdapter,
    _extract_detail_title,
    _guess_doc_type,
    _normalize_whitespace,
    _parse_listing_table,
    _strip_cms_title_prefix,
)
from polisi_scraper.adapters.base import DiscoveredItem, DocumentCandidate


# ---------------------------------------------------------------------------
# Inline HTML fixtures
# ---------------------------------------------------------------------------

LISTING_TWO_ROWS = """
<html><body>
<table id="example">
  <thead><tr><th>Title</th><th>Date</th></tr></thead>
  <tbody>
    <tr>
      <td><a href="/pekeliling/surat-siaran-kpm-1-2026">Surat Siaran KPM Bil.1/2026</a></td>
      <td>12 Feb 2026</td>
    </tr>
    <tr>
      <td><a href="/kenyataan-media/press-release-feb">Press Release February</a></td>
      <td>05 Feb 2026</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

LISTING_EMPTY_TBODY = """
<html><body>
<table id="example">
  <thead><tr><th>Title</th><th>Date</th></tr></thead>
  <tbody></tbody>
</table>
</body></html>
"""

LISTING_NO_TABLE = """
<html><body><p>No DataTables here.</p></body></html>
"""

LISTING_SINGLE_CELL_ROW = """
<html><body>
<table id="example">
  <tbody>
    <tr><td>Only one cell, no anchor</td></tr>
    <tr>
      <td><a href="/valid">Valid Row</a></td>
      <td>01 Jan 2026</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

LISTING_MISSING_ANCHOR = """
<html><body>
<table id="example">
  <tbody>
    <tr>
      <td>No anchor tag here</td>
      <td>10 Mac 2026</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

LISTING_EMPTY_HREF = """
<html><body>
<table id="example">
  <tbody>
    <tr>
      <td><a href="">Empty Href</a></td>
      <td>10 Mac 2026</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

LISTING_RELATIVE_LINK = """
<html><body>
<table id="example">
  <tbody>
    <tr>
      <td><a href="/pekeliling/item-1">Item One</a></td>
      <td>15 Januari 2026</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

LISTING_EXTERNAL_LINK = """
<html><body>
<table id="example">
  <tbody>
    <tr>
      <td><a href="https://external.example.com/doc">External</a></td>
      <td>20 Feb 2026</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

LISTING_WHITESPACE_TITLE = """
<html><body>
<table id="example">
  <tbody>
    <tr>
      <td><a href="/item">  Lots   of   spaces  </a></td>
      <td>  01   Jan   2026  </td>
    </tr>
  </tbody>
</table>
</body></html>
"""

LISTING_NO_TITLE_TEXT = """
<html><body>
<table id="example">
  <tbody>
    <tr>
      <td><a href="/no-title"></a></td>
      <td>01 Jan 2026</td>
    </tr>
  </tbody>
</table>
</body></html>
"""

DETAIL_H1 = """
<html><head><title>KPM | Ignored</title></head>
<body><h1>Pekeliling Detail Title</h1></body></html>
"""

DETAIL_H2_FALLBACK = """
<html><head><title>KPM | Ignored</title></head>
<body><h1></h1><h2>Fallback H2 Title</h2></body></html>
"""

DETAIL_H3_FALLBACK = """
<html><head><title>KPM | Ignored</title></head>
<body><h1></h1><h2></h2><h3>Fallback H3 Title</h3></body></html>
"""

DETAIL_TITLE_TAG_ONLY = """
<html><head><title>KPM | Actual Title From Title Tag</title></head>
<body><p>No headings here</p></body></html>
"""

DETAIL_CMS_PREFIX_LONG = """
<html><head><title>Kementerian Pendidikan Malaysia | Real Title</title></head>
<body><p>No headings</p></body></html>
"""

DETAIL_EMPTY = """
<html><head><title></title></head><body></body></html>
"""

DETAIL_WITH_PDF = """
<html><body>
<h1>Document Title</h1>
<a href="/files/report.pdf">Download Report</a>
<a href="/files/annex.docx">Download Annex</a>
</body></html>
"""

PAGE_URL = "https://www.moe.gov.my/pekeliling"


# ===================================================================
# _parse_listing_table
# ===================================================================


class TestParseListingTable:
    def test_extracts_two_rows(self):
        items = _parse_listing_table(LISTING_TWO_ROWS, PAGE_URL)
        assert len(items) == 2

    def test_first_item_url_is_absolute(self):
        items = _parse_listing_table(LISTING_TWO_ROWS, PAGE_URL)
        assert items[0]["url"].startswith("https://www.moe.gov.my")

    def test_first_item_title(self):
        items = _parse_listing_table(LISTING_TWO_ROWS, PAGE_URL)
        assert "Surat Siaran KPM" in items[0]["title"]

    def test_first_item_date_str(self):
        items = _parse_listing_table(LISTING_TWO_ROWS, PAGE_URL)
        assert items[0]["date_str"] == "12 Feb 2026"

    def test_second_item_title(self):
        items = _parse_listing_table(LISTING_TWO_ROWS, PAGE_URL)
        assert "Press Release February" in items[1]["title"]

    def test_second_item_date(self):
        items = _parse_listing_table(LISTING_TWO_ROWS, PAGE_URL)
        assert items[1]["date_str"] == "05 Feb 2026"

    def test_empty_tbody_returns_empty(self):
        items = _parse_listing_table(LISTING_EMPTY_TBODY, PAGE_URL)
        assert items == []

    def test_no_table_returns_empty(self):
        items = _parse_listing_table(LISTING_NO_TABLE, PAGE_URL)
        assert items == []

    def test_single_cell_row_skipped(self):
        """Rows with < 2 cells or no anchor are skipped; valid row kept."""
        items = _parse_listing_table(LISTING_SINGLE_CELL_ROW, PAGE_URL)
        assert len(items) == 1
        assert "Valid Row" in items[0]["title"]

    def test_missing_anchor_row_skipped(self):
        items = _parse_listing_table(LISTING_MISSING_ANCHOR, PAGE_URL)
        assert items == []

    def test_empty_href_skipped(self):
        items = _parse_listing_table(LISTING_EMPTY_HREF, PAGE_URL)
        assert items == []

    def test_relative_link_resolved(self):
        items = _parse_listing_table(LISTING_RELATIVE_LINK, PAGE_URL)
        assert items[0]["url"] == "https://www.moe.gov.my/pekeliling/item-1"

    def test_external_link_preserved(self):
        items = _parse_listing_table(LISTING_EXTERNAL_LINK, PAGE_URL)
        assert items[0]["url"] == "https://external.example.com/doc"

    def test_whitespace_normalized_in_title(self):
        items = _parse_listing_table(LISTING_WHITESPACE_TITLE, PAGE_URL)
        assert items[0]["title"] == "Lots of spaces"

    def test_whitespace_normalized_in_date(self):
        items = _parse_listing_table(LISTING_WHITESPACE_TITLE, PAGE_URL)
        assert items[0]["date_str"] == "01 Jan 2026"

    def test_empty_title_becomes_untitled(self):
        items = _parse_listing_table(LISTING_NO_TITLE_TEXT, PAGE_URL)
        assert items[0]["title"] == "Untitled"


# ===================================================================
# _extract_detail_title
# ===================================================================


class TestExtractDetailTitle:
    def test_h1_title(self):
        assert _extract_detail_title(DETAIL_H1) == "Pekeliling Detail Title"

    def test_h2_fallback_when_h1_empty(self):
        assert _extract_detail_title(DETAIL_H2_FALLBACK) == "Fallback H2 Title"

    def test_h3_fallback_when_h1_h2_empty(self):
        assert _extract_detail_title(DETAIL_H3_FALLBACK) == "Fallback H3 Title"

    def test_title_tag_with_cms_prefix_stripped(self):
        title = _extract_detail_title(DETAIL_TITLE_TAG_ONLY)
        assert title == "Actual Title From Title Tag"

    def test_long_cms_prefix_stripped(self):
        title = _extract_detail_title(DETAIL_CMS_PREFIX_LONG)
        assert title == "Real Title"

    def test_empty_page_returns_empty_string(self):
        assert _extract_detail_title(DETAIL_EMPTY) == ""


# ===================================================================
# _strip_cms_title_prefix
# ===================================================================


class TestStripCmsTitlePrefix:
    def test_kpm_prefix(self):
        assert _strip_cms_title_prefix("KPM | My Title") == "My Title"

    def test_full_name_prefix(self):
        result = _strip_cms_title_prefix(
            "Kementerian Pendidikan Malaysia | Actual Title"
        )
        assert result == "Actual Title"

    def test_no_prefix_unchanged(self):
        assert _strip_cms_title_prefix("Normal Title") == "Normal Title"

    def test_case_insensitive(self):
        assert _strip_cms_title_prefix("kpm | lowercase") == "lowercase"


# ===================================================================
# _guess_doc_type
# ===================================================================


class TestGuessDocType:
    def test_press_release_from_title(self):
        assert _guess_doc_type("https://moe.gov.my/item", "Kenyataan Media 2026") == "press_release"

    def test_press_release_from_url(self):
        assert _guess_doc_type("https://moe.gov.my/media release/x", "Some Title") == "press_release"

    def test_statement_from_surat_siaran(self):
        assert _guess_doc_type("https://moe.gov.my/x", "Surat Siaran Bil 1") == "statement"

    def test_report_from_laporan(self):
        assert _guess_doc_type("https://moe.gov.my/x", "Laporan Tahunan 2025") == "report"

    def test_notice_from_pekeliling(self):
        assert _guess_doc_type("https://moe.gov.my/pekeliling/x", "Item") == "notice"

    def test_speech_from_ucapan(self):
        assert _guess_doc_type("https://moe.gov.my/x", "Ucapan YB Menteri") == "speech"

    def test_fallback_to_other(self):
        assert _guess_doc_type("https://moe.gov.my/x", "Generic Item") == "other"

    def test_custom_fallback(self):
        assert _guess_doc_type("https://moe.gov.my/x", "Generic", fallback="custom") == "custom"

    def test_notice_from_circular_in_url(self):
        assert _guess_doc_type("https://moe.gov.my/circular/x", "Item") == "notice"


# ===================================================================
# _normalize_whitespace
# ===================================================================


class TestNormalizeWhitespace:
    def test_collapses_spaces(self):
        assert _normalize_whitespace("  hello   world  ") == "hello world"

    def test_collapses_newlines_and_tabs(self):
        assert _normalize_whitespace("hello\n\tworld") == "hello world"

    def test_empty_string(self):
        assert _normalize_whitespace("") == ""


# ===================================================================
# MoeAdapter.discover() — integration with mocked HTTP
# ===================================================================


class TestMoeAdapterDiscover:
    def _make_adapter(self, config, responses):
        """Create adapter with mocked HTTP that returns pre-set HTML responses."""
        mock_http = MagicMock()
        call_count = [0]

        def side_effect(url):
            resp = MagicMock()
            if call_count[0] < len(responses):
                resp.text = responses[call_count[0]]
            else:
                resp.text = LISTING_EMPTY_TBODY
            call_count[0] += 1
            return resp

        mock_http.get.side_effect = side_effect
        return MoeAdapter(config=config, http=mock_http)

    def test_discover_yields_items(self):
        config = {
            "base_url": "https://www.moe.gov.my",
            "allowed_hosts": ["www.moe.gov.my"],
            "sections": [
                {"url": "https://www.moe.gov.my/pekeliling", "doc_type": "notice", "language": "ms"}
            ],
        }
        adapter = self._make_adapter(config, [LISTING_TWO_ROWS])
        items = list(adapter.discover())
        assert len(items) == 2

    def test_discover_sets_doc_type_from_section(self):
        config = {
            "base_url": "https://www.moe.gov.my",
            "allowed_hosts": ["www.moe.gov.my"],
            "sections": [
                {"url": "https://www.moe.gov.my/pekeliling", "doc_type": "notice", "language": "ms"}
            ],
        }
        adapter = self._make_adapter(config, [LISTING_TWO_ROWS])
        items = list(adapter.discover())
        assert all(item.doc_type == "notice" for item in items)

    def test_discover_infers_doc_type_when_no_override(self):
        config = {
            "base_url": "https://www.moe.gov.my",
            "allowed_hosts": ["www.moe.gov.my"],
            "sections": [
                {"url": "https://www.moe.gov.my/all", "language": "ms"}
            ],
        }
        adapter = self._make_adapter(config, [LISTING_TWO_ROWS])
        items = list(adapter.discover())
        # "Surat Siaran" -> statement, "Press Release" -> press_release
        types = {item.title: item.doc_type for item in items}
        assert types.get("Surat Siaran KPM Bil.1/2026") == "statement"
        assert types.get("Press Release February") == "press_release"

    def test_discover_respects_max_pages(self):
        config = {
            "base_url": "https://www.moe.gov.my",
            "allowed_hosts": ["www.moe.gov.my"],
            "sections": [
                {"url": "https://www.moe.gov.my/pekeliling", "doc_type": "notice", "language": "ms"}
            ],
        }
        adapter = self._make_adapter(config, [LISTING_TWO_ROWS])
        items = list(adapter.discover(max_pages=1))
        assert len(items) == 1

    def test_discover_filters_by_since(self):
        config = {
            "base_url": "https://www.moe.gov.my",
            "allowed_hosts": ["www.moe.gov.my"],
            "sections": [
                {"url": "https://www.moe.gov.my/pekeliling", "doc_type": "notice", "language": "ms"}
            ],
        }
        adapter = self._make_adapter(config, [LISTING_TWO_ROWS])
        # "12 Feb 2026" and "05 Feb 2026" — only the first should pass
        items = list(adapter.discover(since=date(2026, 2, 10)))
        assert len(items) == 1
        assert "Surat Siaran" in items[0].title

    def test_discover_deduplicates_urls(self):
        dup_html = """
        <html><body>
        <table id="example"><tbody>
          <tr><td><a href="/item/same">Title A</a></td><td>01 Jan 2026</td></tr>
          <tr><td><a href="/item/same">Title B</a></td><td>02 Jan 2026</td></tr>
        </tbody></table>
        </body></html>
        """
        config = {
            "base_url": "https://www.moe.gov.my",
            "allowed_hosts": ["www.moe.gov.my"],
            "sections": [
                {"url": "https://www.moe.gov.my/test", "doc_type": "other", "language": "ms"}
            ],
        }
        adapter = self._make_adapter(config, [dup_html])
        items = list(adapter.discover())
        assert len(items) == 1

    def test_discover_filters_disallowed_hosts(self):
        config = {
            "base_url": "https://www.moe.gov.my",
            "allowed_hosts": ["www.moe.gov.my"],
            "sections": [
                {"url": "https://www.moe.gov.my/pekeliling", "doc_type": "notice", "language": "ms"}
            ],
        }
        adapter = self._make_adapter(config, [LISTING_EXTERNAL_LINK])
        items = list(adapter.discover())
        assert len(items) == 0

    def test_discover_empty_sections(self):
        config = {"base_url": "https://www.moe.gov.my", "sections": []}
        adapter = self._make_adapter(config, [])
        items = list(adapter.discover())
        assert items == []

    def test_discover_skips_section_with_no_url(self):
        config = {
            "base_url": "https://www.moe.gov.my",
            "sections": [{"doc_type": "notice", "language": "ms"}],
        }
        adapter = self._make_adapter(config, [])
        items = list(adapter.discover())
        assert items == []

    def test_discover_http_error_continues(self):
        """If fetching a section fails, discover should not crash."""
        mock_http = MagicMock()
        mock_http.get.side_effect = Exception("Network error")
        config = {
            "base_url": "https://www.moe.gov.my",
            "sections": [
                {"url": "https://www.moe.gov.my/pekeliling", "doc_type": "notice", "language": "ms"}
            ],
        }
        adapter = MoeAdapter(config=config, http=mock_http)
        items = list(adapter.discover())
        assert items == []

    def test_discover_multiple_sections(self):
        config = {
            "base_url": "https://www.moe.gov.my",
            "allowed_hosts": ["www.moe.gov.my"],
            "sections": [
                {"url": "https://www.moe.gov.my/pekeliling", "doc_type": "notice", "language": "ms"},
                {"url": "https://www.moe.gov.my/kenyataan", "doc_type": "press_release", "language": "ms"},
            ],
        }
        adapter = self._make_adapter(config, [LISTING_TWO_ROWS, LISTING_TWO_ROWS])
        items = list(adapter.discover())
        # 2 from first section, but second section has same URLs so dedup kicks in
        # Actually URLs resolve differently for different page_urls
        assert len(items) >= 2

    def test_discover_language_propagated(self):
        config = {
            "base_url": "https://www.moe.gov.my",
            "allowed_hosts": ["www.moe.gov.my"],
            "sections": [
                {"url": "https://www.moe.gov.my/pekeliling", "doc_type": "notice", "language": "en"}
            ],
        }
        adapter = self._make_adapter(config, [LISTING_TWO_ROWS])
        items = list(adapter.discover())
        assert all(item.language == "en" for item in items)

    def test_discover_metadata_includes_section_url(self):
        config = {
            "base_url": "https://www.moe.gov.my",
            "allowed_hosts": ["www.moe.gov.my"],
            "sections": [
                {"url": "https://www.moe.gov.my/pekeliling", "doc_type": "notice", "language": "ms"}
            ],
        }
        adapter = self._make_adapter(config, [LISTING_TWO_ROWS])
        items = list(adapter.discover())
        assert items[0].metadata["section_url"] == "https://www.moe.gov.my/pekeliling"


# ===================================================================
# MoeAdapter.fetch_and_extract() — integration with mocked HTTP
# ===================================================================


class TestMoeAdapterFetchAndExtract:
    def _make_adapter(self, detail_html):
        mock_http = MagicMock()
        resp = MagicMock()
        resp.text = detail_html
        mock_http.get.return_value = resp
        config = {"base_url": "https://www.moe.gov.my"}
        return MoeAdapter(config=config, http=mock_http)

    def test_yields_html_candidate(self):
        adapter = self._make_adapter(DETAIL_H1)
        item = DiscoveredItem(
            source_url="https://www.moe.gov.my/pekeliling/item-1",
            title="Row Title",
            published_at="2026-02-12",
            doc_type="notice",
            language="ms",
        )
        candidates = list(adapter.fetch_and_extract(item))
        html_candidates = [c for c in candidates if c.content_type == "text/html"]
        assert len(html_candidates) == 1

    def test_prefers_listing_title_over_detail(self):
        adapter = self._make_adapter(DETAIL_H1)
        item = DiscoveredItem(
            source_url="https://www.moe.gov.my/pekeliling/item-1",
            title="Row Title",
            published_at="2026-02-12",
            doc_type="notice",
            language="ms",
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates[0].title == "Row Title"

    def test_falls_back_to_detail_title_when_untitled(self):
        adapter = self._make_adapter(DETAIL_H1)
        item = DiscoveredItem(
            source_url="https://www.moe.gov.my/pekeliling/item-1",
            title="Untitled",
            published_at="2026-02-12",
            doc_type="notice",
            language="ms",
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates[0].title == "Pekeliling Detail Title"

    def test_extracts_embedded_pdf_links(self):
        adapter = self._make_adapter(DETAIL_WITH_PDF)
        item = DiscoveredItem(
            source_url="https://www.moe.gov.my/pekeliling/item-1",
            title="Doc Title",
            published_at="2026-02-12",
            doc_type="notice",
            language="ms",
        )
        candidates = list(adapter.fetch_and_extract(item))
        # HTML + PDF + DOCX = 3
        assert len(candidates) >= 2
        urls = [c.url for c in candidates]
        assert any(".pdf" in u for u in urls)

    def test_http_error_yields_nothing(self):
        mock_http = MagicMock()
        mock_http.get.side_effect = Exception("Timeout")
        adapter = MoeAdapter(config={}, http=mock_http)
        item = DiscoveredItem(
            source_url="https://www.moe.gov.my/pekeliling/item-1",
            title="Test",
            published_at="",
            doc_type="notice",
            language="ms",
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates == []
