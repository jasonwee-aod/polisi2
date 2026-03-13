"""Tests for the MOHE adapter — RSS feeds, DOCman tables, article extraction.

Covers:
  - RSS feed parsing (XML)
  - DOCman table extraction (k-js-documents-table)
  - DOCman /file endpoint handling
  - Bilingual feed support (EN/MS)
  - Date parsing from RSS
  - Date parsing from DOCman
  - since filtering
  - Article detail extraction
  - Embedded doc links
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from polisi_scraper.adapters.mohe import (
    MoheAdapter,
    _extract_article_meta,
    _extract_docman_items,
    _is_docman_file_url,
    _parse_rss_date,
    _parse_rss_feed,
)
from polisi_scraper.adapters.base import DiscoveredItem, DocumentCandidate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "mohe"
_BASE_URL = "https://www.mohe.gov.my"


# ---------------------------------------------------------------------------
# Sample RSS XML fixtures (inline, since fixture dir is empty)
# ---------------------------------------------------------------------------


SAMPLE_RSS_EN = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>MOHE Announcements</title>
    <link>https://www.mohe.gov.my/en/broadcast/announcements</link>
    <item>
      <title>New Higher Education Framework</title>
      <link>https://www.mohe.gov.my/en/broadcast/announcements/article-001</link>
      <description>The Ministry announced the new framework.</description>
      <pubDate>Thu, 27 Feb 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Scholarship Program Extended</title>
      <link>https://www.mohe.gov.my/en/broadcast/announcements/article-002</link>
      <description>The government scholarship program extended.</description>
      <pubDate>Wed, 26 Feb 2026 15:30:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""

SAMPLE_RSS_MS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>KPT Pengumuman</title>
    <link>https://www.mohe.gov.my/hebahan/pengumuman</link>
    <item>
      <title>Kerangka Pendidikan Tinggi Baru</title>
      <link>https://www.mohe.gov.my/hebahan/pengumuman/article-001</link>
      <description>Kementerian mengumumkan kerangka baru.</description>
      <pubDate>27 Februari 2026 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""

SAMPLE_RSS_NO_LINK = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>No Link Item</title><description>No link.</description></item>
  <item><title>Valid Item</title><link>https://mohe.gov.my/test</link></item>
</channel></rss>"""

SAMPLE_RSS_EMPTY = """<?xml version="1.0"?>
<rss version="2.0"><channel></channel></rss>"""

SAMPLE_RSS_MALFORMED = """<not-xml!!!"""

SAMPLE_DOCMAN_HTML = """<!DOCTYPE html>
<html lang="ms">
<head><meta charset="UTF-8"><title>Arahan Pentadbiran - MOHE</title></head>
<body>
  <div class="k-component k-js-documents-list">
    <table class="k-js-documents-table">
      <thead>
        <tr><th>Tajuk</th><th>Tarikh</th><th>Saiz</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>
            <a href="/warga/muat-turun/pekeliling/arahan-pentadbiran/1715-arahan-bil-1-2024/file">
              Arahan Pentadbiran Bil. 1 Tahun 2024
            </a>
          </td>
          <td>15 Januari 2024</td>
          <td>245 KB</td>
        </tr>
        <tr>
          <td>
            <a href="/warga/muat-turun/pekeliling/arahan-pentadbiran/1601-arahan-bil-2-2023/file">
              Arahan Pentadbiran Bil. 2 Tahun 2023
            </a>
          </td>
          <td>20 Mac 2023</td>
          <td>189 KB</td>
        </tr>
        <tr>
          <td>
            <a href="/warga/muat-turun/pekeliling/arahan-pentadbiran/1600-arahan-bil-1-2023/file">
              Arahan Pentadbiran Bil. 1 Tahun 2023
            </a>
          </td>
          <td>05 Februari 2023</td>
          <td>312 KB</td>
        </tr>
      </tbody>
    </table>
  </div>
</body>
</html>"""

SAMPLE_DOCMAN_HTML_EMPTY = """<!DOCTYPE html>
<html lang="ms"><body>
  <table class="k-js-documents-table">
    <thead><tr><th>Tajuk</th><th>Tarikh</th></tr></thead>
    <tbody></tbody>
  </table>
</body></html>"""

SAMPLE_DOCMAN_NO_TABLE = """<!DOCTYPE html>
<html lang="ms"><body><p>Tiada dokumen ditemui.</p></body></html>"""

SAMPLE_ARTICLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta property="og:title" content="New Higher Education Framework">
</head>
<body>
  <article>
    <h1 itemprop="headline">New Higher Education Framework</h1>
    <time itemprop="datePublished" datetime="2026-02-27">27 February 2026</time>
    <div itemprop="articleBody">
      <p>The Ministry has announced a new framework.</p>
      <p>Download the full document:
        <a href="/media/attachments/framework-2026.pdf">Framework PDF</a>
      </p>
      <p>Related circular:
        <a href="/warga/muat-turun/pekeliling/circular-001/file">Circular 001</a>
      </p>
    </div>
  </article>
</body>
</html>"""


# ---------------------------------------------------------------------------
# _parse_rss_feed — RSS XML parsing
# ---------------------------------------------------------------------------


class TestParseRssFeed:
    def test_parse_basic_rss(self):
        items = _parse_rss_feed(SAMPLE_RSS_EN)
        assert len(items) == 2

    def test_first_item_title(self):
        items = _parse_rss_feed(SAMPLE_RSS_EN)
        assert items[0]["title"] == "New Higher Education Framework"

    def test_first_item_link(self):
        items = _parse_rss_feed(SAMPLE_RSS_EN)
        assert items[0]["link"] == "https://www.mohe.gov.my/en/broadcast/announcements/article-001"

    def test_first_item_pub_date(self):
        items = _parse_rss_feed(SAMPLE_RSS_EN)
        assert "27 Feb 2026" in items[0]["pub_date"]

    def test_first_item_description(self):
        items = _parse_rss_feed(SAMPLE_RSS_EN)
        assert "framework" in items[0]["description"].lower()

    def test_multiple_items(self):
        items = _parse_rss_feed(SAMPLE_RSS_EN)
        assert len(items) == 2
        assert items[1]["title"] == "Scholarship Program Extended"

    def test_missing_link_skipped(self):
        items = _parse_rss_feed(SAMPLE_RSS_NO_LINK)
        assert len(items) == 1
        assert items[0]["title"] == "Valid Item"

    def test_empty_feed(self):
        items = _parse_rss_feed(SAMPLE_RSS_EMPTY)
        assert items == []

    def test_malformed_xml(self):
        items = _parse_rss_feed(SAMPLE_RSS_MALFORMED)
        assert items == []

    def test_malay_rss_feed(self):
        items = _parse_rss_feed(SAMPLE_RSS_MS)
        assert len(items) == 1
        assert items[0]["title"] == "Kerangka Pendidikan Tinggi Baru"

    def test_malay_pubdate_preserved(self):
        items = _parse_rss_feed(SAMPLE_RSS_MS)
        assert "Februari" in items[0]["pub_date"]

    def test_untitled_item_gets_default(self):
        rss = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item><link>https://mohe.gov.my/test</link></item>
        </channel></rss>"""
        items = _parse_rss_feed(rss)
        assert len(items) == 1
        assert items[0]["title"] == "Untitled"


# ---------------------------------------------------------------------------
# _parse_rss_date — RSS date to ISO conversion
# ---------------------------------------------------------------------------


class TestParseRssDate:
    def test_rfc2822_format(self):
        result = _parse_rss_date("Thu, 27 Feb 2026 10:00:00 GMT")
        assert result == "2026-02-27"

    def test_malay_date_format(self):
        result = _parse_rss_date("27 Februari 2026 10:00:00 GMT")
        assert result == "2026-02-27"

    def test_iso_date_passthrough(self):
        result = _parse_rss_date("2026-02-27")
        assert result == "2026-02-27"

    def test_empty_returns_empty(self):
        result = _parse_rss_date("")
        assert result == ""

    def test_whitespace_returns_empty(self):
        result = _parse_rss_date("   ")
        assert result == ""

    def test_malay_mac_month(self):
        result = _parse_rss_date("1 Mac 2026")
        assert result == "2026-03-01"


# ---------------------------------------------------------------------------
# _extract_docman_items — DOCman table extraction
# ---------------------------------------------------------------------------


class TestExtractDocmanItems:
    def test_returns_correct_count(self):
        items = _extract_docman_items(SAMPLE_DOCMAN_HTML, _BASE_URL)
        assert len(items) == 3

    def test_title_extracted(self):
        items = _extract_docman_items(SAMPLE_DOCMAN_HTML, _BASE_URL)
        assert items[0]["title"] == "Arahan Pentadbiran Bil. 1 Tahun 2024"
        assert items[1]["title"] == "Arahan Pentadbiran Bil. 2 Tahun 2023"

    def test_href_ends_with_file(self):
        items = _extract_docman_items(SAMPLE_DOCMAN_HTML, _BASE_URL)
        for item in items:
            assert item["href"].rstrip("/").endswith("/file")

    def test_date_extracted(self):
        items = _extract_docman_items(SAMPLE_DOCMAN_HTML, _BASE_URL)
        assert items[0]["date_text"] == "15 Januari 2024"
        assert items[1]["date_text"] == "20 Mac 2023"
        assert items[2]["date_text"] == "05 Februari 2023"

    def test_source_url_preserved(self):
        items = _extract_docman_items(SAMPLE_DOCMAN_HTML, _BASE_URL)
        for item in items:
            assert item["source_url"] == _BASE_URL

    def test_empty_table_returns_empty(self):
        items = _extract_docman_items(SAMPLE_DOCMAN_HTML_EMPTY, _BASE_URL)
        assert items == []

    def test_no_table_returns_empty(self):
        items = _extract_docman_items(SAMPLE_DOCMAN_NO_TABLE, _BASE_URL)
        assert items == []

    def test_header_row_excluded(self):
        items = _extract_docman_items(SAMPLE_DOCMAN_HTML, _BASE_URL)
        titles = [item["title"] for item in items]
        assert "Tajuk" not in titles

    def test_row_without_file_link_excluded(self):
        html = """
        <table class="k-js-documents-table">
          <tbody>
            <tr>
              <td><a href="/some/page">Not a file link</a></td>
              <td>2024-01-01</td>
            </tr>
            <tr>
              <td><a href="/docs/123/file">Actual File</a></td>
              <td>2024-02-01</td>
            </tr>
          </tbody>
        </table>
        """
        items = _extract_docman_items(html, _BASE_URL)
        assert len(items) == 1
        assert items[0]["title"] == "Actual File"


# ---------------------------------------------------------------------------
# _is_docman_file_url
# ---------------------------------------------------------------------------


class TestIsDocmanFileUrl:
    def test_true_for_file_url(self):
        assert _is_docman_file_url("https://www.mohe.gov.my/warga/muat-turun/1715/file")

    def test_true_for_trailing_slash(self):
        assert _is_docman_file_url("https://www.mohe.gov.my/warga/muat-turun/1715/file/")

    def test_false_for_regular_url(self):
        assert not _is_docman_file_url("https://www.mohe.gov.my/en/broadcast/announcements")

    def test_false_for_pdf_url(self):
        assert not _is_docman_file_url("https://www.mohe.gov.my/media/report.pdf")


# ---------------------------------------------------------------------------
# _extract_article_meta — Joomla article page metadata
# ---------------------------------------------------------------------------


class TestExtractArticleMeta:
    def test_title_from_headline_itemprop(self):
        meta = _extract_article_meta(SAMPLE_ARTICLE_HTML)
        assert meta["title"] == "New Higher Education Framework"

    def test_published_at_from_time_itemprop(self):
        meta = _extract_article_meta(SAMPLE_ARTICLE_HTML)
        assert meta["published_at"] == "2026-02-27"

    def test_og_title_fallback(self):
        html = """
        <html><head>
          <meta property="og:title" content="OG Fallback Title">
        </head><body></body></html>
        """
        meta = _extract_article_meta(html)
        assert meta["title"] == "OG Fallback Title"

    def test_article_container_h1_fallback(self):
        html = """
        <html><body>
          <article><h1>Container Title</h1></article>
        </body></html>
        """
        meta = _extract_article_meta(html)
        assert meta["title"] == "Container Title"

    def test_article_published_time_meta_fallback(self):
        html = """
        <html><head>
          <meta property="article:published_time" content="2026-01-15T00:00:00+08:00">
        </head><body>
          <h1 itemprop="headline">Test</h1>
        </body></html>
        """
        meta = _extract_article_meta(html)
        assert meta["published_at"] == "2026-01-15"

    def test_no_date_returns_empty(self):
        html = "<html><body><p>No dates</p></body></html>"
        meta = _extract_article_meta(html)
        assert meta["published_at"] == ""

    def test_no_title_returns_empty(self):
        html = "<html><body><p>No titles</p></body></html>"
        meta = _extract_article_meta(html)
        assert meta["title"] == ""


# ---------------------------------------------------------------------------
# MoheAdapter._extract_article_doc_links — embedded doc extraction
# ---------------------------------------------------------------------------


class TestExtractArticleDocLinks:
    def test_finds_pdf_link(self):
        links = MoheAdapter._extract_article_doc_links(SAMPLE_ARTICLE_HTML, _BASE_URL)
        pdf_links = [dl for dl in links if dl.url.endswith(".pdf")]
        assert len(pdf_links) == 1

    def test_finds_docman_file_link(self):
        links = MoheAdapter._extract_article_doc_links(SAMPLE_ARTICLE_HTML, _BASE_URL)
        file_links = [dl for dl in links if dl.url.rstrip("/").endswith("/file")]
        assert len(file_links) == 1

    def test_total_links_count(self):
        links = MoheAdapter._extract_article_doc_links(SAMPLE_ARTICLE_HTML, _BASE_URL)
        assert len(links) == 2

    def test_links_are_absolute(self):
        links = MoheAdapter._extract_article_doc_links(SAMPLE_ARTICLE_HTML, _BASE_URL)
        for dl in links:
            assert dl.url.startswith("https://"), f"Relative URL: {dl.url}"

    def test_no_docs_returns_empty(self):
        html = "<html><body><p>No documents.</p></body></html>"
        links = MoheAdapter._extract_article_doc_links(html, _BASE_URL)
        assert links == []


# ---------------------------------------------------------------------------
# MoheAdapter.discover — RSS feed integration (mocked HTTP)
# ---------------------------------------------------------------------------


class TestAdapterDiscoverRss:
    def _make_adapter(self, feed_responses: dict[str, str]) -> MoheAdapter:
        mock_http = MagicMock()

        def side_effect(url):
            resp = MagicMock()
            resp.text = feed_responses.get(url, "")
            return resp

        mock_http.get.side_effect = side_effect

        config = {
            "rss_feeds": [
                {
                    "name": "announcements",
                    "url_en": "https://www.mohe.gov.my/en/broadcast/announcements?format=feed&type=rss",
                    "url_ms": "https://www.mohe.gov.my/hebahan/pengumuman?format=feed&type=rss",
                    "doc_type": "announcement",
                },
            ],
            "listing_pages": [],  # No DOCman pages for this test
        }
        return MoheAdapter(config=config, http=mock_http)

    def test_discovers_en_items(self):
        adapter = self._make_adapter({
            "https://www.mohe.gov.my/en/broadcast/announcements?format=feed&type=rss": SAMPLE_RSS_EN,
            "https://www.mohe.gov.my/hebahan/pengumuman?format=feed&type=rss": SAMPLE_RSS_EMPTY,
        })
        items = list(adapter.discover())
        en_items = [i for i in items if i.language == "en"]
        assert len(en_items) == 2

    def test_discovers_ms_items(self):
        adapter = self._make_adapter({
            "https://www.mohe.gov.my/en/broadcast/announcements?format=feed&type=rss": SAMPLE_RSS_EMPTY,
            "https://www.mohe.gov.my/hebahan/pengumuman?format=feed&type=rss": SAMPLE_RSS_MS,
        })
        items = list(adapter.discover())
        ms_items = [i for i in items if i.language == "ms"]
        assert len(ms_items) == 1

    def test_bilingual_both_languages(self):
        adapter = self._make_adapter({
            "https://www.mohe.gov.my/en/broadcast/announcements?format=feed&type=rss": SAMPLE_RSS_EN,
            "https://www.mohe.gov.my/hebahan/pengumuman?format=feed&type=rss": SAMPLE_RSS_MS,
        })
        items = list(adapter.discover())
        assert len(items) == 3  # 2 EN + 1 MS

    def test_doc_type_propagated(self):
        adapter = self._make_adapter({
            "https://www.mohe.gov.my/en/broadcast/announcements?format=feed&type=rss": SAMPLE_RSS_EN,
            "https://www.mohe.gov.my/hebahan/pengumuman?format=feed&type=rss": SAMPLE_RSS_EMPTY,
        })
        items = list(adapter.discover())
        for item in items:
            assert item.doc_type == "announcement"

    def test_published_at_parsed(self):
        adapter = self._make_adapter({
            "https://www.mohe.gov.my/en/broadcast/announcements?format=feed&type=rss": SAMPLE_RSS_EN,
            "https://www.mohe.gov.my/hebahan/pengumuman?format=feed&type=rss": SAMPLE_RSS_EMPTY,
        })
        items = list(adapter.discover())
        en_items = [i for i in items if i.language == "en"]
        assert en_items[0].published_at == "2026-02-27"

    def test_metadata_contains_feed_info(self):
        adapter = self._make_adapter({
            "https://www.mohe.gov.my/en/broadcast/announcements?format=feed&type=rss": SAMPLE_RSS_EN,
            "https://www.mohe.gov.my/hebahan/pengumuman?format=feed&type=rss": SAMPLE_RSS_EMPTY,
        })
        items = list(adapter.discover())
        en_items = [i for i in items if i.language == "en"]
        assert en_items[0].metadata["feed_name"] == "announcements"


# ---------------------------------------------------------------------------
# MoheAdapter.discover — since filtering
# ---------------------------------------------------------------------------


class TestAdapterDiscoverSince:
    def _make_adapter(self, feed_responses: dict[str, str]) -> MoheAdapter:
        mock_http = MagicMock()

        def side_effect(url):
            resp = MagicMock()
            resp.text = feed_responses.get(url, "")
            return resp

        mock_http.get.side_effect = side_effect

        config = {
            "rss_feeds": [
                {
                    "name": "announcements",
                    "url_en": "https://www.mohe.gov.my/en/feed",
                    "doc_type": "announcement",
                },
            ],
            "listing_pages": [],
        }
        return MoheAdapter(config=config, http=mock_http)

    def test_since_filters_old_items(self):
        adapter = self._make_adapter({
            "https://www.mohe.gov.my/en/feed": SAMPLE_RSS_EN,
        })
        # Both items are 2026-02-26 and 2026-02-27; filter at 2026-02-27
        items = list(adapter.discover(since=date(2026, 2, 27)))
        assert len(items) == 1
        assert items[0].published_at == "2026-02-27"

    def test_since_none_returns_all(self):
        adapter = self._make_adapter({
            "https://www.mohe.gov.my/en/feed": SAMPLE_RSS_EN,
        })
        items = list(adapter.discover(since=None))
        assert len(items) == 2


# ---------------------------------------------------------------------------
# MoheAdapter.discover — DOCman pages (mocked HTTP)
# ---------------------------------------------------------------------------


class TestAdapterDiscoverDocman:
    def _make_adapter(self, responses: dict[str, str]) -> MoheAdapter:
        mock_http = MagicMock()

        def side_effect(url):
            resp = MagicMock()
            resp.text = responses.get(url, "")
            return resp

        mock_http.get.side_effect = side_effect

        config = {
            "rss_feeds": [],
            "listing_pages": [
                {
                    "name": "circulars",
                    "url_ms": "https://www.mohe.gov.my/warga/muat-turun/pekeliling",
                    "doc_type": "circular",
                    "playwright_required": False,
                },
            ],
        }
        return MoheAdapter(config=config, http=mock_http)

    def test_discovers_docman_items(self):
        adapter = self._make_adapter({
            "https://www.mohe.gov.my/warga/muat-turun/pekeliling": SAMPLE_DOCMAN_HTML,
        })
        items = list(adapter.discover())
        assert len(items) == 3

    def test_docman_items_have_file_download_flag(self):
        adapter = self._make_adapter({
            "https://www.mohe.gov.my/warga/muat-turun/pekeliling": SAMPLE_DOCMAN_HTML,
        })
        items = list(adapter.discover())
        for item in items:
            assert item.metadata.get("is_file_download") is True

    def test_docman_max_pages(self):
        adapter = self._make_adapter({
            "https://www.mohe.gov.my/warga/muat-turun/pekeliling": SAMPLE_DOCMAN_HTML,
        })
        items = list(adapter.discover(max_pages=1))
        assert len(items) == 3
        assert adapter.http.get.call_count == 1

    def test_docman_since_filters(self):
        adapter = self._make_adapter({
            "https://www.mohe.gov.my/warga/muat-turun/pekeliling": SAMPLE_DOCMAN_HTML,
        })
        # Items: 2024-01-15, 2023-03-20, 2023-02-05; filter at 2024-01-01
        items = list(adapter.discover(since=date(2024, 1, 1)))
        assert len(items) == 1
        assert items[0].published_at == "2024-01-15"

    def test_playwright_required_skipped(self):
        """Pages marked playwright_required=True are skipped when browser not available."""
        mock_http = MagicMock()

        def side_effect(url):
            resp = MagicMock()
            resp.text = SAMPLE_DOCMAN_HTML
            return resp

        mock_http.get.side_effect = side_effect

        config = {
            "rss_feeds": [],
            "listing_pages": [
                {
                    "name": "forms",
                    "url_ms": "https://www.mohe.gov.my/warga/muat-turun/borang",
                    "doc_type": "form",
                    "playwright_required": True,
                },
            ],
        }
        adapter = MoheAdapter(config=config, http=mock_http)
        items = list(adapter.discover())
        assert items == []
        mock_http.get.assert_not_called()


# ---------------------------------------------------------------------------
# MoheAdapter.fetch_and_extract
# ---------------------------------------------------------------------------


class TestAdapterFetchAndExtract:
    def test_docman_file_yields_single_candidate(self):
        """DOCman /file URL yields one DocumentCandidate without HTTP fetch."""
        mock_http = MagicMock()
        adapter = MoheAdapter(config={}, http=mock_http)
        item = DiscoveredItem(
            source_url="https://www.mohe.gov.my/warga/muat-turun/pekeliling/1715/file",
            title="Arahan Pentadbiran Bil. 1",
            published_at="2024-01-15",
            doc_type="circular",
            language="ms",
            metadata={"is_file_download": True, "listing_url": _BASE_URL},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert len(candidates) == 1
        # DOCman /file without extension defaults to application/pdf
        assert candidates[0].content_type == "application/pdf"
        mock_http.get.assert_not_called()

    def test_pdf_url_yields_single_candidate(self):
        """Direct PDF URL yields one candidate without HTML fetch."""
        mock_http = MagicMock()
        adapter = MoheAdapter(config={}, http=mock_http)
        item = DiscoveredItem(
            source_url="https://www.mohe.gov.my/media/report.pdf",
            title="Annual Report",
            published_at="2025-01-01",
            doc_type="report",
            language="en",
            metadata={},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert len(candidates) == 1
        assert candidates[0].content_type == "application/pdf"
        mock_http.get.assert_not_called()

    def test_article_page_yields_html_plus_embedded(self):
        """An article page yields the HTML plus embedded doc links."""
        mock_http = MagicMock()
        resp = MagicMock()
        resp.text = SAMPLE_ARTICLE_HTML
        mock_http.get.return_value = resp

        adapter = MoheAdapter(config={}, http=mock_http)
        item = DiscoveredItem(
            source_url="https://www.mohe.gov.my/en/broadcast/announcements/article-001",
            title="New Framework",
            published_at="2026-02-27",
            doc_type="announcement",
            language="en",
            metadata={"feed_url": "https://www.mohe.gov.my/en/feed"},
        )
        candidates = list(adapter.fetch_and_extract(item))
        # 1 HTML page + 2 embedded docs (PDF + DOCman /file)
        assert len(candidates) == 3
        assert candidates[0].content_type == "text/html"
        assert candidates[0].title == "New Higher Education Framework"  # enriched from page

    def test_fetch_failure_yields_nothing(self):
        mock_http = MagicMock()
        mock_http.get.side_effect = Exception("Connection error")
        adapter = MoheAdapter(config={}, http=mock_http)
        item = DiscoveredItem(
            source_url="https://www.mohe.gov.my/en/broken-page",
            title="Broken",
            doc_type="other",
            language="en",
            metadata={},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates == []
