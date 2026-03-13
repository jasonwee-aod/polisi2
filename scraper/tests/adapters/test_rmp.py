"""Tests for the RMP adapter — Sitefinity listing, RadGrid publications, pagination, article detail.

Covers:
  - Sitefinity listing discovery (data-sf-field)
  - Path-based pagination (/page/N)
  - RadGrid table extraction
  - sfdownloadLink patterns
  - /docs/default-source/ URL patterns
  - Article detail extraction
  - Date parsing (URL + microdata)
  - since filtering
  - max_pages
"""
from __future__ import annotations

import base64
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from polisi_scraper.adapters.rmp import (
    BASE_URL,
    RmpAdapter,
    _date_from_url,
    _extract_article_meta,
    _extract_embedded_doc_links,
    _extract_listing_items,
    _extract_publications,
    _get_next_page_url,
)
from polisi_scraper.adapters.base import DiscoveredItem, DocumentCandidate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "rmp"
LISTING_URL = "https://www.rmp.gov.my/arkib-berita/berita"
PUBS_URL = "https://www.rmp.gov.my/laman-utama/penerbitan"
DETAIL_URL = "https://www.rmp.gov.my/arkib-berita/berita/2026/03/09/pdrm-tangkap-suspek-rompakan"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# _date_from_url
# ---------------------------------------------------------------------------


class TestDateFromUrl:
    def test_extracts_date_from_sitefinity_path(self):
        url = "/arkib-berita/berita/2026/03/09/some-article"
        assert _date_from_url(url) == "2026-03-09"

    def test_extracts_date_from_full_url(self):
        url = "https://www.rmp.gov.my/arkib-berita/berita/2024/01/15/mesyuarat"
        assert _date_from_url(url) == "2024-01-15"

    def test_no_date_returns_empty(self):
        url = "/arkib-berita/berita"
        assert _date_from_url(url) == ""

    def test_no_date_for_non_date_numbers(self):
        url = "/some/page/123"
        assert _date_from_url(url) == ""


# ---------------------------------------------------------------------------
# _extract_listing_items — Sitefinity listing discovery
# ---------------------------------------------------------------------------


class TestExtractListingItems:
    def test_returns_three_items_from_fixture(self):
        html = _read("listing_berita.html")
        items = _extract_listing_items(html, LISTING_URL)
        assert len(items) == 3

    def test_first_item_title(self):
        html = _read("listing_berita.html")
        items = _extract_listing_items(html, LISTING_URL)
        assert "Rompakan" in items[0]["title"]

    def test_first_item_href(self):
        html = _read("listing_berita.html")
        items = _extract_listing_items(html, LISTING_URL)
        assert items[0]["href"] == "/arkib-berita/berita/2026/03/09/pdrm-tangkap-suspek-rompakan"

    def test_first_item_date_text(self):
        html = _read("listing_berita.html")
        items = _extract_listing_items(html, LISTING_URL)
        assert items[0]["date_text"] == "09 March 2026"

    def test_malay_date_text_preserved(self):
        html = _read("listing_berita.html")
        items = _extract_listing_items(html, LISTING_URL)
        assert items[2]["date_text"] == "05 Mac 2026"

    def test_source_url_preserved(self):
        html = _read("listing_berita.html")
        items = _extract_listing_items(html, LISTING_URL)
        assert all(item["source_url"] == LISTING_URL for item in items)

    def test_empty_page_returns_empty(self):
        html = _read("listing_empty.html")
        items = _extract_listing_items(html, LISTING_URL)
        assert items == []

    def test_no_duplicates(self):
        html = """
        <div class="sfnewsItem">
          <h2><a data-sf-field="Title" href="/foo">Foo</a></h2>
        </div>
        <div class="sfnewsItem">
          <h2><a data-sf-field="Title" href="/foo">Foo Again</a></h2>
        </div>
        """
        items = _extract_listing_items(html, LISTING_URL)
        assert len(items) == 1

    def test_skips_javascript_hrefs(self):
        html = """
        <a data-sf-field="Title" href="javascript:void(0)">JS Link</a>
        <a data-sf-field="Title" href="/real-article">Real</a>
        """
        items = _extract_listing_items(html, LISTING_URL)
        assert len(items) == 1
        assert items[0]["href"] == "/real-article"

    def test_skips_mailto_hrefs(self):
        html = '<a data-sf-field="Title" href="mailto:info@rmp.gov.my">Mail</a>'
        items = _extract_listing_items(html, LISTING_URL)
        assert items == []

    def test_last_page_returns_one_item(self):
        html = _read("listing_last_page.html")
        items = _extract_listing_items(html, LISTING_URL)
        assert len(items) == 1

    def test_fallback_sfnewsItem_container(self):
        """If no data-sf-field anchors, falls back to anchors inside sfnewsItem."""
        html = """
        <div class="sfnewsItem">
          <h2 class="sfnewsItemTitle"><a href="/article-1">Article One</a></h2>
        </div>
        """
        items = _extract_listing_items(html, LISTING_URL)
        assert len(items) == 1
        assert items[0]["title"] == "Article One"

    def test_date_from_url_fallback_when_no_sfnewsDate(self):
        """When no sfnewsDate element exists, date is extracted from href."""
        html = """
        <div class="sfnewsItem">
          <a data-sf-field="Title" href="/news/2025/06/15/some-news">Some News</a>
        </div>
        """
        items = _extract_listing_items(html, LISTING_URL)
        assert items[0]["date_text"] == "2025-06-15"


# ---------------------------------------------------------------------------
# _extract_publications — RadGrid table extraction
# ---------------------------------------------------------------------------


class TestExtractPublications:
    def test_returns_three_items(self):
        html = _read("listing_publications.html")
        items = _extract_publications(html, PUBS_URL)
        assert len(items) == 3

    def test_first_item_title(self):
        html = _read("listing_publications.html")
        items = _extract_publications(html, PUBS_URL)
        assert "Berita Bukit Aman" in items[0]["title"]

    def test_first_item_href_contains_pdf(self):
        html = _read("listing_publications.html")
        items = _extract_publications(html, PUBS_URL)
        assert ".pdf" in items[0]["href"].lower()

    def test_sfdownloadLink_detected(self):
        html = _read("listing_publications.html")
        items = _extract_publications(html, PUBS_URL)
        assert len(items) == 3  # All 3 use sfdownloadLink

    def test_docx_item_detected(self):
        html = _read("listing_publications.html")
        items = _extract_publications(html, PUBS_URL)
        docx_items = [i for i in items if ".docx" in i["href"].lower()]
        assert len(docx_items) == 1

    def test_sfvrsn_preserved_in_href(self):
        html = _read("listing_publications.html")
        items = _extract_publications(html, PUBS_URL)
        assert "sfvrsn" in items[0]["href"]

    def test_no_table_returns_empty(self):
        html = "<html><body><p>No table</p></body></html>"
        items = _extract_publications(html, PUBS_URL)
        assert items == []

    def test_no_duplicates(self):
        html = """
        <table class="rgMasterTable"><tbody>
          <tr><td>Doc A</td><td><a class="sfdownloadLink" href="/docs/a.pdf">DL</a></td></tr>
          <tr><td>Doc A</td><td><a class="sfdownloadLink" href="/docs/a.pdf">DL</a></td></tr>
        </tbody></table>
        """
        items = _extract_publications(html, PUBS_URL)
        assert len(items) == 1

    def test_source_url_preserved(self):
        html = _read("listing_publications.html")
        items = _extract_publications(html, PUBS_URL)
        assert all(item["source_url"] == PUBS_URL for item in items)

    def test_docs_default_source_fallback(self):
        """Links with /docs/default-source/ but without sfdownloadLink class are still found."""
        html = """
        <table class="rgMasterTable"><tbody>
          <tr>
            <td>Report</td>
            <td><a href="/docs/default-source/reports/report.pdf?sfvrsn=1">DL</a></td>
          </tr>
        </tbody></table>
        """
        items = _extract_publications(html, PUBS_URL)
        assert len(items) == 1
        assert "/docs/default-source/" in items[0]["href"]


# ---------------------------------------------------------------------------
# _get_next_page_url — Path-based pagination
# ---------------------------------------------------------------------------


class TestGetNextPageUrl:
    def test_page_1_finds_page_2(self):
        html = _read("listing_berita.html")
        url = _get_next_page_url(html, 1)
        assert url is not None
        assert "/page/2" in url

    def test_page_2_finds_page_3(self):
        html = _read("listing_berita.html")
        url = _get_next_page_url(html, 2)
        assert url is not None
        assert "/page/3" in url

    def test_last_page_returns_none(self):
        html = _read("listing_last_page.html")
        url = _get_next_page_url(html, 3)
        assert url is None

    def test_no_pager_returns_none(self):
        html = _read("listing_empty.html")
        url = _get_next_page_url(html, 1)
        assert url is None

    def test_publications_page_1(self):
        html = _read("listing_publications.html")
        url = _get_next_page_url(html, 1)
        assert url is not None
        assert "/page/2" in url

    def test_publications_no_page_3(self):
        html = _read("listing_publications.html")
        url = _get_next_page_url(html, 2)
        assert url is None


# ---------------------------------------------------------------------------
# _extract_article_meta — Article detail extraction
# ---------------------------------------------------------------------------


class TestExtractArticleMeta:
    def test_title_from_h1_sfnewstitle(self):
        html = _read("detail_article.html")
        meta = _extract_article_meta(html, DETAIL_URL)
        assert "Rompakan" in meta["title"]

    def test_published_at_from_url(self):
        html = _read("detail_article.html")
        meta = _extract_article_meta(html, DETAIL_URL)
        assert meta["published_at"] == "2026-03-09"

    def test_og_title_fallback(self):
        html = """
        <html><head>
          <meta property="og:title" content="OG Title Test">
        </head><body></body></html>
        """
        meta = _extract_article_meta(html, "https://www.rmp.gov.my/foo")
        assert meta["title"] == "OG Title Test"

    def test_title_tag_fallback_strips_suffix(self):
        html = """
        <html><head>
          <title>Article Title | Polis DiRaja Malaysia</title>
        </head><body></body></html>
        """
        meta = _extract_article_meta(html, "https://www.rmp.gov.my/foo")
        assert meta["title"] == "Article Title"

    def test_no_date_in_url_falls_back_to_sfnewsdate(self):
        html = """
        <html><body>
          <h1 class="sfnewsTitle">Test Article</h1>
          <div class="sfnewsMetaInfo">
            <ul><li class="sfnewsDate">15 January 2026</li></ul>
          </div>
        </body></html>
        """
        meta = _extract_article_meta(html, "https://www.rmp.gov.my/no-date-in-url")
        assert meta["published_at"] == "2026-01-15"

    def test_article_published_time_meta_fallback(self):
        html = """
        <html><head>
          <meta property="article:published_time" content="2026-02-10T00:00:00+08:00">
        </head><body>
          <h1 class="sfnewsTitle">Test</h1>
        </body></html>
        """
        meta = _extract_article_meta(html, "https://www.rmp.gov.my/no-date")
        assert meta["published_at"] == "2026-02-10"

    def test_time_element_fallback(self):
        html = """
        <html><body>
          <h1 class="sfnewsTitle">Test</h1>
          <time datetime="2025-11-20">20 November 2025</time>
        </body></html>
        """
        meta = _extract_article_meta(html, "https://www.rmp.gov.my/no-date")
        assert meta["published_at"] == "2025-11-20"

    def test_no_date_returns_empty(self):
        html = "<html><head></head><body><h1 class='sfnewsTitle'>No date</h1></body></html>"
        meta = _extract_article_meta(html, "https://www.rmp.gov.my/no-date-anywhere")
        assert meta["published_at"] == ""


# ---------------------------------------------------------------------------
# _extract_embedded_doc_links — Document discovery inside article body
# ---------------------------------------------------------------------------


class TestExtractEmbeddedDocLinks:
    def test_finds_pdf_and_docx(self):
        html = _read("detail_article.html")
        links = _extract_embedded_doc_links(html, BASE_URL)
        assert len(links) == 2

    def test_pdf_url_is_absolute(self):
        html = _read("detail_article.html")
        links = _extract_embedded_doc_links(html, BASE_URL)
        pdf_links = [url for url in links if ".pdf" in url]
        assert len(pdf_links) == 1
        assert pdf_links[0].startswith("https://www.rmp.gov.my")

    def test_docx_url_present(self):
        html = _read("detail_article.html")
        links = _extract_embedded_doc_links(html, BASE_URL)
        docx_links = [url for url in links if ".docx" in url]
        assert len(docx_links) == 1

    def test_mailto_not_included(self):
        html = _read("detail_article.html")
        links = _extract_embedded_doc_links(html, BASE_URL)
        assert not any("mailto:" in url for url in links)

    def test_no_duplicates(self):
        html = """
        <html><body>
          <div class="sfnewsContent">
            <a href="/docs/default-source/file.pdf?sfvrsn=1">PDF 1</a>
            <a href="/docs/default-source/file.pdf?sfvrsn=1">PDF 1 again</a>
          </div>
        </body></html>
        """
        links = _extract_embedded_doc_links(html, BASE_URL)
        assert len(links) == 1

    def test_no_docs_returns_empty(self):
        html = "<html><body><p>No documents here.</p></body></html>"
        links = _extract_embedded_doc_links(html, BASE_URL)
        assert links == []

    def test_sfvrsn_preserved(self):
        html = """
        <html><body>
          <div class="sfnewsContent">
            <a href="/docs/default-source/file.pdf?sfvrsn=3">Download</a>
          </div>
        </body></html>
        """
        links = _extract_embedded_doc_links(html, BASE_URL)
        assert len(links) == 1
        assert "sfvrsn=3" in links[0]


# ---------------------------------------------------------------------------
# RmpAdapter.discover — since filtering
# ---------------------------------------------------------------------------


class TestAdapterDiscoverSinceFilter:
    def _make_adapter(self, responses: dict[str, str]) -> RmpAdapter:
        """Create an adapter with mocked HTTP that returns fixture HTML for URLs."""
        mock_http = MagicMock()

        def side_effect(url):
            resp = MagicMock()
            resp.text = responses.get(url, "")
            return resp

        mock_http.get.side_effect = side_effect

        config = {
            "sections": [
                {
                    "name": "berita",
                    "listing_url": LISTING_URL,
                    "source_type": "listing",
                    "doc_type": "press_release",
                    "language": "ms",
                },
            ],
        }
        adapter = RmpAdapter(config=config, http=mock_http)
        return adapter

    def test_since_filters_old_items(self):
        """Items published before --since date are excluded."""
        html = _read("listing_berita.html")
        adapter = self._make_adapter({LISTING_URL: html})

        # All items are from March 2026; filter at 2026-03-08 should drop items before that
        items = list(adapter.discover(since=date(2026, 3, 8)))
        # Only the item from 2026-03-09 should pass (05 Mac and 07 March are before 08)
        urls = [i.source_url for i in items]
        assert any("2026/03/09" in url for url in urls)
        assert not any("2026/03/05" in url for url in urls)
        assert not any("2026/03/07" in url for url in urls)

    def test_since_none_returns_all(self):
        """Without --since, all items are returned."""
        html = _read("listing_berita.html")
        adapter = self._make_adapter({LISTING_URL: html})
        items = list(adapter.discover(since=None))
        assert len(items) == 3


# ---------------------------------------------------------------------------
# RmpAdapter.discover — max_pages
# ---------------------------------------------------------------------------


class TestAdapterDiscoverMaxPages:
    def _make_adapter(self, responses: dict[str, str]) -> RmpAdapter:
        mock_http = MagicMock()

        def side_effect(url):
            resp = MagicMock()
            resp.text = responses.get(url, "<html></html>")
            return resp

        mock_http.get.side_effect = side_effect

        config = {
            "sections": [
                {
                    "name": "berita",
                    "listing_url": LISTING_URL,
                    "source_type": "listing",
                    "doc_type": "press_release",
                    "language": "ms",
                },
            ],
        }
        return RmpAdapter(config=config, http=mock_http)

    def test_max_pages_limits_fetches(self):
        """max_pages=1 stops after one page even if more pages exist."""
        html = _read("listing_berita.html")
        adapter = self._make_adapter({LISTING_URL: html})
        items = list(adapter.discover(max_pages=1))
        # Should get 3 items from the single page
        assert len(items) == 3
        # HTTP get should be called only once
        assert adapter.http.get.call_count == 1


# ---------------------------------------------------------------------------
# RmpAdapter.fetch_and_extract — article page
# ---------------------------------------------------------------------------


class TestAdapterFetchAndExtract:
    def test_article_yields_html_plus_embedded_docs(self):
        """An article page yields the HTML itself plus embedded PDF/DOCX."""
        html = _read("detail_article.html")
        mock_http = MagicMock()
        resp = MagicMock()
        resp.text = html
        mock_http.get.return_value = resp

        adapter = RmpAdapter(config={}, http=mock_http)
        item = DiscoveredItem(
            source_url=DETAIL_URL,
            title="Test Article",
            published_at="2026-03-09",
            doc_type="press_release",
            language="ms",
            metadata={"listing_page_url": LISTING_URL, "source_type": "listing"},
        )
        candidates = list(adapter.fetch_and_extract(item))
        # 1 HTML + 2 embedded docs = 3 candidates
        assert len(candidates) == 3
        assert candidates[0].content_type == "text/html"
        assert any(c.content_type == "application/pdf" for c in candidates)

    def test_direct_file_yields_single_candidate(self):
        """A publication item with _direct_file yields one candidate without HTTP fetch."""
        mock_http = MagicMock()
        adapter = RmpAdapter(config={}, http=mock_http)
        item = DiscoveredItem(
            source_url="https://www.rmp.gov.my/docs/default-source/Penerbitan/report.pdf?sfvrsn=1",
            title="Annual Report",
            published_at="",
            doc_type="report",
            language="ms",
            metadata={"_direct_file": True, "listing_page_url": PUBS_URL},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert len(candidates) == 1
        assert candidates[0].content_type == "application/pdf"
        mock_http.get.assert_not_called()

    def test_pdf_url_from_listing_yields_single_candidate(self):
        """A listing item that is itself a PDF URL yields one candidate."""
        mock_http = MagicMock()
        adapter = RmpAdapter(config={}, http=mock_http)
        item = DiscoveredItem(
            source_url="https://www.rmp.gov.my/docs/default-source/media/statement.pdf",
            title="Media Statement",
            published_at="2025-01-01",
            doc_type="statement",
            language="ms",
            metadata={},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert len(candidates) == 1
        assert candidates[0].content_type == "application/pdf"
        mock_http.get.assert_not_called()


# ---------------------------------------------------------------------------
# RmpAdapter.extract_downloads — Sitefinity-aware extraction
# ---------------------------------------------------------------------------


class TestAdapterExtractDownloads:
    def test_sfdownloadlink_detected(self):
        adapter = RmpAdapter(config={}, http=MagicMock())
        html = """
        <html><body>
          <a class="sfdownloadLink" href="/docs/default-source/report.pdf?sfvrsn=1">Download</a>
        </body></html>
        """
        links = adapter.extract_downloads(html, BASE_URL)
        assert any("/docs/default-source/report.pdf" in dl.url for dl in links)

    def test_docs_default_source_pattern(self):
        adapter = RmpAdapter(config={}, http=MagicMock())
        html = """
        <html><body>
          <a href="/docs/default-source/files/document.docx">Download</a>
        </body></html>
        """
        links = adapter.extract_downloads(html, BASE_URL)
        assert any("document.docx" in dl.url for dl in links)
