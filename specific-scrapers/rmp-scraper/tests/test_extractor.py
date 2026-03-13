"""
Tests for RMP HTML extractors: listing, publications, pagination, detail, embedded docs.
"""
from pathlib import Path

import pytest

from rmp_scraper.extractor import (
    extract_embedded_doc_links,
    extract_rmp_article_meta,
    extract_sitefinity_listing_items,
    extract_sitefinity_publications,
    get_next_page_url,
    has_more_pages,
)

FIXTURES = Path(__file__).parent / "fixtures"

LISTING_URL = "https://www.rmp.gov.my/arkib-berita/berita"
PUBS_URL = "https://www.rmp.gov.my/laman-utama/penerbitan"
BASE_URL = "https://www.rmp.gov.my"
DETAIL_URL = "https://www.rmp.gov.my/arkib-berita/berita/2026/03/09/pdrm-tangkap-suspek"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── extract_sitefinity_listing_items ──────────────────────────────────────────


class TestExtractSitefinityListingItems:
    def test_returns_three_items(self):
        html = _read("listing_berita.html")
        items = extract_sitefinity_listing_items(html, LISTING_URL)
        assert len(items) == 3

    def test_first_item_title(self):
        html = _read("listing_berita.html")
        items = extract_sitefinity_listing_items(html, LISTING_URL)
        assert "Rompakan" in items[0]["title"]

    def test_first_item_href(self):
        html = _read("listing_berita.html")
        items = extract_sitefinity_listing_items(html, LISTING_URL)
        assert items[0]["href"] == "/arkib-berita/berita/2026/03/09/pdrm-tangkap-suspek-rompakan"

    def test_first_item_date_text(self):
        html = _read("listing_berita.html")
        items = extract_sitefinity_listing_items(html, LISTING_URL)
        assert items[0]["date_text"] == "09 March 2026"

    def test_malay_date_text_preserved(self):
        html = _read("listing_berita.html")
        items = extract_sitefinity_listing_items(html, LISTING_URL)
        # Third item uses "Mac" (Malay for March)
        assert items[2]["date_text"] == "05 Mac 2026"

    def test_source_url_preserved(self):
        html = _read("listing_berita.html")
        items = extract_sitefinity_listing_items(html, LISTING_URL)
        assert all(item["source_url"] == LISTING_URL for item in items)

    def test_empty_page_returns_empty(self):
        html = _read("listing_empty.html")
        items = extract_sitefinity_listing_items(html, LISTING_URL)
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
        items = extract_sitefinity_listing_items(html, LISTING_URL)
        assert len(items) == 1

    def test_skips_javascript_hrefs(self):
        html = """
        <div class="sfnewsItem">
          <h2><a data-sf-field="Title" href="javascript:void(0)">JS Link</a></h2>
        </div>
        <div class="sfnewsItem">
          <h2><a data-sf-field="Title" href="/real-article">Real</a></h2>
        </div>
        """
        items = extract_sitefinity_listing_items(html, LISTING_URL)
        assert len(items) == 1
        assert items[0]["href"] == "/real-article"

    def test_last_page_returns_one_item(self):
        html = _read("listing_last_page.html")
        items = extract_sitefinity_listing_items(html, LISTING_URL)
        assert len(items) == 1


# ── extract_sitefinity_publications ──────────────────────────────────────────


class TestExtractSitefinityPublications:
    def test_returns_three_items(self):
        html = _read("listing_publications.html")
        items = extract_sitefinity_publications(html, PUBS_URL)
        assert len(items) == 3

    def test_first_item_title(self):
        html = _read("listing_publications.html")
        items = extract_sitefinity_publications(html, PUBS_URL)
        assert "Berita Bukit Aman" in items[0]["title"]

    def test_first_item_href_contains_pdf(self):
        html = _read("listing_publications.html")
        items = extract_sitefinity_publications(html, PUBS_URL)
        assert ".pdf" in items[0]["href"].lower()

    def test_docx_item_detected(self):
        html = _read("listing_publications.html")
        items = extract_sitefinity_publications(html, PUBS_URL)
        docx_items = [i for i in items if ".docx" in i["href"].lower()]
        assert len(docx_items) == 1

    def test_sfvrsn_preserved_in_href(self):
        html = _read("listing_publications.html")
        items = extract_sitefinity_publications(html, PUBS_URL)
        assert "sfvrsn" in items[0]["href"]

    def test_no_table_returns_empty(self):
        html = "<html><body><p>No table</p></body></html>"
        items = extract_sitefinity_publications(html, PUBS_URL)
        assert items == []

    def test_no_duplicates(self):
        html = """
        <table class="rgMasterTable">
          <tbody>
            <tr class="sfpdf">
              <td>Doc A</td>
              <td><a class="sfdownloadLink" href="/docs/a.pdf?sfvrsn=1">Download</a></td>
            </tr>
            <tr class="sfpdf">
              <td>Doc A Again</td>
              <td><a class="sfdownloadLink" href="/docs/a.pdf?sfvrsn=1">Download</a></td>
            </tr>
          </tbody>
        </table>
        """
        items = extract_sitefinity_publications(html, PUBS_URL)
        assert len(items) == 1

    def test_source_url_preserved(self):
        html = _read("listing_publications.html")
        items = extract_sitefinity_publications(html, PUBS_URL)
        assert all(item["source_url"] == PUBS_URL for item in items)


# ── has_more_pages / get_next_page_url ───────────────────────────────────────


class TestPagination:
    def test_has_more_pages_page_1(self):
        html = _read("listing_berita.html")
        assert has_more_pages(html, 1) is True

    def test_has_more_pages_page_2(self):
        html = _read("listing_berita.html")
        # Page 3 link exists in fixture
        assert has_more_pages(html, 2) is True

    def test_no_more_pages_on_last_page(self):
        html = _read("listing_last_page.html")
        # On page 3, no page 4 link
        assert has_more_pages(html, 3) is False

    def test_no_pager_returns_false(self):
        html = _read("listing_empty.html")
        assert has_more_pages(html, 1) is False

    def test_get_next_page_url_page_1(self):
        html = _read("listing_berita.html")
        url = get_next_page_url(html, LISTING_URL, 1)
        assert url is not None
        assert "/page/2" in url

    def test_get_next_page_url_page_2(self):
        html = _read("listing_berita.html")
        url = get_next_page_url(html, LISTING_URL, 2)
        assert url is not None
        assert "/page/3" in url

    def test_get_next_page_url_last(self):
        html = _read("listing_last_page.html")
        url = get_next_page_url(html, LISTING_URL, 3)
        assert url is None

    def test_publications_pager(self):
        html = _read("listing_publications.html")
        assert has_more_pages(html, 1) is True
        assert has_more_pages(html, 2) is False


# ── extract_rmp_article_meta ──────────────────────────────────────────────────


class TestExtractRmpArticleMeta:
    def test_title_from_h1_sfnewstitle(self):
        html = _read("detail_article.html")
        meta = extract_rmp_article_meta(html, DETAIL_URL)
        assert "Rompakan" in meta["title"]

    def test_published_at_from_url(self):
        html = _read("detail_article.html")
        meta = extract_rmp_article_meta(html, DETAIL_URL)
        assert meta["published_at"] == "2026-03-09"

    def test_og_title_fallback(self):
        html = """
        <html><head>
          <meta property="og:title" content="OG Title Test">
        </head><body><p>No h1</p></body></html>
        """
        meta = extract_rmp_article_meta(html, "https://www.rmp.gov.my/foo")
        assert meta["title"] == "OG Title Test"

    def test_title_tag_fallback_strips_suffix(self):
        html = """
        <html><head>
          <title>Article Title | Polis DiRaja Malaysia</title>
        </head><body></body></html>
        """
        meta = extract_rmp_article_meta(html, "https://www.rmp.gov.my/foo")
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
        meta = extract_rmp_article_meta(html, "https://www.rmp.gov.my/no-date-in-url")
        assert meta["published_at"] == "2026-01-15"

    def test_article_published_time_meta_fallback(self):
        html = """
        <html><head>
          <meta property="article:published_time" content="2026-02-10T00:00:00+08:00">
        </head><body>
          <h1 class="sfnewsTitle">Test</h1>
        </body></html>
        """
        meta = extract_rmp_article_meta(html, "https://www.rmp.gov.my/no-date")
        assert meta["published_at"] == "2026-02-10"

    def test_no_date_returns_empty(self):
        html = "<html><head></head><body><h1 class='sfnewsTitle'>No date</h1></body></html>"
        meta = extract_rmp_article_meta(html, "https://www.rmp.gov.my/no-date-anywhere")
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
        pdf_links = [l for l in links if l.endswith(".pdf") or ".pdf?" in l]
        assert len(pdf_links) == 1
        assert pdf_links[0].startswith("https://www.rmp.gov.my")

    def test_docx_url_present(self):
        html = _read("detail_article.html")
        links = extract_embedded_doc_links(html, BASE_URL)
        docx_links = [l for l in links if ".docx" in l]
        assert len(docx_links) == 1

    def test_mailto_not_included(self):
        html = _read("detail_article.html")
        links = extract_embedded_doc_links(html, BASE_URL)
        assert not any("mailto:" in l for l in links)

    def test_no_duplicates(self):
        html = """
        <html><body>
          <div class="sfnewsContent">
            <a href="/docs/default-source/file.pdf?sfvrsn=1">PDF 1</a>
            <a href="/docs/default-source/file.pdf?sfvrsn=1">PDF 1 again</a>
          </div>
        </body></html>
        """
        links = extract_embedded_doc_links(html, BASE_URL)
        assert len(links) == 1

    def test_no_docs_returns_empty(self):
        html = "<html><body><p>No documents here.</p></body></html>"
        links = extract_embedded_doc_links(html, BASE_URL)
        assert links == []

    def test_sfvrsn_preserved(self):
        html = """
        <html><body>
          <div class="sfnewsContent">
            <a href="/docs/default-source/file.pdf?sfvrsn=3">Download</a>
          </div>
        </body></html>
        """
        links = extract_embedded_doc_links(html, BASE_URL)
        assert len(links) == 1
        assert "sfvrsn=3" in links[0]
