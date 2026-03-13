"""
Tests for MOH HTML extractors: listing, pagination, detail page, embedded docs.
"""
from pathlib import Path

import pytest

from moh_scraper.extractor import (
    extract_embedded_doc_links,
    extract_joomla_listing_items,
    extract_moh_article_meta,
    has_more_pages,
)

FIXTURES = Path(__file__).parent / "fixtures"

SOURCE_URL = "https://www.moh.gov.my/en/media-kkm/media-statement/2026"
BASE_URL = "https://www.moh.gov.my"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── extract_joomla_listing_items ─────────────────────────────────────────────


class TestExtractJoomlaListingItems:
    def test_returns_two_items(self):
        html = _read("listing_media_statements.html")
        items = extract_joomla_listing_items(html, SOURCE_URL)
        assert len(items) == 2

    def test_first_item_title(self):
        html = _read("listing_media_statements.html")
        items = extract_joomla_listing_items(html, SOURCE_URL)
        assert "Pertama" in items[0]["title"]

    def test_first_item_href(self):
        html = _read("listing_media_statements.html")
        items = extract_joomla_listing_items(html, SOURCE_URL)
        assert items[0]["href"] == "/en/media-kkm/media-statement/2026/kenyataan-media-1"

    def test_first_item_date_text(self):
        html = _read("listing_media_statements.html")
        items = extract_joomla_listing_items(html, SOURCE_URL)
        assert items[0]["date_text"] == "23-02-2026"

    def test_second_item_date(self):
        html = _read("listing_media_statements.html")
        items = extract_joomla_listing_items(html, SOURCE_URL)
        assert items[1]["date_text"] == "20-02-2026"

    def test_source_url_preserved(self):
        html = _read("listing_media_statements.html")
        items = extract_joomla_listing_items(html, SOURCE_URL)
        assert all(item["source_url"] == SOURCE_URL for item in items)

    def test_empty_tbody_returns_empty(self):
        html = _read("listing_empty.html")
        items = extract_joomla_listing_items(html, SOURCE_URL)
        assert items == []

    def test_no_table_returns_empty(self):
        items = extract_joomla_listing_items("<html><body>No table here</body></html>", SOURCE_URL)
        assert items == []

    def test_last_page_has_one_item(self):
        html = _read("listing_last_page.html")
        items = extract_joomla_listing_items(html, SOURCE_URL)
        assert len(items) == 1

    def test_deduplicates_hrefs(self):
        # Manually create HTML with duplicate href
        html = """
        <table class="com-content-category__table category">
          <tbody>
            <tr><td class="list-title"><a href="/en/dup">Title A</a></td><td class="list-date small">01-01-2026</td></tr>
            <tr><td class="list-title"><a href="/en/dup">Title B</a></td><td class="list-date small">02-01-2026</td></tr>
          </tbody>
        </table>
        """
        items = extract_joomla_listing_items(html, SOURCE_URL)
        assert len(items) == 1


# ── has_more_pages ────────────────────────────────────────────────────────────


class TestHasMorePages:
    def test_more_pages_at_offset_0(self):
        html = _read("listing_media_statements.html")
        # Listing has links for start=10 and start=20 → more pages after offset 0
        assert has_more_pages(html, 0) is True

    def test_more_pages_at_offset_10(self):
        html = _read("listing_media_statements.html")
        # start=20 still exists → more pages after offset 10
        assert has_more_pages(html, 10) is True

    def test_no_more_pages_at_last_offset(self):
        html = _read("listing_last_page.html")
        # Pagination only shows start=10 (current) and start=0 (page 1) → done
        assert has_more_pages(html, 10) is False

    def test_no_pagination_widget_returns_false(self):
        html = _read("listing_empty.html")
        assert has_more_pages(html, 0) is False


# ── extract_moh_article_meta ─────────────────────────────────────────────────


class TestExtractMohArticleMeta:
    def test_title_from_h1_itemprop(self):
        html = _read("detail_article.html")
        meta = extract_moh_article_meta(html, SOURCE_URL)
        assert meta["title"] == "Kenyataan Media Test"

    def test_published_at_from_time_itemprop(self):
        html = _read("detail_article.html")
        meta = extract_moh_article_meta(html, SOURCE_URL)
        assert meta["published_at"] == "2026-02-23"

    def test_og_title_fallback(self):
        html = """
        <html><head>
          <meta property="og:title" content="OG Title Fallback">
        </head><body><article><p>No h1 here</p></article></body></html>
        """
        meta = extract_moh_article_meta(html, SOURCE_URL)
        assert meta["title"] == "OG Title Fallback"

    def test_title_tag_fallback(self):
        html = """
        <html><head>
          <title>Title Tag Article | Kementerian Kesihatan Malaysia</title>
        </head><body></body></html>
        """
        meta = extract_moh_article_meta(html, SOURCE_URL)
        assert meta["title"] == "Title Tag Article"

    def test_article_published_time_meta_fallback(self):
        html = """
        <html><head>
          <meta property="article:published_time" content="2026-01-15T00:00:00+08:00">
        </head><body>
          <article><h1 itemprop="headline">Test</h1></article>
        </body></html>
        """
        meta = extract_moh_article_meta(html, SOURCE_URL)
        assert meta["published_at"] == "2026-01-15"

    def test_no_date_returns_empty_string(self):
        html = "<html><head></head><body><article><h1 itemprop='headline'>X</h1></article></body></html>"
        meta = extract_moh_article_meta(html, SOURCE_URL)
        assert meta["published_at"] == ""


# ── extract_embedded_doc_links ────────────────────────────────────────────────


class TestExtractEmbeddedDocLinks:
    def test_finds_pdf_and_docx(self):
        html = _read("detail_article.html")
        links = extract_embedded_doc_links(html, BASE_URL)
        assert len(links) == 2

    def test_pdf_url_is_absolute(self):
        html = _read("detail_article.html")
        links = extract_embedded_doc_links(html, BASE_URL)
        pdf_links = [l for l in links if l.endswith(".pdf")]
        assert len(pdf_links) == 1
        assert pdf_links[0].startswith("https://www.moh.gov.my")

    def test_docx_url_present(self):
        html = _read("detail_article.html")
        links = extract_embedded_doc_links(html, BASE_URL)
        docx_links = [l for l in links if l.endswith(".docx")]
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
        links = extract_embedded_doc_links(html, BASE_URL)
        assert len(links) == 1

    def test_mailto_not_included(self):
        html = _read("detail_article.html")
        links = extract_embedded_doc_links(html, BASE_URL)
        assert not any("mailto:" in l for l in links)

    def test_no_docs_returns_empty(self):
        html = "<html><body><p>No documents here.</p></body></html>"
        links = extract_embedded_doc_links(html, BASE_URL)
        assert links == []
