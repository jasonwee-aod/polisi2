"""Tests for the Perpaduan adapter — CSS selector-driven HTML scraping.

Covers:
  - Discovery from CSS selectors (item_selector, title_selector, link_selector, date_selector)
  - Title extraction and fallback to truncated text
  - Date extraction via parse_malay_date
  - Link extraction and absolute URL resolution
  - Empty sections and error handling
  - since date filtering
  - fetch_and_extract()
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from polisi_scraper.adapters.perpaduan import PerpaduanAdapter
from polisi_scraper.adapters.base import DiscoveredItem, DocumentCandidate, HTTPClient


def _mock_http(html_by_url: dict[str, str] | None = None) -> MagicMock:
    """Build a mock HTTPClient that returns HTML for given URLs."""
    http = MagicMock(spec=HTTPClient)

    def fake_get(url, **kwargs):
        resp = MagicMock()
        if html_by_url and url in html_by_url:
            resp.text = html_by_url[url]
        else:
            resp.text = "<html><body></body></html>"
        return resp

    http.get.side_effect = fake_get
    return http


def _make_adapter(config: dict, http: MagicMock | None = None) -> PerpaduanAdapter:
    adapter = PerpaduanAdapter.__new__(PerpaduanAdapter)
    adapter.config = config
    adapter.http = http or _mock_http()
    adapter.state = None
    adapter.archiver = None
    adapter.browser_pool = None
    return adapter


# ── Sample HTML fixtures ──────────────────────────────────────────────────

_LISTING_HTML = """
<html>
<body>
<div class="articles">
    <div class="article-item">
        <h3 class="title">Kenyataan Media: Hari Perpaduan Negara 2026</h3>
        <span class="date">13 Mac 2026</span>
        <a href="/index.php/bm/kenyataan-media/item/123-hari-perpaduan">Read more</a>
    </div>
    <div class="article-item">
        <h3 class="title">Laporan Aktiviti Suku Tahun Pertama</h3>
        <span class="date">1 Januari 2026</span>
        <a href="/index.php/bm/laporan/item/456-laporan-q1">Read more</a>
    </div>
    <div class="article-item">
        <h3 class="title">Mesyuarat Jawatankuasa</h3>
        <span class="date">15 Disember 2025</span>
        <a href="/index.php/bm/mesyuarat/item/789-jawatankuasa">Read more</a>
    </div>
</div>
</body>
</html>
"""

_SECTION_CONFIG = {
    "url": "https://www.perpaduan.gov.my/index.php/bm/kenyataan-media",
    "doc_type": "press_release",
    "item_selector": ".article-item",
    "title_selector": ".title",
    "link_selector": "a",
    "date_selector": ".date",
}


# ═══════════════════════════════════════════════════════════════════════════
# Discovery from CSS selectors
# ═══════════════════════════════════════════════════════════════════════════


class TestDiscoveryCssSelectors:
    def test_extracts_correct_number_of_items(self):
        http = _mock_http({_SECTION_CONFIG["url"]: _LISTING_HTML})
        adapter = _make_adapter({"sections": [_SECTION_CONFIG]}, http)
        items = list(adapter.discover())
        assert len(items) == 3

    def test_title_extracted_from_selector(self):
        http = _mock_http({_SECTION_CONFIG["url"]: _LISTING_HTML})
        adapter = _make_adapter({"sections": [_SECTION_CONFIG]}, http)
        items = list(adapter.discover())
        titles = [i.title for i in items]
        assert "Kenyataan Media: Hari Perpaduan Negara 2026" in titles
        assert "Laporan Aktiviti Suku Tahun Pertama" in titles
        assert "Mesyuarat Jawatankuasa" in titles

    def test_links_resolved_to_absolute(self):
        http = _mock_http({_SECTION_CONFIG["url"]: _LISTING_HTML})
        adapter = _make_adapter({"sections": [_SECTION_CONFIG]}, http)
        items = list(adapter.discover())
        assert all(i.source_url.startswith("https://") for i in items)

    def test_href_correctly_joined(self):
        http = _mock_http({_SECTION_CONFIG["url"]: _LISTING_HTML})
        adapter = _make_adapter({"sections": [_SECTION_CONFIG]}, http)
        items = list(adapter.discover())
        hrefs = [i.source_url for i in items]
        assert any("item/123-hari-perpaduan" in h for h in hrefs)
        assert any("item/456-laporan-q1" in h for h in hrefs)

    def test_doc_type_propagated(self):
        http = _mock_http({_SECTION_CONFIG["url"]: _LISTING_HTML})
        adapter = _make_adapter({"sections": [_SECTION_CONFIG]}, http)
        items = list(adapter.discover())
        assert all(i.doc_type == "press_release" for i in items)

    def test_language_always_ms(self):
        http = _mock_http({_SECTION_CONFIG["url"]: _LISTING_HTML})
        adapter = _make_adapter({"sections": [_SECTION_CONFIG]}, http)
        items = list(adapter.discover())
        assert all(i.language == "ms" for i in items)


# ═══════════════════════════════════════════════════════════════════════════
# Date extraction
# ═══════════════════════════════════════════════════════════════════════════


class TestDateExtraction:
    def test_malay_date_parsed(self):
        http = _mock_http({_SECTION_CONFIG["url"]: _LISTING_HTML})
        adapter = _make_adapter({"sections": [_SECTION_CONFIG]}, http)
        items = list(adapter.discover())
        dates = {i.title: i.published_at for i in items}
        # "13 Mac 2026" -> Mac = March
        assert dates["Kenyataan Media: Hari Perpaduan Negara 2026"] == "2026-03-13"

    def test_no_date_selector_yields_empty_date(self):
        section = {**_SECTION_CONFIG, "date_selector": ""}
        http = _mock_http({_SECTION_CONFIG["url"]: _LISTING_HTML})
        adapter = _make_adapter({"sections": [section]}, http)
        items = list(adapter.discover())
        assert all(i.published_at == "" for i in items)


# ═══════════════════════════════════════════════════════════════════════════
# Title fallback
# ═══════════════════════════════════════════════════════════════════════════


class TestTitleFallback:
    def test_fallback_to_item_text_when_no_title_selector(self):
        html = """
        <html><body>
        <div class="items">
            <div class="item">
                Short text with a <a href="/page1">link</a>
            </div>
        </div>
        </body></html>
        """
        section = {
            "url": "https://www.perpaduan.gov.my/test",
            "doc_type": "other",
            "item_selector": ".item",
            "title_selector": "",
            "link_selector": "a",
            "date_selector": "",
        }
        http = _mock_http({"https://www.perpaduan.gov.my/test": html})
        adapter = _make_adapter({"sections": [section]}, http)
        items = list(adapter.discover())
        assert len(items) == 1
        assert "Short text" in items[0].title

    def test_title_truncated_to_200_chars(self):
        long_text = "A" * 300
        html = f"""
        <html><body>
        <div class="items">
            <div class="item">
                {long_text} <a href="/page1">link</a>
            </div>
        </div>
        </body></html>
        """
        section = {
            "url": "https://www.perpaduan.gov.my/test",
            "doc_type": "other",
            "item_selector": ".item",
            "title_selector": "",
            "link_selector": "a",
            "date_selector": "",
        }
        http = _mock_http({"https://www.perpaduan.gov.my/test": html})
        adapter = _make_adapter({"sections": [section]}, http)
        items = list(adapter.discover())
        assert len(items[0].title) <= 200


# ═══════════════════════════════════════════════════════════════════════════
# Empty sections and error handling
# ═══════════════════════════════════════════════════════════════════════════


class TestEmptySectionsAndErrors:
    def test_empty_html_no_items(self):
        html = "<html><body></body></html>"
        section = {**_SECTION_CONFIG}
        http = _mock_http({_SECTION_CONFIG["url"]: html})
        adapter = _make_adapter({"sections": [section]}, http)
        items = list(adapter.discover())
        assert items == []

    def test_section_without_url_skipped(self):
        section = {**_SECTION_CONFIG, "url": ""}
        adapter = _make_adapter({"sections": [section]}, _mock_http())
        items = list(adapter.discover())
        assert items == []

    def test_http_error_graceful(self):
        http = MagicMock(spec=HTTPClient)
        http.get.side_effect = Exception("Timeout")
        adapter = _make_adapter({"sections": [_SECTION_CONFIG]}, http)
        items = list(adapter.discover())
        assert items == []

    def test_no_sections_key(self):
        adapter = _make_adapter({}, _mock_http())
        items = list(adapter.discover())
        assert items == []

    def test_item_without_link_skipped(self):
        html = """
        <html><body>
        <div class="articles">
            <div class="article-item">
                <h3 class="title">No Link Here</h3>
            </div>
        </div>
        </body></html>
        """
        http = _mock_http({_SECTION_CONFIG["url"]: html})
        adapter = _make_adapter({"sections": [_SECTION_CONFIG]}, http)
        items = list(adapter.discover())
        assert items == []

    def test_item_with_empty_href_skipped(self):
        html = """
        <html><body>
        <div class="articles">
            <div class="article-item">
                <h3 class="title">Empty Href</h3>
                <a href="">link</a>
            </div>
        </div>
        </body></html>
        """
        http = _mock_http({_SECTION_CONFIG["url"]: html})
        adapter = _make_adapter({"sections": [_SECTION_CONFIG]}, http)
        items = list(adapter.discover())
        assert items == []


# ═══════════════════════════════════════════════════════════════════════════
# since date filtering
# ═══════════════════════════════════════════════════════════════════════════


class TestSinceFiltering:
    def test_old_items_filtered_out(self):
        http = _mock_http({_SECTION_CONFIG["url"]: _LISTING_HTML})
        adapter = _make_adapter({"sections": [_SECTION_CONFIG]}, http)
        # "15 Disember 2025" should be filtered with since=2026-01-01
        items = list(adapter.discover(since=date(2026, 1, 1)))
        titles = [i.title for i in items]
        assert "Mesyuarat Jawatankuasa" not in titles
        # The 2026 items should remain
        assert len(items) >= 1

    def test_no_since_returns_all(self):
        http = _mock_http({_SECTION_CONFIG["url"]: _LISTING_HTML})
        adapter = _make_adapter({"sections": [_SECTION_CONFIG]}, http)
        items = list(adapter.discover(since=None))
        assert len(items) == 3


# ═══════════════════════════════════════════════════════════════════════════
# fetch_and_extract()
# ═══════════════════════════════════════════════════════════════════════════


class TestFetchAndExtract:
    def test_yields_html_document_candidate(self):
        adapter = _make_adapter({})
        item = DiscoveredItem(
            source_url="https://www.perpaduan.gov.my/index.php/bm/item/123",
            title="Test Document",
            published_at="2026-01-01",
            doc_type="press_release",
            language="ms",
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert len(candidates) == 1
        assert isinstance(candidates[0], DocumentCandidate)

    def test_content_type_is_html(self):
        adapter = _make_adapter({})
        item = DiscoveredItem(
            source_url="https://www.perpaduan.gov.my/page",
            title="Test",
            language="ms",
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates[0].content_type == "text/html"

    def test_candidate_preserves_fields(self):
        adapter = _make_adapter({})
        item = DiscoveredItem(
            source_url="https://www.perpaduan.gov.my/page",
            title="My Title",
            published_at="2026-03-13",
            doc_type="news",
            language="ms",
        )
        candidates = list(adapter.fetch_and_extract(item))
        c = candidates[0]
        assert c.title == "My Title"
        assert c.published_at == "2026-03-13"
        assert c.doc_type == "news"
        assert c.url == "https://www.perpaduan.gov.my/page"
        assert c.source_page_url == "https://www.perpaduan.gov.my/page"


# ═══════════════════════════════════════════════════════════════════════════
# Adapter properties
# ═══════════════════════════════════════════════════════════════════════════


class TestAdapterProperties:
    def test_slug(self):
        assert PerpaduanAdapter.slug == "perpaduan"

    def test_agency(self):
        assert "Perpaduan" in PerpaduanAdapter.agency

    def test_requires_browser_false(self):
        assert PerpaduanAdapter.requires_browser is False
