"""
Tests for the MOH adapter — Joomla 4 listing extraction, offset pagination,
year-based URL templates, article detail extraction, embedded PDF links,
date parsing, since filtering, and max_pages.

Uses fixture files from tests/fixtures/moh/ and inline HTML where needed.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from polisi_scraper.adapters.moh import (
    MohAdapter,
    _build_listing_url,
    _extract_article_meta,
    _extract_embedded_doc_links,
    _extract_joomla_listing_items,
    _get_listing_urls,
    _has_more_pages,
)
from polisi_scraper.adapters.base import DiscoveredItem, DocumentCandidate


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "moh"

SOURCE_URL = "https://www.moh.gov.my/en/media-kkm/media-statement/2026"
BASE_URL = "https://www.moh.gov.my"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ===================================================================
# _build_listing_url
# ===================================================================


class TestBuildListingUrl:
    def test_offset_zero_returns_base(self):
        assert _build_listing_url("https://moh.gov.my/test", 0) == "https://moh.gov.my/test"

    def test_offset_nonzero_appends_start(self):
        url = _build_listing_url("https://moh.gov.my/test", 10)
        assert url == "https://moh.gov.my/test?start=10"

    def test_existing_query_uses_ampersand(self):
        url = _build_listing_url("https://moh.gov.my/test?cat=5", 20)
        assert url == "https://moh.gov.my/test?cat=5&start=20"


# ===================================================================
# _get_listing_urls
# ===================================================================


class TestGetListingUrls:
    def test_single_url(self):
        section = {"listing_url": "https://moh.gov.my/press"}
        assert _get_listing_urls(section) == ["https://moh.gov.my/press"]

    def test_explicit_list(self):
        section = {"listing_urls": ["https://moh.gov.my/a", "https://moh.gov.my/b"]}
        urls = _get_listing_urls(section)
        assert urls == ["https://moh.gov.my/a", "https://moh.gov.my/b"]

    def test_year_template_newest_first(self):
        section = {
            "listing_url_template": "https://moh.gov.my/press/{year}",
            "year_from": 2024,
            "year_to": 2026,
        }
        urls = _get_listing_urls(section)
        assert urls == [
            "https://moh.gov.my/press/2026",
            "https://moh.gov.my/press/2025",
            "https://moh.gov.my/press/2024",
        ]

    def test_empty_section_returns_empty(self):
        assert _get_listing_urls({}) == []

    def test_template_takes_priority_over_single(self):
        section = {
            "listing_url_template": "https://moh.gov.my/{year}",
            "year_from": 2025,
            "year_to": 2025,
            "listing_url": "https://moh.gov.my/fallback",
        }
        urls = _get_listing_urls(section)
        assert urls == ["https://moh.gov.my/2025"]


# ===================================================================
# _extract_joomla_listing_items
# ===================================================================


class TestExtractJoomlaListingItems:
    def test_returns_two_items(self):
        html = _read("listing_media_statements.html")
        items = _extract_joomla_listing_items(html, SOURCE_URL)
        assert len(items) == 2

    def test_first_item_title(self):
        html = _read("listing_media_statements.html")
        items = _extract_joomla_listing_items(html, SOURCE_URL)
        assert "Pertama" in items[0]["title"]

    def test_first_item_href(self):
        html = _read("listing_media_statements.html")
        items = _extract_joomla_listing_items(html, SOURCE_URL)
        assert items[0]["href"] == "/en/media-kkm/media-statement/2026/kenyataan-media-1"

    def test_first_item_date_text(self):
        html = _read("listing_media_statements.html")
        items = _extract_joomla_listing_items(html, SOURCE_URL)
        assert items[0]["date_text"] == "23-02-2026"

    def test_second_item_date(self):
        html = _read("listing_media_statements.html")
        items = _extract_joomla_listing_items(html, SOURCE_URL)
        assert items[1]["date_text"] == "20-02-2026"

    def test_source_url_preserved(self):
        html = _read("listing_media_statements.html")
        items = _extract_joomla_listing_items(html, SOURCE_URL)
        assert all(item["source_url"] == SOURCE_URL for item in items)

    def test_empty_tbody_returns_empty(self):
        html = _read("listing_empty.html")
        items = _extract_joomla_listing_items(html, SOURCE_URL)
        assert items == []

    def test_no_table_returns_empty(self):
        items = _extract_joomla_listing_items(
            "<html><body>No table here</body></html>", SOURCE_URL
        )
        assert items == []

    def test_last_page_has_one_item(self):
        html = _read("listing_last_page.html")
        items = _extract_joomla_listing_items(html, SOURCE_URL)
        assert len(items) == 1

    def test_deduplicates_hrefs(self):
        html = """
        <table class="com-content-category__table category">
          <tbody>
            <tr><td class="list-title"><a href="/dup">A</a></td><td class="list-date small">01-01-2026</td></tr>
            <tr><td class="list-title"><a href="/dup">B</a></td><td class="list-date small">02-01-2026</td></tr>
          </tbody>
        </table>
        """
        items = _extract_joomla_listing_items(html, SOURCE_URL)
        assert len(items) == 1

    def test_skips_javascript_hrefs(self):
        html = """
        <table class="com-content-category__table category">
          <tbody>
            <tr><td class="list-title"><a href="javascript:void(0)">Bad</a></td><td class="list-date">01-01-2026</td></tr>
          </tbody>
        </table>
        """
        items = _extract_joomla_listing_items(html, SOURCE_URL)
        assert items == []

    def test_skips_mailto_hrefs(self):
        html = """
        <table class="com-content-category__table category">
          <tbody>
            <tr><td class="list-title"><a href="mailto:a@b.com">Mail</a></td><td class="list-date">01-01-2026</td></tr>
          </tbody>
        </table>
        """
        items = _extract_joomla_listing_items(html, SOURCE_URL)
        assert items == []


# ===================================================================
# _has_more_pages
# ===================================================================


class TestHasMorePages:
    def test_more_pages_at_offset_0(self):
        html = _read("listing_media_statements.html")
        assert _has_more_pages(html, 0) is True

    def test_more_pages_at_offset_10(self):
        html = _read("listing_media_statements.html")
        assert _has_more_pages(html, 10) is True

    def test_no_more_pages_at_last_offset(self):
        html = _read("listing_last_page.html")
        assert _has_more_pages(html, 10) is False

    def test_no_pagination_widget_returns_false(self):
        html = _read("listing_empty.html")
        assert _has_more_pages(html, 0) is False

    def test_no_pagination_in_plain_html(self):
        assert _has_more_pages("<html><body></body></html>", 0) is False


# ===================================================================
# _extract_article_meta
# ===================================================================


class TestExtractArticleMeta:
    def test_title_from_h1_itemprop(self):
        html = _read("detail_article.html")
        meta = _extract_article_meta(html)
        assert meta["title"] == "Kenyataan Media Test"

    def test_published_at_from_time_itemprop(self):
        html = _read("detail_article.html")
        meta = _extract_article_meta(html)
        assert meta["published_at"] == "2026-02-23"

    def test_og_title_fallback(self):
        html = """
        <html><head>
          <meta property="og:title" content="OG Title Fallback">
        </head><body><article><p>No h1</p></article></body></html>
        """
        meta = _extract_article_meta(html)
        assert meta["title"] == "OG Title Fallback"

    def test_title_tag_fallback(self):
        html = """
        <html><head>
          <title>Title Tag Article | Kementerian Kesihatan Malaysia</title>
        </head><body></body></html>
        """
        meta = _extract_article_meta(html)
        assert meta["title"] == "Title Tag Article"

    def test_article_published_time_meta(self):
        html = """
        <html><head>
          <meta property="article:published_time" content="2026-01-15T00:00:00+08:00">
        </head><body>
          <article><h1 itemprop="headline">Test</h1></article>
        </body></html>
        """
        meta = _extract_article_meta(html)
        assert meta["published_at"] == "2026-01-15"

    def test_no_date_returns_empty(self):
        html = "<html><head></head><body><article><h1 itemprop='headline'>X</h1></article></body></html>"
        meta = _extract_article_meta(html)
        assert meta["published_at"] == ""

    def test_date_modified_fallback(self):
        html = """
        <html><body>
          <time datetime="2026-03-01T00:00:00" itemprop="dateModified">1 Mar 2026</time>
        </body></html>
        """
        meta = _extract_article_meta(html)
        assert meta["published_at"] == "2026-03-01"

    def test_h2_inside_article_fallback(self):
        html = """
        <html><body>
          <article><h2>Article H2 Title</h2></article>
        </body></html>
        """
        meta = _extract_article_meta(html)
        assert meta["title"] == "Article H2 Title"


# ===================================================================
# _extract_embedded_doc_links
# ===================================================================


class TestExtractEmbeddedDocLinks:
    def test_finds_pdf_and_docx(self):
        html = _read("detail_article.html")
        links = _extract_embedded_doc_links(html, BASE_URL)
        assert len(links) == 2

    def test_pdf_url_is_absolute(self):
        html = _read("detail_article.html")
        links = _extract_embedded_doc_links(html, BASE_URL)
        pdf_links = [l for l in links if l.url.endswith(".pdf")]
        assert len(pdf_links) == 1
        assert pdf_links[0].url.startswith("https://www.moh.gov.my")

    def test_docx_url_present(self):
        html = _read("detail_article.html")
        links = _extract_embedded_doc_links(html, BASE_URL)
        docx_links = [l for l in links if l.url.endswith(".docx")]
        assert len(docx_links) == 1

    def test_no_duplicate_links(self):
        html = """
        <html><body>
          <div itemprop="articleBody">
            <a href="/doc.pdf">PDF 1</a>
            <a href="/doc.pdf">PDF 1 again</a>
          </div>
        </body></html>
        """
        links = _extract_embedded_doc_links(html, BASE_URL)
        assert len(links) == 1

    def test_mailto_not_included(self):
        html = _read("detail_article.html")
        links = _extract_embedded_doc_links(html, BASE_URL)
        assert not any("mailto:" in l.url for l in links)

    def test_no_docs_returns_empty(self):
        html = "<html><body><p>No documents here.</p></body></html>"
        links = _extract_embedded_doc_links(html, BASE_URL)
        assert links == []

    def test_javascript_href_ignored(self):
        html = """
        <html><body>
          <div itemprop="articleBody">
            <a href="javascript:void(0)">Click</a>
          </div>
        </body></html>
        """
        links = _extract_embedded_doc_links(html, BASE_URL)
        assert links == []


# ===================================================================
# MohAdapter.discover() — integration with mocked HTTP
# ===================================================================


class TestMohAdapterDiscover:
    def _make_adapter(self, config, responses):
        """Create adapter with mocked HTTP returning pre-set HTML per call."""
        mock_http = MagicMock()
        call_count = [0]

        def side_effect(url):
            resp = MagicMock()
            if call_count[0] < len(responses):
                resp.text = responses[call_count[0]]
            else:
                resp.text = _read("listing_empty.html")
            call_count[0] += 1
            return resp

        mock_http.get.side_effect = side_effect
        return MohAdapter(config=config, http=mock_http)

    def test_discover_yields_items_single_page(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "media_statements",
                "listing_url": f"{BASE_URL}/en/media-kkm/media-statement/2026",
                "doc_type": "press_release",
                "language": "ms",
                "page_size": 10,
            }],
        }
        # First page has 2 items + pagination; second page is last
        adapter = self._make_adapter(config, [
            _read("listing_media_statements.html"),
            _read("listing_last_page.html"),
            _read("listing_empty.html"),
        ])
        items = list(adapter.discover())
        assert len(items) >= 2

    def test_discover_max_pages_limits_fetches(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "test",
                "listing_url": f"{BASE_URL}/en/test",
                "doc_type": "other",
                "language": "ms",
                "page_size": 10,
            }],
        }
        adapter = self._make_adapter(config, [
            _read("listing_media_statements.html"),
            _read("listing_last_page.html"),
        ])
        items = list(adapter.discover(max_pages=1))
        # With max_pages=1, only first page is fetched -> 2 items
        assert len(items) == 2

    def test_discover_since_filter(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "test",
                "listing_url": f"{BASE_URL}/en/test",
                "doc_type": "press_release",
                "language": "ms",
                "page_size": 10,
            }],
        }
        adapter = self._make_adapter(config, [
            _read("listing_media_statements.html"),
            _read("listing_empty.html"),
        ])
        # Dates: 23-02-2026, 20-02-2026 — only first passes since=2026-02-22
        items = list(adapter.discover(since=date(2026, 2, 22)))
        assert len(items) == 1

    def test_discover_empty_listing_stops(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "test",
                "listing_url": f"{BASE_URL}/en/test",
                "doc_type": "other",
                "language": "ms",
                "page_size": 10,
            }],
        }
        adapter = self._make_adapter(config, [_read("listing_empty.html")])
        items = list(adapter.discover())
        assert items == []

    def test_discover_doc_type_propagated(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "test",
                "listing_url": f"{BASE_URL}/en/test",
                "doc_type": "report",
                "language": "ms",
                "page_size": 10,
            }],
        }
        adapter = self._make_adapter(config, [
            _read("listing_media_statements.html"),
            _read("listing_empty.html"),
        ])
        items = list(adapter.discover())
        assert all(item.doc_type == "report" for item in items)

    def test_discover_year_template_sections(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "test",
                "listing_url_template": f"{BASE_URL}/en/press/{{year}}",
                "year_from": 2025,
                "year_to": 2026,
                "doc_type": "press_release",
                "language": "ms",
                "page_size": 10,
            }],
        }
        adapter = self._make_adapter(config, [
            _read("listing_media_statements.html"),
            _read("listing_empty.html"),
            _read("listing_media_statements.html"),
            _read("listing_empty.html"),
        ])
        items = list(adapter.discover())
        assert len(items) >= 2

    def test_discover_http_error_breaks_seed(self):
        mock_http = MagicMock()
        mock_http.get.side_effect = Exception("Network error")
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "test",
                "listing_url": f"{BASE_URL}/en/test",
                "doc_type": "other",
                "language": "ms",
            }],
        }
        adapter = MohAdapter(config=config, http=mock_http)
        items = list(adapter.discover())
        assert items == []

    def test_discover_no_sections(self):
        config = {"base_url": BASE_URL, "sections": []}
        adapter = self._make_adapter(config, [])
        items = list(adapter.discover())
        assert items == []


# ===================================================================
# MohAdapter.fetch_and_extract()
# ===================================================================


class TestMohAdapterFetchAndExtract:
    def _make_adapter(self, html):
        mock_http = MagicMock()
        resp = MagicMock()
        resp.text = html
        mock_http.get.return_value = resp
        return MohAdapter(config={"base_url": BASE_URL}, http=mock_http)

    def test_yields_html_candidate(self):
        adapter = self._make_adapter(_read("detail_article.html"))
        item = DiscoveredItem(
            source_url=f"{BASE_URL}/en/media-kkm/media-statement/2026/kenyataan-media-1",
            title="Kenyataan Media Pertama",
            published_at="2026-02-23",
            doc_type="press_release",
            language="ms",
            metadata={"listing_url": SOURCE_URL, "date_text": "23-02-2026", "section": "test"},
        )
        candidates = list(adapter.fetch_and_extract(item))
        html_candidates = [c for c in candidates if c.content_type == "text/html"]
        assert len(html_candidates) == 1

    def test_extracts_embedded_docs(self):
        adapter = self._make_adapter(_read("detail_article.html"))
        item = DiscoveredItem(
            source_url=f"{BASE_URL}/en/media-kkm/media-statement/2026/kenyataan-media-1",
            title="Kenyataan Media Pertama",
            published_at="2026-02-23",
            doc_type="press_release",
            language="ms",
            metadata={"listing_url": SOURCE_URL, "date_text": "23-02-2026", "section": "test"},
        )
        candidates = list(adapter.fetch_and_extract(item))
        # HTML + PDF + DOCX = 3
        assert len(candidates) == 3
        urls = [c.url for c in candidates]
        assert any(".pdf" in u for u in urls)
        assert any(".docx" in u for u in urls)

    def test_direct_pdf_url_yields_without_fetch(self):
        mock_http = MagicMock()
        adapter = MohAdapter(config={"base_url": BASE_URL}, http=mock_http)
        item = DiscoveredItem(
            source_url=f"{BASE_URL}/images/report.pdf",
            title="Report",
            published_at="2026-01-01",
            doc_type="report",
            language="ms",
            metadata={"listing_url": SOURCE_URL},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert len(candidates) == 1
        assert candidates[0].content_type == "application/pdf"
        # HTTP should NOT be called for direct PDF
        mock_http.get.assert_not_called()

    def test_http_error_yields_nothing(self):
        mock_http = MagicMock()
        mock_http.get.side_effect = Exception("Timeout")
        adapter = MohAdapter(config={"base_url": BASE_URL}, http=mock_http)
        item = DiscoveredItem(
            source_url=f"{BASE_URL}/en/article",
            title="Test",
            published_at="",
            doc_type="other",
            language="ms",
            metadata={},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates == []

    def test_title_from_detail_page_used(self):
        adapter = self._make_adapter(_read("detail_article.html"))
        item = DiscoveredItem(
            source_url=f"{BASE_URL}/en/article",
            title="Listing Title",
            published_at="",
            doc_type="press_release",
            language="ms",
            metadata={"listing_url": SOURCE_URL, "date_text": "23-02-2026", "section": "test"},
        )
        candidates = list(adapter.fetch_and_extract(item))
        # Detail page title "Kenyataan Media Test" should be used
        assert candidates[0].title == "Kenyataan Media Test"

    def test_published_at_from_detail_page(self):
        adapter = self._make_adapter(_read("detail_article.html"))
        item = DiscoveredItem(
            source_url=f"{BASE_URL}/en/article",
            title="Test",
            published_at="",
            doc_type="press_release",
            language="ms",
            metadata={"listing_url": SOURCE_URL, "date_text": "", "section": "test"},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates[0].published_at == "2026-02-23"


# ===================================================================
# MohAdapter.extract_downloads()
# ===================================================================


class TestMohAdapterExtractDownloads:
    def test_returns_embedded_links_from_article_body(self):
        adapter = MohAdapter(config={"base_url": BASE_URL})
        html = _read("detail_article.html")
        links = adapter.extract_downloads(html, BASE_URL)
        assert len(links) >= 2

    def test_fallback_to_generic_extractor(self):
        adapter = MohAdapter(config={"base_url": BASE_URL})
        html = """
        <html><body>
          <a href="/some/report.pdf">Download report</a>
        </body></html>
        """
        links = adapter.extract_downloads(html, BASE_URL)
        assert len(links) >= 1
