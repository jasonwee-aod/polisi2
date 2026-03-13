"""Tests for HTML and XML extractors using local fixtures."""
from pathlib import Path

import pytest

from dewan_selangor_scraper.extractor import (
    extract_embedded_doc_links,
    extract_equans_listing,
    extract_hansard_index,
    extract_hansard_session_pdfs,
    extract_wp_listing,
    extract_wp_post_meta,
    get_next_equans_page_url,
    get_next_listing_page_url,
    parse_hansard_date,
    parse_sitemap_xml,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── Sitemap parser ────────────────────────────────────────────────────────────


class TestParseSitemapXml:
    def test_sitemap_index_returns_child_sitemaps(self):
        xml = _read("sitemap_index.xml")
        entries = parse_sitemap_xml(xml, "https://dewan.selangor.gov.my/sitemap_index.xml")
        assert len(entries) == 4
        assert all(e["is_sitemap_index"] for e in entries)

    def test_sitemap_index_urls(self):
        xml = _read("sitemap_index.xml")
        entries = parse_sitemap_xml(xml, "https://dewan.selangor.gov.my/sitemap_index.xml")
        urls = [e["url"] for e in entries]
        assert "https://dewan.selangor.gov.my/post-sitemap.xml" in urls
        assert "https://dewan.selangor.gov.my/hansard-sitemap.xml" in urls

    def test_urlset_sitemap_returns_article_urls(self):
        xml = _read("post_sitemap.xml")
        entries = parse_sitemap_xml(xml, "https://dewan.selangor.gov.my/post-sitemap.xml")
        assert len(entries) == 3
        assert not any(e["is_sitemap_index"] for e in entries)

    def test_urlset_sitemap_urls(self):
        xml = _read("post_sitemap.xml")
        entries = parse_sitemap_xml(xml, "https://dewan.selangor.gov.my/post-sitemap.xml")
        urls = [e["url"] for e in entries]
        assert "https://dewan.selangor.gov.my/awasi-tambah-baik-sekolah-tahfiz/" in urls

    def test_urlset_lastmod(self):
        xml = _read("post_sitemap.xml")
        entries = parse_sitemap_xml(xml, "https://dewan.selangor.gov.my/post-sitemap.xml")
        entry = next(e for e in entries if "awasi-tambah-baik" in e["url"])
        assert entry["lastmod"] == "2025-11-13"

    def test_empty_xml_returns_empty_list(self):
        entries = parse_sitemap_xml("<root/>", "https://example.com/sitemap.xml")
        assert entries == []


# ── WordPress Listing Page ────────────────────────────────────────────────────


class TestExtractWpListing:
    def test_extracts_three_articles(self):
        html = _read("wp_listing.html")
        items = extract_wp_listing(html, "https://dewan.selangor.gov.my/berita-dewan/page/2/")
        assert len(items) == 3

    def test_titles_extracted(self):
        html = _read("wp_listing.html")
        items = extract_wp_listing(html, "https://dewan.selangor.gov.my/berita-dewan/page/2/")
        titles = [i["title"] for i in items]
        assert any("Awasi" in t for t in titles)
        assert any("Banjir" in t for t in titles)

    def test_hrefs_extracted(self):
        html = _read("wp_listing.html")
        items = extract_wp_listing(html, "https://dewan.selangor.gov.my/berita-dewan/page/2/")
        hrefs = [i["href"] for i in items]
        assert any("awasi-tambah-baik" in h for h in hrefs)

    def test_date_text_from_datetime_attr(self):
        html = _read("wp_listing.html")
        items = extract_wp_listing(html, "https://dewan.selangor.gov.my/berita-dewan/page/2/")
        # First item should have a datetime attribute value
        first = items[0]
        assert first["date_text"].startswith("2025-")

    def test_source_url_preserved(self):
        source = "https://dewan.selangor.gov.my/berita-dewan/page/2/"
        html = _read("wp_listing.html")
        items = extract_wp_listing(html, source)
        assert all(i["source_url"] == source for i in items)

    def test_no_duplicate_hrefs(self):
        html = _read("wp_listing.html")
        items = extract_wp_listing(html, "https://dewan.selangor.gov.my/berita-dewan/")
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_empty_html_returns_empty_list(self):
        items = extract_wp_listing("<html><body></body></html>", "https://example.com/")
        assert items == []


class TestGetNextListingPageUrl:
    def test_finds_next_page_link(self):
        html = _read("wp_listing.html")
        next_url = get_next_listing_page_url(html)
        assert next_url == "https://dewan.selangor.gov.my/berita-dewan/page/3/"

    def test_returns_none_on_last_page(self):
        html = "<html><body><a class='prev page-numbers' href='/p/1/'>1</a></body></html>"
        assert get_next_listing_page_url(html) is None

    def test_returns_none_on_empty(self):
        assert get_next_listing_page_url("<html><body></body></html>") is None


# ── WordPress Single Post ─────────────────────────────────────────────────────


class TestExtractWpPostMeta:
    def test_title_from_h1(self):
        html = _read("wp_post_berita.html")
        meta = extract_wp_post_meta(html, "https://dewan.selangor.gov.my/awasi-tambah-baik/")
        assert "Awasi Tambah Baik" in meta["title"]

    def test_date_from_time_tag(self):
        html = _read("wp_post_berita.html")
        meta = extract_wp_post_meta(html, "https://dewan.selangor.gov.my/awasi-tambah-baik/")
        assert meta["published_at"] == "2025-11-13"

    def test_title_from_og_meta_fallback(self):
        html = """<html><head>
          <meta property="og:title" content="Test Title From OG"/>
          <meta property="article:published_time" content="2025-06-01T00:00:00+00:00"/>
        </head><body></body></html>"""
        meta = extract_wp_post_meta(html, "https://dewan.selangor.gov.my/test/")
        assert meta["title"] == "Test Title From OG"
        assert meta["published_at"] == "2025-06-01"

    def test_missing_date_returns_empty(self):
        html = "<html><body><h1 class='entry-title'>Title Only</h1></body></html>"
        meta = extract_wp_post_meta(html, "https://dewan.selangor.gov.my/test/")
        assert meta["title"] == "Title Only"
        assert meta["published_at"] == ""


# ── Embedded Document Links ───────────────────────────────────────────────────


class TestExtractEmbeddedDocLinks:
    BASE = "https://dewan.selangor.gov.my"

    def test_pdfjs_iframe_url_extracted(self):
        html = _read("wp_post_with_pdf.html")
        links = extract_embedded_doc_links(html, self.BASE)
        pdfjs_links = [l for l in links if "ucapan-belanjawan-2026.pdf" in l]
        assert len(pdfjs_links) == 1

    def test_direct_pdf_link_extracted(self):
        html = _read("wp_post_with_pdf.html")
        links = extract_embedded_doc_links(html, self.BASE)
        direct_pdf = [l for l in links if "lampiran-belanjawan-2026.pdf" in l]
        assert len(direct_pdf) == 1

    def test_docx_link_extracted(self):
        html = _read("wp_post_with_pdf.html")
        links = extract_embedded_doc_links(html, self.BASE)
        docx_links = [l for l in links if l.endswith(".docx")]
        assert len(docx_links) == 1

    def test_no_duplicate_urls(self):
        html = _read("wp_post_with_pdf.html")
        links = extract_embedded_doc_links(html, self.BASE)
        assert len(links) == len(set(links))

    def test_no_doc_links_returns_empty(self):
        html = _read("wp_post_berita.html")
        links = extract_embedded_doc_links(html, self.BASE)
        assert links == []

    def test_relative_link_made_absolute(self):
        html = """<html><body>
          <div class="entry-content">
            <a href="/wp-content/uploads/2025/01/report.pdf">Download</a>
          </div>
        </body></html>"""
        links = extract_embedded_doc_links(html, self.BASE)
        assert links == ["https://dewan.selangor.gov.my/wp-content/uploads/2025/01/report.pdf"]


# ── Penyata Rasmi / Hansard hub extractors ────────────────────────────────────


class TestParseHansardDate:
    def test_standard_date_with_malay_day(self):
        assert parse_hansard_date("18 FEB 2025 (SELASA)") == "2025-02-18"

    def test_malay_month_abbreviation(self):
        assert parse_hansard_date("3 MAC 2025 (ISNIN)") == "2025-03-03"

    def test_malay_month_full_name(self):
        assert parse_hansard_date("1 DISEMBER 2025 (SELASA)") == "2025-12-01"

    def test_no_day_suffix(self):
        # Works without the parenthesised day name too
        assert parse_hansard_date("18 FEB 2025") == "2025-02-18"

    def test_single_digit_day(self):
        assert parse_hansard_date("5 MEI 2024 (AHAD)") == "2024-05-05"

    def test_empty_string_returns_empty(self):
        assert parse_hansard_date("") == ""

    def test_whitespace_only_returns_empty(self):
        assert parse_hansard_date("   ") == ""

    def test_garbage_returns_empty(self):
        assert parse_hansard_date("not a date at all!!!") == ""


class TestExtractHansardIndex:
    SOURCE = "https://dewan.selangor.gov.my/penyata-rasmi/"

    def test_extracts_all_session_links(self):
        html = _read("penyata_rasmi_index.html")
        items = extract_hansard_index(html, self.SOURCE)
        # Fixture has 3 session links: sesi-1-6, sesi-2-6, sesi-3-5
        assert len(items) == 3

    def test_href_values_are_correct(self):
        html = _read("penyata_rasmi_index.html")
        items = extract_hansard_index(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert "https://dewan.selangor.gov.my/hansard/sesi-1-6/" in hrefs
        assert "https://dewan.selangor.gov.my/hansard/sesi-2-6/" in hrefs
        assert "https://dewan.selangor.gov.my/hansard/sesi-3-5/" in hrefs

    def test_year_attributed_correctly(self):
        html = _read("penyata_rasmi_index.html")
        items = extract_hansard_index(html, self.SOURCE)
        year_by_href = {i["href"]: i["year"] for i in items}
        assert year_by_href["https://dewan.selangor.gov.my/hansard/sesi-1-6/"] == "2025"
        assert year_by_href["https://dewan.selangor.gov.my/hansard/sesi-2-6/"] == "2025"
        assert year_by_href["https://dewan.selangor.gov.my/hansard/sesi-3-5/"] == "2024"

    def test_title_extracted(self):
        html = _read("penyata_rasmi_index.html")
        items = extract_hansard_index(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert "Sesi 1" in titles
        assert "Sesi 2" in titles

    def test_source_url_preserved(self):
        html = _read("penyata_rasmi_index.html")
        items = extract_hansard_index(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_no_duplicates(self):
        html = _read("penyata_rasmi_index.html")
        items = extract_hansard_index(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_empty_html_returns_empty_list(self):
        items = extract_hansard_index("<html><body></body></html>", self.SOURCE)
        assert items == []


class TestExtractHansardSessionPdfs:
    BASE = "https://dewan.selangor.gov.my"
    SOURCE = "https://dewan.selangor.gov.my/hansard/sesi-1-6/"

    def test_extracts_three_pdfs(self):
        html = _read("hansard_session_pdfs.html")
        items = extract_hansard_session_pdfs(html, self.SOURCE, self.BASE)
        assert len(items) == 3

    def test_href_is_absolute_pdf_url(self):
        html = _read("hansard_session_pdfs.html")
        items = extract_hansard_session_pdfs(html, self.SOURCE, self.BASE)
        hrefs = [i["href"] for i in items]
        assert all(h.startswith("https://") and h.endswith(".pdf") for h in hrefs)
        assert any("18-FEB-2025" in h for h in hrefs)

    def test_non_pdf_links_excluded(self):
        html = _read("hansard_session_pdfs.html")
        items = extract_hansard_session_pdfs(html, self.SOURCE, self.BASE)
        # The fixture has a non-PDF link ("Kembali ke Senarai") that must be excluded
        hrefs = [i["href"] for i in items]
        assert not any("/hansard/" in h and h.endswith("/") for h in hrefs)

    def test_date_text_is_sitting_label(self):
        html = _read("hansard_session_pdfs.html")
        items = extract_hansard_session_pdfs(html, self.SOURCE, self.BASE)
        date_texts = [i["date_text"] for i in items]
        assert "18 FEB 2025 (SELASA)" in date_texts
        assert "19 FEB 2025 (RABU)" in date_texts

    def test_no_duplicates(self):
        html = _read("hansard_session_pdfs.html")
        items = extract_hansard_session_pdfs(html, self.SOURCE, self.BASE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_source_url_preserved(self):
        html = _read("hansard_session_pdfs.html")
        items = extract_hansard_session_pdfs(html, self.SOURCE, self.BASE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_empty_html_returns_empty_list(self):
        items = extract_hansard_session_pdfs("<html><body></body></html>", self.SOURCE, self.BASE)
        assert items == []


# ── e-QUANS (Question archive) extractors ─────────────────────────────────────


class TestExtractEquansListing:
    SOURCE = "https://dewan.selangor.gov.my/question/page/2/"

    def test_extracts_three_questions(self):
        html = _read("equans_listing.html")
        items = extract_equans_listing(html, self.SOURCE)
        assert len(items) == 3

    def test_hrefs_are_question_urls(self):
        html = _read("equans_listing.html")
        items = extract_equans_listing(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert "https://dewan.selangor.gov.my/question/unisel-8/" in hrefs
        assert "https://dewan.selangor.gov.my/question/prestasi-kewangan-negeri-selangor/" in hrefs

    def test_titles_extracted(self):
        html = _read("equans_listing.html")
        items = extract_equans_listing(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert any("UNISEL" in t for t in titles)
        assert any("PRESTASI" in t for t in titles)

    def test_date_text_is_empty(self):
        # Date is only on the individual question page, not the listing
        html = _read("equans_listing.html")
        items = extract_equans_listing(html, self.SOURCE)
        assert all(i["date_text"] == "" for i in items)

    def test_source_url_preserved(self):
        html = _read("equans_listing.html")
        items = extract_equans_listing(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_no_duplicates(self):
        html = _read("equans_listing.html")
        items = extract_equans_listing(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_empty_html_returns_empty_list(self):
        items = extract_equans_listing("<html><body></body></html>", self.SOURCE)
        assert items == []


class TestGetNextEquansPageUrl:
    SOURCE = "https://dewan.selangor.gov.my/question/page/2/"

    def test_finds_next_page_link(self):
        html = _read("equans_listing.html")
        next_url = get_next_equans_page_url(html)
        assert next_url == "https://dewan.selangor.gov.my/question/page/3/"

    def test_returns_none_when_no_next_li(self):
        # Last page: no li.page-item.next element
        html = """<html><body>
          <div class="pagination-wrap">
            <ul class="pagination">
              <li class="page-item"><a class="page-link" href="/question/page/4/">4</a></li>
              <li class="page-item active"><a class="page-link" href="#">5</a></li>
            </ul>
          </div>
        </body></html>"""
        assert get_next_equans_page_url(html) is None

    def test_returns_none_on_empty_html(self):
        assert get_next_equans_page_url("<html><body></body></html>") is None


class TestEquansPostMeta:
    """Tests that extract_wp_post_meta handles e-QUANS single question pages."""
    URL = "https://dewan.selangor.gov.my/question/unisel-8/"

    def test_title_from_og_title(self):
        html = _read("equans_post.html")
        meta = extract_wp_post_meta(html, self.URL)
        # og:title is "UNISEL | Dewan Negeri Selangor" → stripped to "UNISEL"
        assert "UNISEL" in meta["title"]

    def test_date_from_sidang_details(self):
        html = _read("equans_post.html")
        meta = extract_wp_post_meta(html, self.URL)
        # "17 Ogos - 20 Ogos 2015" → start date "2015-08-17"
        assert meta["published_at"] == "2015-08-17"

    def test_equans_attachments_extracted(self):
        BASE = "https://dewan.selangor.gov.my"
        html = _read("equans_post.html")
        links = extract_embedded_doc_links(html, BASE)
        # Fixture has: JPG, PDF, XLSX, and a javascript: link (excluded)
        jpg_links = [l for l in links if "NO-22.jpg" in l]
        pdf_links = [l for l in links if "unisel-lampiran.pdf" in l]
        xlsx_links = [l for l in links if "unisel-data.xlsx" in l]
        assert len(jpg_links) == 1, "JPG attachment should be included"
        assert len(pdf_links) == 1
        assert len(xlsx_links) == 1

    def test_equans_javascript_links_excluded(self):
        BASE = "https://dewan.selangor.gov.my"
        html = _read("equans_post.html")
        links = extract_embedded_doc_links(html, BASE)
        assert not any("javascript:" in l for l in links)

    def test_equans_attachments_are_absolute(self):
        BASE = "https://dewan.selangor.gov.my"
        html = _read("equans_post.html")
        links = extract_embedded_doc_links(html, BASE)
        assert all(l.startswith("https://") for l in links)
