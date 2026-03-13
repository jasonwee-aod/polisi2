"""Tests for the Dewan Selangor unified adapter.

Covers:
  - Sitemap XML parsing (index + urlset, lastmod filtering)
  - WordPress listing page extraction + pagination
  - WordPress single post metadata extraction
  - pdfjs-viewer iframe extraction
  - Embedded document link extraction
  - 3-level Hansard hub navigation (index + session PDFs)
  - e-QUANS listing extraction + Bootstrap pagination
  - e-QUANS date range parsing
  - Hansard date parsing
  - since filtering
  - max_pages limiting
  - Empty pages
  - Adapter discover() integration via mocked HTTP
  - Adapter fetch_and_extract() for different page types
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from polisi_scraper.adapters.dewan_selangor import (
    DewanSelangorAdapter,
    _extract_embedded_doc_links,
    _extract_equans_listing,
    _extract_hansard_index,
    _extract_hansard_session_pdfs,
    _extract_wp_listing,
    _extract_wp_post_meta,
    _get_next_equans_page_url,
    _get_next_wp_listing_page_url,
    _parse_equans_date_range,
    _parse_hansard_date,
    _parse_sitemap_xml,
    _since_filter,
)
from polisi_scraper.adapters.base import DiscoveredItem

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "dewan_selangor"
BASE = "https://dewan.selangor.gov.my"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Sitemap XML parser
# ---------------------------------------------------------------------------

class TestParseSitemapXml:
    def test_sitemap_index_returns_child_sitemaps(self):
        xml = _read("sitemap_index.xml")
        entries = _parse_sitemap_xml(xml, f"{BASE}/sitemap_index.xml")
        assert len(entries) == 4
        assert all(e["is_sitemap_index"] for e in entries)

    def test_sitemap_index_urls(self):
        xml = _read("sitemap_index.xml")
        entries = _parse_sitemap_xml(xml, f"{BASE}/sitemap_index.xml")
        urls = [e["url"] for e in entries]
        assert f"{BASE}/post-sitemap.xml" in urls
        assert f"{BASE}/hansard-sitemap.xml" in urls

    def test_sitemap_index_lastmod_values(self):
        xml = _read("sitemap_index.xml")
        entries = _parse_sitemap_xml(xml, f"{BASE}/sitemap_index.xml")
        entry = next(e for e in entries if "post-sitemap" in e["url"])
        assert entry["lastmod"].startswith("2025-11-13")

    def test_urlset_sitemap_returns_article_urls(self):
        xml = _read("post_sitemap.xml")
        entries = _parse_sitemap_xml(xml, f"{BASE}/post-sitemap.xml")
        assert len(entries) == 3
        assert not any(e["is_sitemap_index"] for e in entries)

    def test_urlset_sitemap_urls(self):
        xml = _read("post_sitemap.xml")
        entries = _parse_sitemap_xml(xml, f"{BASE}/post-sitemap.xml")
        urls = [e["url"] for e in entries]
        assert f"{BASE}/awasi-tambah-baik-sekolah-tahfiz/" in urls

    def test_urlset_lastmod(self):
        xml = _read("post_sitemap.xml")
        entries = _parse_sitemap_xml(xml, f"{BASE}/post-sitemap.xml")
        entry = next(e for e in entries if "awasi-tambah-baik" in e["url"])
        assert entry["lastmod"] == "2025-11-13"

    def test_empty_xml_returns_empty_list(self):
        entries = _parse_sitemap_xml("<root/>", f"{BASE}/sitemap.xml")
        assert entries == []

    def test_malformed_xml_returns_empty_list(self):
        entries = _parse_sitemap_xml("", f"{BASE}/sitemap.xml")
        assert entries == []

    def test_urlset_without_lastmod(self):
        xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/page1</loc></url>
        </urlset>"""
        entries = _parse_sitemap_xml(xml, "https://example.com/sitemap.xml")
        assert len(entries) == 1
        assert entries[0]["lastmod"] == ""

    def test_sitemap_index_skips_entries_without_loc(self):
        xml = """<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap></sitemap>
          <sitemap><loc>https://example.com/child.xml</loc></sitemap>
        </sitemapindex>"""
        entries = _parse_sitemap_xml(xml, "https://example.com/sitemap_index.xml")
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# WordPress Listing Page
# ---------------------------------------------------------------------------

class TestExtractWpListing:
    SOURCE = f"{BASE}/berita-dewan/page/2/"

    def test_extracts_three_articles(self):
        html = _read("wp_listing.html")
        items = _extract_wp_listing(html, self.SOURCE)
        assert len(items) == 3

    def test_titles_extracted(self):
        html = _read("wp_listing.html")
        items = _extract_wp_listing(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert any("Awasi" in t for t in titles)
        assert any("Banjir" in t for t in titles)

    def test_hrefs_extracted(self):
        html = _read("wp_listing.html")
        items = _extract_wp_listing(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert any("awasi-tambah-baik" in h for h in hrefs)

    def test_date_text_from_datetime_attr(self):
        html = _read("wp_listing.html")
        items = _extract_wp_listing(html, self.SOURCE)
        first = items[0]
        assert first["date_text"].startswith("2025-")

    def test_source_url_preserved(self):
        html = _read("wp_listing.html")
        items = _extract_wp_listing(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_no_duplicate_hrefs(self):
        html = _read("wp_listing.html")
        items = _extract_wp_listing(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_empty_html_returns_empty_list(self):
        items = _extract_wp_listing("<html><body></body></html>", self.SOURCE)
        assert items == []

    def test_fallback_to_entry_title_links(self):
        """When no <article> elements, fallback to a.entry-title links."""
        html = """<html><body>
          <a class="entry-title" href="https://example.com/post1/">Post One</a>
          <a class="entry-title" href="https://example.com/post2/">Post Two</a>
        </body></html>"""
        items = _extract_wp_listing(html, self.SOURCE)
        assert len(items) == 2
        assert items[0]["title"] == "Post One"

    def test_article_without_heading_skipped(self):
        html = """<html><body>
          <article class="post"><p>No heading here</p></article>
          <article class="post">
            <h2 class="entry-title">
              <a href="https://example.com/valid/">Valid</a>
            </h2>
          </article>
        </body></html>"""
        items = _extract_wp_listing(html, self.SOURCE)
        assert len(items) == 1
        assert items[0]["title"] == "Valid"


class TestGetNextWpListingPageUrl:
    def test_finds_next_page_link(self):
        html = _read("wp_listing.html")
        next_url = _get_next_wp_listing_page_url(html)
        assert next_url == f"{BASE}/berita-dewan/page/3/"

    def test_returns_none_on_last_page(self):
        html = "<html><body><a class='prev page-numbers' href='/p/1/'>1</a></body></html>"
        assert _get_next_wp_listing_page_url(html) is None

    def test_returns_none_on_empty(self):
        assert _get_next_wp_listing_page_url("<html><body></body></html>") is None


# ---------------------------------------------------------------------------
# WordPress Single Post metadata
# ---------------------------------------------------------------------------

class TestExtractWpPostMeta:
    def test_title_from_h1(self):
        html = _read("wp_post_berita.html")
        meta = _extract_wp_post_meta(html, f"{BASE}/awasi-tambah-baik/")
        assert "Awasi Tambah Baik" in meta["title"]

    def test_date_from_time_tag(self):
        html = _read("wp_post_berita.html")
        meta = _extract_wp_post_meta(html, f"{BASE}/awasi-tambah-baik/")
        assert meta["published_at"] == "2025-11-13"

    def test_title_from_og_meta_fallback(self):
        html = """<html><head>
          <meta property="og:title" content="Test Title From OG"/>
          <meta property="article:published_time" content="2025-06-01T00:00:00+00:00"/>
        </head><body></body></html>"""
        meta = _extract_wp_post_meta(html, f"{BASE}/test/")
        assert meta["title"] == "Test Title From OG"
        assert meta["published_at"] == "2025-06-01"

    def test_missing_date_returns_empty(self):
        html = "<html><body><h1 class='entry-title'>Title Only</h1></body></html>"
        meta = _extract_wp_post_meta(html, f"{BASE}/test/")
        assert meta["title"] == "Title Only"
        assert meta["published_at"] == ""

    def test_title_from_title_tag_pipe_split(self):
        html = """<html><head><title>Hello | Dewan Selangor</title></head><body></body></html>"""
        meta = _extract_wp_post_meta(html, f"{BASE}/test/")
        assert meta["title"] == "Hello"

    def test_date_from_updated_time_fallback(self):
        html = """<html><body>
          <h1 class="entry-title">Post</h1>
          <time class="updated" datetime="2025-03-15T10:00:00+08:00">15 Mac 2025</time>
        </body></html>"""
        meta = _extract_wp_post_meta(html, f"{BASE}/test/")
        assert meta["published_at"] == "2025-03-15"

    def test_equans_sidang_details_date(self):
        html = _read("equans_post.html")
        meta = _extract_wp_post_meta(html, f"{BASE}/question/unisel-8/")
        # "17 Ogos - 20 Ogos 2015" -> start date "2015-08-17"
        assert meta["published_at"] == "2015-08-17"

    def test_equans_title_from_og(self):
        html = _read("equans_post.html")
        meta = _extract_wp_post_meta(html, f"{BASE}/question/unisel-8/")
        assert "UNISEL" in meta["title"]


# ---------------------------------------------------------------------------
# Embedded document links & pdfjs-viewer
# ---------------------------------------------------------------------------

class TestExtractEmbeddedDocLinks:
    def test_pdfjs_iframe_url_extracted(self):
        html = _read("wp_post_with_pdf.html")
        links = _extract_embedded_doc_links(html, BASE)
        pdfjs_links = [dl for dl in links if "ucapan-belanjawan-2026.pdf" in dl.url]
        assert len(pdfjs_links) == 1

    def test_direct_pdf_link_extracted(self):
        html = _read("wp_post_with_pdf.html")
        links = _extract_embedded_doc_links(html, BASE)
        direct_pdf = [dl for dl in links if "lampiran-belanjawan-2026.pdf" in dl.url]
        assert len(direct_pdf) == 1

    def test_docx_link_extracted(self):
        html = _read("wp_post_with_pdf.html")
        links = _extract_embedded_doc_links(html, BASE)
        docx_links = [dl for dl in links if dl.url.endswith(".docx")]
        assert len(docx_links) == 1

    def test_no_duplicate_urls(self):
        html = _read("wp_post_with_pdf.html")
        links = _extract_embedded_doc_links(html, BASE)
        urls = [dl.url for dl in links]
        assert len(urls) == len(set(urls))

    def test_no_doc_links_returns_empty(self):
        html = _read("wp_post_berita.html")
        links = _extract_embedded_doc_links(html, BASE)
        assert links == []

    def test_relative_link_made_absolute(self):
        html = """<html><body>
          <div class="entry-content">
            <a href="/wp-content/uploads/2025/01/report.pdf">Download</a>
          </div>
        </body></html>"""
        links = _extract_embedded_doc_links(html, BASE)
        assert len(links) == 1
        assert links[0].url == f"{BASE}/wp-content/uploads/2025/01/report.pdf"

    def test_pdfjs_viewer_url_decoded(self):
        """The file= query param should be URL-decoded."""
        html = _read("wp_post_with_pdf.html")
        links = _extract_embedded_doc_links(html, BASE)
        pdfjs = next(dl for dl in links if "ucapan-belanjawan-2026" in dl.url)
        assert "%2F" not in pdfjs.url  # should be decoded

    def test_equans_attachments_extracted(self):
        html = _read("equans_post.html")
        links = _extract_embedded_doc_links(html, BASE)
        pdf_links = [dl for dl in links if "unisel-lampiran.pdf" in dl.url]
        xlsx_links = [dl for dl in links if "unisel-data.xlsx" in dl.url]
        assert len(pdf_links) == 1
        assert len(xlsx_links) == 1

    def test_equans_javascript_links_excluded(self):
        html = _read("equans_post.html")
        links = _extract_embedded_doc_links(html, BASE)
        assert not any("javascript:" in dl.url for dl in links)

    def test_equans_attachments_are_absolute(self):
        html = _read("equans_post.html")
        links = _extract_embedded_doc_links(html, BASE)
        assert all(dl.url.startswith("https://") for dl in links)

    def test_mailto_links_excluded(self):
        html = """<html><body>
          <div class="entry-content">
            <a href="mailto:admin@example.com">Email us</a>
            <a href="/doc.pdf">Doc</a>
          </div>
        </body></html>"""
        links = _extract_embedded_doc_links(html, BASE)
        assert len(links) == 1
        assert "doc.pdf" in links[0].url

    def test_hash_links_excluded(self):
        html = """<html><body>
          <div class="entry-content">
            <a href="#">Jump</a>
            <a href="/doc.pdf">Doc</a>
          </div>
        </body></html>"""
        links = _extract_embedded_doc_links(html, BASE)
        assert len(links) == 1


# ---------------------------------------------------------------------------
# Hansard date parsing
# ---------------------------------------------------------------------------

class TestParseHansardDate:
    def test_standard_date_with_malay_day(self):
        assert _parse_hansard_date("18 FEB 2025 (SELASA)") == "2025-02-18"

    def test_malay_month_abbreviation(self):
        assert _parse_hansard_date("3 MAC 2025 (ISNIN)") == "2025-03-03"

    def test_malay_month_full_name(self):
        assert _parse_hansard_date("1 DISEMBER 2025 (SELASA)") == "2025-12-01"

    def test_no_day_suffix(self):
        assert _parse_hansard_date("18 FEB 2025") == "2025-02-18"

    def test_single_digit_day(self):
        assert _parse_hansard_date("5 MEI 2024 (AHAD)") == "2024-05-05"

    def test_empty_string_returns_empty(self):
        assert _parse_hansard_date("") == ""

    def test_whitespace_only_returns_empty(self):
        assert _parse_hansard_date("   ") == ""

    def test_garbage_returns_empty(self):
        assert _parse_hansard_date("not a date at all!!!") == ""


# ---------------------------------------------------------------------------
# e-QUANS date range parsing
# ---------------------------------------------------------------------------

class TestParseEquansDateRange:
    def test_date_range_with_month_on_both_sides(self):
        assert _parse_equans_date_range("17 Ogos - 20 Ogos 2015") == "2015-08-17"

    def test_date_range_mac(self):
        assert _parse_equans_date_range("3 Mac - 5 Mac 2023") == "2023-03-03"

    def test_single_date_no_range(self):
        assert _parse_equans_date_range("21 Oktober 2019") == "2019-10-21"

    def test_empty_string(self):
        assert _parse_equans_date_range("") == ""

    def test_range_with_different_months(self):
        # Hypothetical: different months in range
        result = _parse_equans_date_range("28 Februari - 3 Mac 2023")
        assert result == "2023-02-28"


# ---------------------------------------------------------------------------
# since_filter helper
# ---------------------------------------------------------------------------

class TestSinceFilter:
    def test_item_before_since_is_skipped(self):
        assert _since_filter("2024-01-01", date(2025, 1, 1)) is True

    def test_item_after_since_is_not_skipped(self):
        assert _since_filter("2025-06-01", date(2025, 1, 1)) is False

    def test_item_on_since_date_is_not_skipped(self):
        assert _since_filter("2025-01-01", date(2025, 1, 1)) is False

    def test_no_since_never_skips(self):
        assert _since_filter("2020-01-01", None) is False

    def test_empty_date_never_skips(self):
        assert _since_filter("", date(2025, 1, 1)) is False

    def test_invalid_date_never_skips(self):
        assert _since_filter("not-a-date", date(2025, 1, 1)) is False


# ---------------------------------------------------------------------------
# Hansard hub extractors
# ---------------------------------------------------------------------------

class TestExtractHansardIndex:
    SOURCE = f"{BASE}/penyata-rasmi/"

    def test_extracts_all_session_links(self):
        html = _read("penyata_rasmi_index.html")
        items = _extract_hansard_index(html, self.SOURCE)
        assert len(items) == 3

    def test_href_values_are_correct(self):
        html = _read("penyata_rasmi_index.html")
        items = _extract_hansard_index(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert f"{BASE}/hansard/sesi-1-6/" in hrefs
        assert f"{BASE}/hansard/sesi-2-6/" in hrefs
        assert f"{BASE}/hansard/sesi-3-5/" in hrefs

    def test_year_attributed_correctly(self):
        html = _read("penyata_rasmi_index.html")
        items = _extract_hansard_index(html, self.SOURCE)
        year_by_href = {i["href"]: i["year"] for i in items}
        assert year_by_href[f"{BASE}/hansard/sesi-1-6/"] == "2025"
        assert year_by_href[f"{BASE}/hansard/sesi-2-6/"] == "2025"
        assert year_by_href[f"{BASE}/hansard/sesi-3-5/"] == "2024"

    def test_title_extracted(self):
        html = _read("penyata_rasmi_index.html")
        items = _extract_hansard_index(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert "Sesi 1" in titles
        assert "Sesi 2" in titles

    def test_source_url_preserved(self):
        html = _read("penyata_rasmi_index.html")
        items = _extract_hansard_index(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_no_duplicates(self):
        html = _read("penyata_rasmi_index.html")
        items = _extract_hansard_index(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_empty_html_returns_empty_list(self):
        items = _extract_hansard_index("<html><body></body></html>", self.SOURCE)
        assert items == []


class TestExtractHansardSessionPdfs:
    SOURCE = f"{BASE}/hansard/sesi-1-6/"

    def test_extracts_three_pdfs(self):
        html = _read("hansard_session_pdfs.html")
        items = _extract_hansard_session_pdfs(html, self.SOURCE, BASE)
        assert len(items) == 3

    def test_href_is_absolute_pdf_url(self):
        html = _read("hansard_session_pdfs.html")
        items = _extract_hansard_session_pdfs(html, self.SOURCE, BASE)
        hrefs = [i["href"] for i in items]
        assert all(h.startswith("https://") and h.endswith(".pdf") for h in hrefs)
        assert any("18-FEB-2025" in h for h in hrefs)

    def test_non_pdf_links_excluded(self):
        html = _read("hansard_session_pdfs.html")
        items = _extract_hansard_session_pdfs(html, self.SOURCE, BASE)
        hrefs = [i["href"] for i in items]
        assert not any("/hansard/" in h and h.endswith("/") for h in hrefs)

    def test_date_text_is_sitting_label(self):
        html = _read("hansard_session_pdfs.html")
        items = _extract_hansard_session_pdfs(html, self.SOURCE, BASE)
        date_texts = [i["date_text"] for i in items]
        assert "18 FEB 2025 (SELASA)" in date_texts
        assert "19 FEB 2025 (RABU)" in date_texts

    def test_no_duplicates(self):
        html = _read("hansard_session_pdfs.html")
        items = _extract_hansard_session_pdfs(html, self.SOURCE, BASE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_source_url_preserved(self):
        html = _read("hansard_session_pdfs.html")
        items = _extract_hansard_session_pdfs(html, self.SOURCE, BASE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_empty_html_returns_empty_list(self):
        items = _extract_hansard_session_pdfs(
            "<html><body></body></html>", self.SOURCE, BASE,
        )
        assert items == []


# ---------------------------------------------------------------------------
# e-QUANS listing extractors
# ---------------------------------------------------------------------------

class TestExtractEquansListing:
    SOURCE = f"{BASE}/question/page/2/"

    def test_extracts_three_questions(self):
        html = _read("equans_listing.html")
        items = _extract_equans_listing(html, self.SOURCE)
        assert len(items) == 3

    def test_hrefs_are_question_urls(self):
        html = _read("equans_listing.html")
        items = _extract_equans_listing(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert f"{BASE}/question/unisel-8/" in hrefs
        assert f"{BASE}/question/prestasi-kewangan-negeri-selangor/" in hrefs

    def test_titles_extracted(self):
        html = _read("equans_listing.html")
        items = _extract_equans_listing(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert any("UNISEL" in t for t in titles)
        assert any("PRESTASI" in t for t in titles)

    def test_date_text_is_empty(self):
        html = _read("equans_listing.html")
        items = _extract_equans_listing(html, self.SOURCE)
        assert all(i["date_text"] == "" for i in items)

    def test_source_url_preserved(self):
        html = _read("equans_listing.html")
        items = _extract_equans_listing(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_no_duplicates(self):
        html = _read("equans_listing.html")
        items = _extract_equans_listing(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_empty_html_returns_empty_list(self):
        items = _extract_equans_listing("<html><body></body></html>", self.SOURCE)
        assert items == []

    def test_card_without_header_skipped(self):
        html = """<html><body>
          <div class="card mb-3 question">
            <div class="card-body"><p>No header</p></div>
          </div>
          <div class="card mb-3 question">
            <h3 class="card-header mt-0">
              <a href="https://example.com/q/1/">Question 1</a>
            </h3>
          </div>
        </body></html>"""
        items = _extract_equans_listing(html, self.SOURCE)
        assert len(items) == 1


class TestGetNextEquansPageUrl:
    def test_finds_next_page_via_numbered_links(self):
        html = """<html><body><ul class="pagination">
          <li class="page-item active"><a href="#">2</a></li>
          <li class="page-item"><a href="/question/page/3/?x=1">3</a></li>
          <li class="page-item"><a href="/question/page/4/?x=1">4</a></li>
        </ul></body></html>"""
        assert _get_next_equans_page_url(html, "/question/page/2/") == "/question/page/3/?x=1"

    def test_finds_next_page_via_explicit_next_class(self):
        html = """<html><body><ul class="pagination">
          <li class="page-item active"><a href="#">1</a></li>
          <li class="page-item next"><a href="/question/page/2/">Next</a></li>
        </ul></body></html>"""
        assert _get_next_equans_page_url(html, "/question/") == "/question/page/2/"

    def test_returns_none_when_last_page(self):
        html = """<html><body><ul class="pagination">
          <li class="page-item"><a href="/question/page/4/">4</a></li>
          <li class="page-item active"><a href="#">5</a></li>
        </ul></body></html>"""
        assert _get_next_equans_page_url(html, "/question/page/5/") is None

    def test_returns_none_on_empty_html(self):
        assert _get_next_equans_page_url("<html><body></body></html>", "/") is None

    def test_ignores_hash_href_in_next(self):
        html = """<html><body>
          <ul class="pagination">
            <li class="page-item next">
              <a class="page-link" href="#">Next</a>
            </li>
          </ul>
        </body></html>"""
        assert _get_next_equans_page_url(html, "/") is None


# ---------------------------------------------------------------------------
# Adapter integration tests (discover)
# ---------------------------------------------------------------------------

def _make_adapter(sections: list[dict]) -> DewanSelangorAdapter:
    """Create a DewanSelangorAdapter with mocked HTTP."""
    adapter = DewanSelangorAdapter.__new__(DewanSelangorAdapter)
    adapter.config = {"sections": sections, "base_url": BASE}
    adapter.http = MagicMock()
    adapter.state = None
    adapter.archiver = None
    adapter.browser_pool = None
    return adapter


def _mock_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.status_code = 200
    return resp


class TestAdapterDiscoverSitemap:
    def test_discover_sitemap_recursive(self):
        """Sitemap index -> child sitemap -> DiscoveredItems."""
        adapter = _make_adapter([{
            "name": "posts",
            "source_type": "sitemap",
            "sitemap_url": f"{BASE}/sitemap_index.xml",
            "doc_type": "news",
            "language": "ms",
        }])

        index_xml = _read("sitemap_index.xml")
        post_xml = _read("post_sitemap.xml")

        def mock_get(url):
            if "sitemap_index" in url:
                return _mock_response(index_xml)
            return _mock_response(post_xml)

        adapter.http.get.side_effect = mock_get

        items = list(adapter.discover())
        # 4 child sitemaps x 3 URLs each = 12
        assert len(items) == 12
        assert all(i.doc_type == "news" for i in items)

    def test_discover_sitemap_since_filter(self):
        """Items with lastmod before `since` are filtered out."""
        adapter = _make_adapter([{
            "name": "posts",
            "source_type": "sitemap",
            "sitemap_url": f"{BASE}/post-sitemap.xml",
            "doc_type": "news",
            "language": "ms",
        }])

        post_xml = _read("post_sitemap.xml")
        adapter.http.get.return_value = _mock_response(post_xml)

        # Only 2025-11-13 passes (the other dates are 2025-10-22 and 2025-09-05)
        items = list(adapter.discover(since=date(2025, 11, 1)))
        assert len(items) == 1
        assert "awasi-tambah-baik" in items[0].source_url

    def test_discover_sitemap_since_none_returns_all(self):
        adapter = _make_adapter([{
            "name": "posts",
            "source_type": "sitemap",
            "sitemap_url": f"{BASE}/post-sitemap.xml",
            "doc_type": "news",
            "language": "ms",
        }])

        post_xml = _read("post_sitemap.xml")
        adapter.http.get.return_value = _mock_response(post_xml)

        items = list(adapter.discover(since=None))
        assert len(items) == 3

    def test_discover_sitemap_http_error_graceful(self):
        adapter = _make_adapter([{
            "name": "failing",
            "source_type": "sitemap",
            "sitemap_url": f"{BASE}/bad-sitemap.xml",
            "doc_type": "news",
            "language": "ms",
        }])
        adapter.http.get.side_effect = ConnectionError("Network error")
        items = list(adapter.discover())
        assert len(items) == 0


class TestAdapterDiscoverListing:
    def test_discover_listing_with_pagination(self):
        adapter = _make_adapter([{
            "name": "berita",
            "source_type": "listing",
            "listing_pages": [{"url": f"{BASE}/berita-dewan/"}],
            "doc_type": "news",
            "language": "ms",
        }])

        page1 = _read("wp_listing.html")
        page2 = "<html><body></body></html>"

        call_count = [0]

        def mock_get(url):
            call_count[0] += 1
            if call_count[0] == 1:
                return _mock_response(page1)
            return _mock_response(page2)

        adapter.http.get.side_effect = mock_get

        items = list(adapter.discover())
        assert len(items) == 3
        assert call_count[0] == 2

    def test_discover_listing_max_pages(self):
        adapter = _make_adapter([{
            "name": "berita",
            "source_type": "listing",
            "listing_pages": [{"url": f"{BASE}/berita-dewan/"}],
            "doc_type": "news",
            "language": "ms",
        }])

        page1 = _read("wp_listing.html")
        adapter.http.get.return_value = _mock_response(page1)

        items = list(adapter.discover(max_pages=1))
        assert len(items) == 3
        assert adapter.http.get.call_count == 1

    def test_discover_listing_since_filter(self):
        adapter = _make_adapter([{
            "name": "berita",
            "source_type": "listing",
            "listing_pages": [{"url": f"{BASE}/berita-dewan/"}],
            "doc_type": "news",
            "language": "ms",
        }])

        page1 = _read("wp_listing.html")
        adapter.http.get.side_effect = [
            _mock_response(page1),
            _mock_response("<html><body></body></html>"),
        ]

        # Dates in fixture: 2025-11-13, 2025-10-22, 2025-09-05
        items = list(adapter.discover(since=date(2025, 10, 1)))
        assert len(items) == 2
        urls = [i.source_url for i in items]
        assert any("awasi-tambah-baik" in u for u in urls)
        assert any("banjir" in u for u in urls)

    def test_discover_listing_empty_page(self):
        adapter = _make_adapter([{
            "name": "empty",
            "source_type": "listing",
            "listing_pages": [{"url": f"{BASE}/empty/"}],
            "doc_type": "news",
            "language": "ms",
        }])
        adapter.http.get.return_value = _mock_response("<html><body></body></html>")

        items = list(adapter.discover())
        assert len(items) == 0


class TestAdapterDiscoverHub:
    def test_discover_hub_navigates_sessions(self):
        """Hub -> session pages -> PDF DiscoveredItems."""
        adapter = _make_adapter([{
            "name": "hansard",
            "source_type": "hub",
            "hub_page": f"{BASE}/penyata-rasmi/",
            "doc_type": "hansard",
            "language": "ms",
        }])

        hub_html = _read("penyata_rasmi_index.html")
        session_html = _read("hansard_session_pdfs.html")

        def mock_get(url):
            if "penyata-rasmi" in url:
                return _mock_response(hub_html)
            return _mock_response(session_html)

        adapter.http.get.side_effect = mock_get

        items = list(adapter.discover())
        # 3 sessions x 3 PDFs each = 9
        assert len(items) == 9
        assert all(i.doc_type == "hansard" for i in items)
        assert all(i.source_url.endswith(".pdf") for i in items)

    def test_discover_hub_max_pages_limits_sessions(self):
        adapter = _make_adapter([{
            "name": "hansard",
            "source_type": "hub",
            "hub_page": f"{BASE}/penyata-rasmi/",
            "doc_type": "hansard",
            "language": "ms",
        }])

        hub_html = _read("penyata_rasmi_index.html")
        session_html = _read("hansard_session_pdfs.html")

        call_count = [0]

        def mock_get(url):
            call_count[0] += 1
            if "penyata-rasmi" in url:
                return _mock_response(hub_html)
            return _mock_response(session_html)

        adapter.http.get.side_effect = mock_get

        items = list(adapter.discover(max_pages=1))
        # Only 1 session page fetched -> 3 PDFs
        assert len(items) == 3

    def test_discover_hub_since_filter(self):
        adapter = _make_adapter([{
            "name": "hansard",
            "source_type": "hub",
            "hub_page": f"{BASE}/penyata-rasmi/",
            "doc_type": "hansard",
            "language": "ms",
        }])

        hub_html = _read("penyata_rasmi_index.html")
        session_html = _read("hansard_session_pdfs.html")

        def mock_get(url):
            if "penyata-rasmi" in url:
                return _mock_response(hub_html)
            return _mock_response(session_html)

        adapter.http.get.side_effect = mock_get

        # All PDFs in session fixture have dates "18 FEB 2025", "19 FEB 2025", "20 FEB 2025"
        items = list(adapter.discover(since=date(2025, 2, 19)))
        # 3 sessions x 2 PDFs each (19 and 20 Feb pass) = 6
        assert len(items) == 6

    def test_discover_hub_session_http_error_skips_session(self):
        adapter = _make_adapter([{
            "name": "hansard",
            "source_type": "hub",
            "hub_page": f"{BASE}/penyata-rasmi/",
            "doc_type": "hansard",
            "language": "ms",
        }])

        hub_html = _read("penyata_rasmi_index.html")

        call_count = [0]

        def mock_get(url):
            call_count[0] += 1
            if "penyata-rasmi" in url:
                return _mock_response(hub_html)
            raise ConnectionError("Session page unavailable")

        adapter.http.get.side_effect = mock_get

        items = list(adapter.discover())
        # All session fetches fail -- no PDFs discovered
        assert len(items) == 0


class TestAdapterDiscoverEquans:
    def test_discover_equans_with_pagination(self):
        adapter = _make_adapter([{
            "name": "soalan",
            "source_type": "equans",
            "listing_url": f"{BASE}/question/",
            "doc_type": "question",
            "language": "ms",
        }])

        page1 = _read("equans_listing.html")
        page2 = "<html><body></body></html>"

        call_count = [0]

        def mock_get(url):
            call_count[0] += 1
            if call_count[0] == 1:
                return _mock_response(page1)
            return _mock_response(page2)

        adapter.http.get.side_effect = mock_get

        items = list(adapter.discover())
        assert len(items) == 3
        assert call_count[0] == 2

    def test_discover_equans_max_pages(self):
        adapter = _make_adapter([{
            "name": "soalan",
            "source_type": "equans",
            "listing_url": f"{BASE}/question/",
            "doc_type": "question",
            "language": "ms",
        }])

        page1 = _read("equans_listing.html")
        adapter.http.get.return_value = _mock_response(page1)

        items = list(adapter.discover(max_pages=1))
        assert len(items) == 3
        assert adapter.http.get.call_count == 1

    def test_discover_equans_empty_page(self):
        adapter = _make_adapter([{
            "name": "soalan",
            "source_type": "equans",
            "listing_url": f"{BASE}/question/",
            "doc_type": "question",
            "language": "ms",
        }])
        adapter.http.get.return_value = _mock_response("<html><body></body></html>")

        items = list(adapter.discover())
        assert len(items) == 0


# ---------------------------------------------------------------------------
# Adapter fetch_and_extract() tests
# ---------------------------------------------------------------------------

class TestAdapterFetchAndExtract:
    def test_direct_pdf_url_yields_single_candidate(self):
        adapter = _make_adapter([])
        item = DiscoveredItem(
            source_url=f"{BASE}/wp-content/uploads/2025/02/18-FEB-2025-SELASA.pdf",
            title="18 FEB 2025 (SELASA)",
            published_at="2025-02-18",
            doc_type="hansard",
            language="ms",
            metadata={"listing_url": f"{BASE}/hansard/sesi-1-6/", "source_type": "hub"},
        )

        candidates = list(adapter.fetch_and_extract(item))
        assert len(candidates) == 1
        assert candidates[0].url.endswith(".pdf")
        assert candidates[0].content_type == "application/pdf"

    def test_html_page_yields_page_plus_embedded_docs(self):
        adapter = _make_adapter([])
        html = _read("wp_post_with_pdf.html")
        adapter.http.get.return_value = _mock_response(html)

        item = DiscoveredItem(
            source_url=f"{BASE}/ucapan-belanjawan-2026/",
            title="",
            published_at="",
            doc_type="speech",
            language="ms",
            metadata={"source_type": "listing", "listing_url": f"{BASE}/ucapan/"},
        )

        candidates = list(adapter.fetch_and_extract(item))
        # 1 HTML + 3 embedded docs (pdfjs PDF + direct PDF + DOCX)
        assert len(candidates) == 4
        html_candidates = [c for c in candidates if c.content_type == "text/html"]
        assert len(html_candidates) == 1
        pdf_candidates = [c for c in candidates if c.url.endswith(".pdf")]
        assert len(pdf_candidates) == 2

    def test_html_page_populates_metadata(self):
        adapter = _make_adapter([])
        html = _read("wp_post_berita.html")
        adapter.http.get.return_value = _mock_response(html)

        item = DiscoveredItem(
            source_url=f"{BASE}/awasi-tambah-baik-sekolah-tahfiz/",
            title="",
            published_at="",
            doc_type="news",
            language="ms",
            metadata={"source_type": "listing"},
        )

        candidates = list(adapter.fetch_and_extract(item))
        html_candidate = candidates[0]
        assert "Awasi Tambah Baik" in html_candidate.title
        assert html_candidate.published_at == "2025-11-13"

    def test_html_page_no_docs_yields_only_page(self):
        adapter = _make_adapter([])
        html = _read("wp_post_berita.html")
        adapter.http.get.return_value = _mock_response(html)

        item = DiscoveredItem(
            source_url=f"{BASE}/awasi-tambah-baik-sekolah-tahfiz/",
            title="",
            published_at="",
            doc_type="news",
            language="ms",
            metadata={"source_type": "listing"},
        )

        candidates = list(adapter.fetch_and_extract(item))
        # The berita post has no document links
        assert len(candidates) == 1
        assert candidates[0].content_type == "text/html"

    def test_fetch_error_yields_nothing(self):
        adapter = _make_adapter([])
        adapter.http.get.side_effect = ConnectionError("Failed")

        item = DiscoveredItem(
            source_url=f"{BASE}/some-page/",
            title="Test",
            published_at="",
            doc_type="news",
            language="ms",
            metadata={},
        )

        candidates = list(adapter.fetch_and_extract(item))
        assert len(candidates) == 0

    def test_equans_post_yields_attachments(self):
        adapter = _make_adapter([])
        html = _read("equans_post.html")
        adapter.http.get.return_value = _mock_response(html)

        item = DiscoveredItem(
            source_url=f"{BASE}/question/unisel-8/",
            title="",
            published_at="",
            doc_type="question",
            language="ms",
            metadata={"source_type": "equans", "listing_url": f"{BASE}/question/"},
        )

        candidates = list(adapter.fetch_and_extract(item))
        # 1 HTML page + 3 attachments (JPG, PDF, XLSX from .list-of-attachments)
        assert len(candidates) >= 4
        attachment_urls = [c.url for c in candidates if c.url != item.source_url]
        assert any("unisel-lampiran.pdf" in u for u in attachment_urls)
        assert any("unisel-data.xlsx" in u for u in attachment_urls)


# ---------------------------------------------------------------------------
# Adapter miscellaneous
# ---------------------------------------------------------------------------

class TestAdapterMiscellaneous:
    def test_slug_and_agency(self):
        adapter = _make_adapter([])
        assert adapter.slug == "dewan_selangor"
        assert adapter.agency == "Dewan Negeri Selangor"

    def test_requires_browser_false(self):
        adapter = _make_adapter([])
        assert adapter.requires_browser is False

    def test_discover_missing_sitemap_url_skipped(self):
        adapter = _make_adapter([{
            "name": "missing",
            "source_type": "sitemap",
            "doc_type": "other",
        }])
        items = list(adapter.discover())
        assert len(items) == 0

    def test_discover_missing_hub_page_skipped(self):
        adapter = _make_adapter([{
            "name": "missing",
            "source_type": "hub",
            "doc_type": "other",
        }])
        items = list(adapter.discover())
        assert len(items) == 0

    def test_discover_missing_listing_pages_skipped(self):
        adapter = _make_adapter([{
            "name": "missing",
            "source_type": "listing",
            "doc_type": "other",
        }])
        items = list(adapter.discover())
        assert len(items) == 0

    def test_discover_missing_equans_listing_url_skipped(self):
        adapter = _make_adapter([{
            "name": "missing",
            "source_type": "equans",
            "doc_type": "other",
        }])
        items = list(adapter.discover())
        assert len(items) == 0

    def test_extract_downloads_combines_site_specific_and_generic(self):
        adapter = _make_adapter([])
        html = _read("wp_post_with_pdf.html")
        links = adapter.extract_downloads(html, BASE)
        urls = [dl.url for dl in links]
        assert any("ucapan-belanjawan-2026.pdf" in u for u in urls)

    def test_extract_downloads_fallback_to_generic(self):
        """When no site-specific links found, generic extractor runs."""
        adapter = _make_adapter([])
        html = "<html><body><a href='/doc.pdf'>Doc</a></body></html>"
        links = adapter.extract_downloads(html, BASE)
        # Generic extractor should find this PDF link
        assert any("doc.pdf" in dl.url for dl in links)
