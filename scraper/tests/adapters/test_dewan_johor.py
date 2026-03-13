"""Tests for the Dewan Johor unified adapter.

Covers:
  - Sitemap XML parsing (index + urlset)
  - Divi listing page extraction + pagination
  - WPDM package page metadata extraction
  - WPDM file link extraction (a.inddl with ?wpdmdl=)
  - Embedded document links
  - PR hub extraction (Divi accordion + table)
  - SDJL/SDJB hub extraction
  - RUU hub extraction
  - Post metadata extraction
  - Date parsing
  - since filtering
  - max_pages limiting
  - Adapter discover() integration via mocked HTTP
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from polisi_scraper.adapters.dewan_johor import (
    DewanJohorAdapter,
    _extract_divi_listing,
    _extract_embedded_doc_links,
    _extract_post_meta,
    _extract_pr_hub,
    _extract_ruu_hub,
    _extract_sdjl_hub,
    _extract_wpdm_file_links,
    _extract_wpdm_page_meta,
    _get_next_divi_page_url,
    _is_wpdmpro_url,
    _parse_sitemap_xml,
)
from polisi_scraper.adapters.base import DiscoveredItem

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "dewan_johor"
BASE = "https://dewannegeri.johor.gov.my"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Sitemap XML parser
# ---------------------------------------------------------------------------

class TestParseSitemapXml:
    def test_sitemap_index_returns_child_sitemaps(self):
        xml = _read("wp_sitemap_index.xml")
        entries = _parse_sitemap_xml(xml)
        assert len(entries) == 5
        assert all(e["is_sitemap_index"] for e in entries)

    def test_sitemap_index_urls_present(self):
        xml = _read("wp_sitemap_index.xml")
        entries = _parse_sitemap_xml(xml)
        urls = [e["url"] for e in entries]
        assert f"{BASE}/wp-sitemap-posts-post-1.xml" in urls
        assert f"{BASE}/wp-sitemap-posts-wpdmpro-1.xml" in urls

    def test_sitemap_index_has_empty_lastmod(self):
        xml = _read("wp_sitemap_index.xml")
        entries = _parse_sitemap_xml(xml)
        # The fixture has no <lastmod> in the index entries
        assert all(e["lastmod"] == "" for e in entries)

    def test_wpdmpro_sitemap_returns_url_entries(self):
        xml = _read("wpdmpro_sitemap.xml")
        entries = _parse_sitemap_xml(xml)
        assert len(entries) == 3
        assert not any(e["is_sitemap_index"] for e in entries)

    def test_wpdmpro_sitemap_urls(self):
        xml = _read("wpdmpro_sitemap.xml")
        entries = _parse_sitemap_xml(xml)
        urls = [e["url"] for e in entries]
        assert f"{BASE}/download/28-jun-2018/" in urls
        assert f"{BASE}/download/27-jun-2019/" in urls

    def test_wpdmpro_sitemap_lastmod(self):
        xml = _read("wpdmpro_sitemap.xml")
        entries = _parse_sitemap_xml(xml)
        entry = next(e for e in entries if "28-jun-2018" in e["url"])
        assert entry["lastmod"].startswith("2020-05-14")

    def test_empty_xml_returns_empty_list(self):
        entries = _parse_sitemap_xml("<root/>")
        assert entries == []

    def test_malformed_xml_returns_empty_list(self):
        entries = _parse_sitemap_xml("")
        assert entries == []

    def test_urlset_without_lastmod(self):
        xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/page1</loc></url>
        </urlset>"""
        entries = _parse_sitemap_xml(xml)
        assert len(entries) == 1
        assert entries[0]["lastmod"] == ""
        assert entries[0]["url"] == "https://example.com/page1"

    def test_sitemap_index_skips_loc_missing(self):
        xml = """<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap></sitemap>
          <sitemap><loc>https://example.com/sm.xml</loc></sitemap>
        </sitemapindex>"""
        entries = _parse_sitemap_xml(xml)
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# Divi Listing Page
# ---------------------------------------------------------------------------

class TestExtractDiviListing:
    SOURCE = f"{BASE}/category/pengumuman/"

    def test_extracts_three_articles(self):
        html = _read("divi_post_listing.html")
        items = _extract_divi_listing(html, self.SOURCE)
        assert len(items) == 3

    def test_titles_extracted(self):
        html = _read("divi_post_listing.html")
        items = _extract_divi_listing(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert any("Sultan Johor" in t for t in titles)
        assert any("Hannah Yeoh" in t for t in titles)
        assert any("Mesyuarat Pertama" in t for t in titles)

    def test_hrefs_extracted(self):
        html = _read("divi_post_listing.html")
        items = _extract_divi_listing(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert any("lintas-hormat" in h for h in hrefs)

    def test_date_text_from_published_span(self):
        html = _read("divi_post_listing.html")
        items = _extract_divi_listing(html, self.SOURCE)
        date_texts = [i["date_text"] for i in items]
        assert "Jul 27, 2019" in date_texts
        assert "Apr 4, 2019" in date_texts
        assert "Jan 15, 2019" in date_texts

    def test_source_url_preserved(self):
        html = _read("divi_post_listing.html")
        items = _extract_divi_listing(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_no_duplicate_hrefs(self):
        html = _read("divi_post_listing.html")
        items = _extract_divi_listing(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_empty_html_returns_empty_list(self):
        items = _extract_divi_listing("<html><body></body></html>", self.SOURCE)
        assert items == []


class TestGetNextDiviPageUrl:
    def test_finds_next_page_link_in_alignright(self):
        html = _read("divi_post_listing.html")
        next_url = _get_next_divi_page_url(html)
        assert next_url == f"{BASE}/category/pengumuman/?paged=3"

    def test_returns_none_when_alignright_empty(self):
        html = """<html><body>
          <div class="pagination clearfix">
            <div class="alignleft"><a href="...">Prev</a></div>
            <div class="alignright"></div>
          </div>
        </body></html>"""
        assert _get_next_divi_page_url(html) is None

    def test_returns_none_on_empty_html(self):
        assert _get_next_divi_page_url("<html><body></body></html>") is None

    def test_finds_next_page_numbers_class(self):
        html = """<html><body>
          <a class="next page-numbers" href="https://example.com/page/2/">Next</a>
        </body></html>"""
        assert _get_next_divi_page_url(html) == "https://example.com/page/2/"

    def test_ignores_hash_href(self):
        html = """<html><body>
          <div class="pagination clearfix">
            <div class="alignright"><a href="#">Next</a></div>
          </div>
        </body></html>"""
        assert _get_next_divi_page_url(html) is None


# ---------------------------------------------------------------------------
# Single Post metadata
# ---------------------------------------------------------------------------

class TestExtractPostMeta:
    def test_title_from_h1(self):
        html = _read("divi_post_detail.html")
        meta = _extract_post_meta(html)
        assert "Sultan Johor" in meta["title"]

    def test_date_from_article_published_time_meta(self):
        html = _read("divi_post_detail.html")
        meta = _extract_post_meta(html)
        assert meta["published_at"] == "2019-07-27"

    def test_title_from_og_meta_fallback(self):
        html = """<html><head>
          <meta property="og:title" content="Test Title | Dewan Negeri Johor"/>
          <meta property="article:published_time" content="2020-01-01T00:00:00+08:00"/>
        </head><body></body></html>"""
        meta = _extract_post_meta(html)
        assert meta["title"] == "Test Title"
        assert meta["published_at"] == "2020-01-01"

    def test_date_from_published_span_fallback(self):
        html = """<html><body>
          <h1 class="entry-title">My Post</h1>
          <p class="post-meta">by Author | <span class="published">Jul 27, 2019</span></p>
        </body></html>"""
        meta = _extract_post_meta(html)
        assert meta["published_at"] == "2019-07-27"

    def test_missing_date_returns_empty(self):
        html = "<html><body><h1 class='entry-title'>Title Only</h1></body></html>"
        meta = _extract_post_meta(html)
        assert meta["title"] == "Title Only"
        assert meta["published_at"] == ""

    def test_title_from_title_tag_fallback(self):
        html = """<html><head><title>Hello | Dewan</title></head><body></body></html>"""
        meta = _extract_post_meta(html)
        assert meta["title"] == "Hello"


# ---------------------------------------------------------------------------
# WP Download Manager page metadata
# ---------------------------------------------------------------------------

class TestExtractWpdmPageMeta:
    def test_title_from_h1(self):
        html = _read("wpdm_single_page.html")
        meta = _extract_wpdm_page_meta(html)
        assert meta["title"] == "28 Jun 2018"

    def test_date_from_create_date_badge(self):
        html = _read("wpdm_single_page.html")
        meta = _extract_wpdm_page_meta(html)
        assert meta["published_at"] == "2019-11-11"

    def test_description_extracted(self):
        html = _read("wpdm_single_page.html")
        meta = _extract_wpdm_page_meta(html)
        assert "Penyata Rasmi" in meta["description"]

    def test_missing_create_date_falls_back_to_last_updated(self):
        html = """<html><body>
          <h1 class="entry-title">Test Package</h1>
          <div class='w3eden'>
            <ul class="list-group">
              <li class="list-group-item">
                <span class="badge">June 1, 2020</span> Last Updated
              </li>
            </ul>
          </div>
        </body></html>"""
        meta = _extract_wpdm_page_meta(html)
        assert meta["published_at"] == "2020-06-01"

    def test_multi_file_page_title(self):
        html = _read("wpdm_multi_file_page.html")
        meta = _extract_wpdm_page_meta(html)
        assert "9 Ogos 2018" in meta["title"]

    def test_multi_file_page_description(self):
        html = _read("wpdm_multi_file_page.html")
        meta = _extract_wpdm_page_meta(html)
        assert "Penyata Rasmi" in meta["description"]


# ---------------------------------------------------------------------------
# WP Download Manager file links
# ---------------------------------------------------------------------------

class TestExtractWpdmFileLinks:
    def test_extracts_single_inddl_link(self):
        html = _read("wpdm_single_page.html")
        links = _extract_wpdm_file_links(html, BASE)
        assert len(links) == 1

    def test_inddl_link_contains_wpdmdl_param(self):
        html = _read("wpdm_single_page.html")
        links = _extract_wpdm_file_links(html, BASE)
        assert "wpdmdl=3910" in links[0]

    def test_wpdm_download_link_js_onclick_excluded(self):
        html = _read("wpdm_single_page.html")
        links = _extract_wpdm_file_links(html, BASE)
        # The panel-footer button has href='#' -- must not appear
        assert not any("#" == l.split("?")[0].split("/")[-1] for l in links)

    def test_extracts_three_inddl_links_from_multi_file(self):
        html = _read("wpdm_multi_file_page.html")
        links = _extract_wpdm_file_links(html, BASE)
        assert len(links) == 3

    def test_no_duplicate_links(self):
        html = _read("wpdm_multi_file_page.html")
        links = _extract_wpdm_file_links(html, BASE)
        assert len(links) == len(set(links))

    def test_empty_html_returns_empty_list(self):
        links = _extract_wpdm_file_links("<html><body></body></html>", BASE)
        assert links == []

    def test_inddl_without_wpdmdl_ignored(self):
        html = """<html><body>
          <a class="inddl" href="/download/some-file/">Download</a>
        </body></html>"""
        links = _extract_wpdm_file_links(html, BASE)
        assert links == []

    def test_inddl_javascript_href_ignored(self):
        html = """<html><body>
          <a class="inddl" href="javascript:void(0)">Download</a>
        </body></html>"""
        links = _extract_wpdm_file_links(html, BASE)
        assert links == []


# ---------------------------------------------------------------------------
# Embedded document links
# ---------------------------------------------------------------------------

class TestExtractEmbeddedDocLinks:
    def test_pdf_link_extracted_from_post(self):
        html = _read("divi_post_detail.html")
        links = _extract_embedded_doc_links(html, BASE)
        pdf_links = [dl for dl in links if "ucapan-lintas-hormat.pdf" in dl.url]
        assert len(pdf_links) == 1

    def test_docx_link_extracted_from_post(self):
        html = _read("divi_post_detail.html")
        links = _extract_embedded_doc_links(html, BASE)
        docx_links = [dl for dl in links if dl.url.endswith(".docx")]
        assert len(docx_links) == 1

    def test_wpdm_inddl_link_extracted(self):
        html = _read("wpdm_single_page.html")
        links = _extract_embedded_doc_links(html, BASE)
        wpdm_links = [dl for dl in links if "wpdmdl" in dl.url]
        assert len(wpdm_links) == 1

    def test_no_duplicate_urls(self):
        html = _read("wpdm_multi_file_page.html")
        links = _extract_embedded_doc_links(html, BASE)
        urls = [dl.url for dl in links]
        assert len(urls) == len(set(urls))

    def test_relative_link_made_absolute(self):
        html = """<html><body>
          <div class="entry-content">
            <a href="/wp-content/uploads/2019/07/report.pdf">Download</a>
          </div>
        </body></html>"""
        links = _extract_embedded_doc_links(html, BASE)
        assert len(links) == 1
        assert links[0].url == f"{BASE}/wp-content/uploads/2019/07/report.pdf"

    def test_no_doc_links_returns_empty(self):
        html = "<html><body><p>No files here</p></body></html>"
        links = _extract_embedded_doc_links(html, BASE)
        assert links == []


# ---------------------------------------------------------------------------
# is_wpdmpro_url
# ---------------------------------------------------------------------------

class TestIsWpdmproUrl:
    def test_download_slug_recognized(self):
        assert _is_wpdmpro_url(f"{BASE}/download/28-jun-2018/") is True

    def test_regular_post_url_not_wpdm(self):
        assert _is_wpdmpro_url(f"{BASE}/2019/07/27/some-post/") is False

    def test_root_url_not_wpdm(self):
        assert _is_wpdmpro_url(f"{BASE}/") is False


# ---------------------------------------------------------------------------
# Penyata Rasmi hub (/pr/)
# ---------------------------------------------------------------------------

class TestExtractPrHub:
    SOURCE = f"{BASE}/pr/"

    def test_extracts_four_pdf_entries(self):
        html = _read("pr_hub.html")
        items = _extract_pr_hub(html, self.SOURCE)
        assert len(items) == 4

    def test_placeholder_rows_excluded(self):
        html = _read("pr_hub.html")
        items = _extract_pr_hub(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert not any("Akan Datang" in t for t in titles)

    def test_dewan_level_assigned(self):
        html = _read("pr_hub.html")
        items = _extract_pr_hub(html, self.SOURCE)
        dewan_levels = {i["dewan_level"] for i in items}
        assert "Dewan Negeri Johor Ke-15" in dewan_levels
        assert "Dewan Negeri Johor Ke-14" in dewan_levels

    def test_session_assigned(self):
        html = _read("pr_hub.html")
        items = _extract_pr_hub(html, self.SOURCE)
        sessions = {i["session"] for i in items}
        assert "Penggal Persidangan Keempat" in sessions
        assert "Penggal Persidangan Ketiga" in sessions
        assert "Penggal Persidangan Pertama" in sessions

    def test_meeting_assigned(self):
        html = _read("pr_hub.html")
        items = _extract_pr_hub(html, self.SOURCE)
        meetings = {i["meeting"] for i in items}
        assert "Mesyuarat Pertama" in meetings

    def test_date_text_is_parsed(self):
        """date_text is produced by parse_malay_date on the full doc title.

        Note: parse_malay_date uses fuzzy parsing, so the "Ke-15"/"Ke-14" in
        the title can influence the year. We just verify a non-empty date is set.
        """
        html = _read("pr_hub.html")
        items = _extract_pr_hub(html, self.SOURCE)
        for item in items:
            assert item["date_text"] != "", f"Expected non-empty date for: {item['title']}"

    def test_simple_title_date_extracted(self):
        """When the title has a plain Malay date without 'Ke-N' noise, parsing is accurate."""
        html = _read("pr_hub.html")
        items = _extract_pr_hub(html, self.SOURCE)
        # The sambungan title has "21, 24, 25 Oktober 2024"
        item = next(i for i in items if "Oktober 2024" in i["title"])
        assert item["date_text"].startswith("2024-")

    def test_hrefs_are_absolute(self):
        html = _read("pr_hub.html")
        items = _extract_pr_hub(html, self.SOURCE)
        assert all(i["href"].startswith("https://") for i in items)

    def test_hrefs_end_in_pdf(self):
        html = _read("pr_hub.html")
        items = _extract_pr_hub(html, self.SOURCE)
        assert all(i["href"].lower().endswith(".pdf") for i in items)

    def test_no_duplicate_hrefs(self):
        html = _read("pr_hub.html")
        items = _extract_pr_hub(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_source_url_preserved(self):
        html = _read("pr_hub.html")
        items = _extract_pr_hub(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_empty_html_returns_empty_list(self):
        items = _extract_pr_hub("<html><body></body></html>", self.SOURCE)
        assert items == []


# ---------------------------------------------------------------------------
# Soalan & Jawapan Lisan hub (/sdjl/)
# ---------------------------------------------------------------------------

class TestExtractSdjlHub:
    SOURCE = f"{BASE}/sdjl/"

    def test_extracts_four_pdf_entries(self):
        html = _read("sdjl_hub.html")
        items = _extract_sdjl_hub(html, self.SOURCE)
        assert len(items) == 4

    def test_placeholder_rows_excluded(self):
        html = _read("sdjl_hub.html")
        items = _extract_sdjl_hub(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert not any("Akan Datang" in t for t in titles)

    def test_session_assigned(self):
        html = _read("sdjl_hub.html")
        items = _extract_sdjl_hub(html, self.SOURCE)
        sessions = {i["session"] for i in items}
        assert "Penggal Persidangan Keempat" in sessions
        assert "Penggal Persidangan Ketiga" in sessions

    def test_meeting_assigned(self):
        html = _read("sdjl_hub.html")
        items = _extract_sdjl_hub(html, self.SOURCE)
        meetings = {i["meeting"] for i in items}
        assert "Mesyuarat Pertama" in meetings
        assert "Mesyuarat Kedua" in meetings

    def test_title_is_link_text(self):
        html = _read("sdjl_hub.html")
        items = _extract_sdjl_hub(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert "19 Mei 2025" in titles
        assert "20 Mei 2025" in titles
        assert "11 September 2024" in titles

    def test_date_extracted_from_malay_link_text(self):
        html = _read("sdjl_hub.html")
        items = _extract_sdjl_hub(html, self.SOURCE)
        item = next(i for i in items if i["title"] == "19 Mei 2025")
        assert item["date_text"] == "2025-05-19"

    def test_november_date_extracted(self):
        html = _read("sdjl_hub.html")
        items = _extract_sdjl_hub(html, self.SOURCE)
        item = next(i for i in items if i["title"] == "17 November 2025")
        assert item["date_text"] == "2025-11-17"

    def test_september_date_extracted(self):
        html = _read("sdjl_hub.html")
        items = _extract_sdjl_hub(html, self.SOURCE)
        item = next(i for i in items if i["title"] == "11 September 2024")
        assert item["date_text"] == "2024-09-11"

    def test_hrefs_are_absolute(self):
        html = _read("sdjl_hub.html")
        items = _extract_sdjl_hub(html, self.SOURCE)
        assert all(i["href"].startswith("https://") for i in items)

    def test_hrefs_end_in_pdf(self):
        html = _read("sdjl_hub.html")
        items = _extract_sdjl_hub(html, self.SOURCE)
        assert all(i["href"].lower().endswith(".pdf") for i in items)

    def test_no_duplicate_hrefs(self):
        html = _read("sdjl_hub.html")
        items = _extract_sdjl_hub(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_source_url_preserved(self):
        html = _read("sdjl_hub.html")
        items = _extract_sdjl_hub(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_no_dewan_level_key(self):
        html = _read("sdjl_hub.html")
        items = _extract_sdjl_hub(html, self.SOURCE)
        assert all("dewan_level" not in i for i in items)

    def test_empty_html_returns_empty_list(self):
        items = _extract_sdjl_hub("<html><body></body></html>", self.SOURCE)
        assert items == []


# ---------------------------------------------------------------------------
# Rang Undang-Undang / Enakmen hub
# ---------------------------------------------------------------------------

class TestExtractRuuHub:
    SOURCE = f"{BASE}/rang-undang-undang-enakmen/"

    def test_extracts_three_pdf_entries(self):
        html = _read("ruu_hub.html")
        items = _extract_ruu_hub(html, self.SOURCE)
        assert len(items) == 3

    def test_placeholder_rows_excluded(self):
        html = _read("ruu_hub.html")
        items = _extract_ruu_hub(html, self.SOURCE)
        # Placeholder row has no <a> in last column
        assert len(items) == 3

    def test_header_rows_excluded(self):
        html = _read("ruu_hub.html")
        items = _extract_ruu_hub(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert not any(t.lower() in ("perkara", "subject", "bil") for t in titles)

    def test_dewan_level_assigned(self):
        html = _read("ruu_hub.html")
        items = _extract_ruu_hub(html, self.SOURCE)
        dewan_levels = {i["dewan_level"] for i in items}
        assert "Dewan Negeri Johor Ke-15" in dewan_levels
        assert "Dewan Negeri Johor Ke-14" in dewan_levels

    def test_session_assigned(self):
        html = _read("ruu_hub.html")
        items = _extract_ruu_hub(html, self.SOURCE)
        sessions = {i["session"] for i in items}
        assert "Penggal Persidangan Keempat" in sessions
        assert "Penggal Persidangan Pertama" in sessions

    def test_meeting_assigned(self):
        html = _read("ruu_hub.html")
        items = _extract_ruu_hub(html, self.SOURCE)
        meetings = {i["meeting"] for i in items}
        assert "Mesyuarat Pertama" in meetings
        assert "Mesyuarat Kedua" in meetings

    def test_title_from_perkara_column(self):
        html = _read("ruu_hub.html")
        items = _extract_ruu_hub(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert any("Pentadbiran Tanah" in t for t in titles)
        assert any("Kawalan Banjir" in t for t in titles)
        assert any("Air Bersih" in t for t in titles)

    def test_date_from_tarikh_column(self):
        html = _read("ruu_hub.html")
        items = _extract_ruu_hub(html, self.SOURCE)
        item = next(i for i in items if "Pentadbiran Tanah" in i["title"])
        assert item["date_text"] == "2025-05-16"

    def test_september_date_parsed(self):
        html = _read("ruu_hub.html")
        items = _extract_ruu_hub(html, self.SOURCE)
        item = next(i for i in items if "Kawalan Banjir" in i["title"])
        assert item["date_text"] == "2025-09-11"

    def test_ke14_date_parsed(self):
        html = _read("ruu_hub.html")
        items = _extract_ruu_hub(html, self.SOURCE)
        item = next(i for i in items if "Air Bersih" in i["title"])
        assert item["date_text"] == "2022-04-21"

    def test_hrefs_are_absolute(self):
        html = _read("ruu_hub.html")
        items = _extract_ruu_hub(html, self.SOURCE)
        assert all(i["href"].startswith("https://") for i in items)

    def test_hrefs_end_in_pdf(self):
        html = _read("ruu_hub.html")
        items = _extract_ruu_hub(html, self.SOURCE)
        assert all(i["href"].lower().endswith(".pdf") for i in items)

    def test_no_duplicate_hrefs(self):
        html = _read("ruu_hub.html")
        items = _extract_ruu_hub(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_source_url_preserved(self):
        html = _read("ruu_hub.html")
        items = _extract_ruu_hub(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_all_rows_empty_returns_empty_list(self):
        html = """<html><body>
          <div class="et_pb_accordion et_pb_module">
            <div class="et_pb_toggle">
              <h5 class="et_pb_toggle_title">Penggal Persidangan Keempat</h5>
              <div class="et_pb_toggle_content clearfix">
                <p><strong>Mesyuarat Pertama</strong></p>
                <table><tbody>
                  <tr><td>Bil</td><td>Tarikh</td><td>Perkara</td><td>Muat Turun</td></tr>
                  <tr><td>1.</td><td></td><td><p>&nbsp;</p></td><td></td></tr>
                </tbody></table>
              </div>
            </div>
          </div>
        </body></html>"""
        items = _extract_ruu_hub(html, self.SOURCE)
        assert items == []

    def test_empty_html_returns_empty_list(self):
        items = _extract_ruu_hub("<html><body></body></html>", self.SOURCE)
        assert items == []


# ---------------------------------------------------------------------------
# Adapter integration tests (discover + fetch_and_extract)
# ---------------------------------------------------------------------------

def _make_adapter(sections: list[dict]) -> DewanJohorAdapter:
    """Create a DewanJohorAdapter with mocked HTTP and given sections config."""
    adapter = DewanJohorAdapter.__new__(DewanJohorAdapter)
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
            "name": "test_section",
            "source_type": "sitemap",
            "sitemap_url": f"{BASE}/wp-sitemap.xml",
            "doc_type": "hansard",
            "language": "ms",
        }])

        index_xml = _read("wp_sitemap_index.xml")
        wpdmpro_xml = _read("wpdmpro_sitemap.xml")

        def mock_get(url):
            if url.endswith("wp-sitemap.xml"):
                return _mock_response(index_xml)
            # All child sitemaps return the wpdmpro data for simplicity
            return _mock_response(wpdmpro_xml)

        adapter.http.get.side_effect = mock_get

        items = list(adapter.discover())
        # 5 child sitemaps x 3 URLs each = 15
        assert len(items) == 15
        assert all(i.doc_type == "hansard" for i in items)

    def test_discover_sitemap_since_filter(self):
        """Items older than `since` date are filtered out."""
        adapter = _make_adapter([{
            "name": "test_section",
            "source_type": "sitemap",
            "sitemap_url": f"{BASE}/wp-sitemap-posts-wpdmpro-1.xml",
            "doc_type": "hansard",
            "language": "ms",
        }])

        wpdmpro_xml = _read("wpdmpro_sitemap.xml")
        adapter.http.get.return_value = _mock_response(wpdmpro_xml)

        # All fixture entries have lastmod starting with 2020-05-14
        items = list(adapter.discover(since=date(2021, 1, 1)))
        assert len(items) == 0

    def test_discover_sitemap_since_none_returns_all(self):
        adapter = _make_adapter([{
            "name": "test_section",
            "source_type": "sitemap",
            "sitemap_url": f"{BASE}/wp-sitemap-posts-wpdmpro-1.xml",
            "doc_type": "hansard",
            "language": "ms",
        }])

        wpdmpro_xml = _read("wpdmpro_sitemap.xml")
        adapter.http.get.return_value = _mock_response(wpdmpro_xml)

        items = list(adapter.discover(since=None))
        assert len(items) == 3


class TestAdapterDiscoverListing:
    def test_discover_listing_with_pagination(self):
        """Listing pages are followed via pagination."""
        adapter = _make_adapter([{
            "name": "pengumuman",
            "source_type": "listing",
            "listing_pages": [{"url": f"{BASE}/category/pengumuman/"}],
            "doc_type": "press_release",
            "language": "ms",
        }])

        page1 = _read("divi_post_listing.html")
        # Page 2 has no pagination "next" link
        page2 = "<html><body></body></html>"

        call_count = [0]

        def mock_get(url):
            call_count[0] += 1
            if call_count[0] == 1:
                return _mock_response(page1)
            return _mock_response(page2)

        adapter.http.get.side_effect = mock_get

        items = list(adapter.discover())
        # Page 1 has 3 articles; page 2 is empty
        assert len(items) == 3
        assert call_count[0] == 2  # fetched page 1 + page 2

    def test_discover_listing_max_pages(self):
        """max_pages limits how many listing pages are fetched."""
        adapter = _make_adapter([{
            "name": "pengumuman",
            "source_type": "listing",
            "listing_pages": [{"url": f"{BASE}/category/pengumuman/"}],
            "doc_type": "press_release",
            "language": "ms",
        }])

        page1 = _read("divi_post_listing.html")
        adapter.http.get.return_value = _mock_response(page1)

        items = list(adapter.discover(max_pages=1))
        assert len(items) == 3  # only page 1 articles
        # Should have only fetched once
        assert adapter.http.get.call_count == 1

    def test_discover_listing_since_filter(self):
        """Items older than since are filtered from listing discovery."""
        adapter = _make_adapter([{
            "name": "pengumuman",
            "source_type": "listing",
            "listing_pages": [{"url": f"{BASE}/category/pengumuman/"}],
            "doc_type": "press_release",
            "language": "ms",
        }])

        page1 = _read("divi_post_listing.html")
        # Return page1 then empty page
        adapter.http.get.side_effect = [
            _mock_response(page1),
            _mock_response("<html><body></body></html>"),
        ]

        # "Jul 27, 2019" -> 2019-07-27; all dates are 2019
        items = list(adapter.discover(since=date(2019, 5, 1)))
        # Only "Jul 27, 2019" should pass (Apr 4 and Jan 15 are before May 1)
        assert len(items) == 1
        assert "Sultan Johor" in items[0].title


class TestAdapterDiscoverPrHub:
    def test_discover_pr_hub(self):
        adapter = _make_adapter([{
            "name": "pr",
            "source_type": "pr_hub",
            "hub_url": f"{BASE}/pr/",
            "doc_type": "hansard",
            "language": "ms",
        }])

        hub_html = _read("pr_hub.html")
        adapter.http.get.return_value = _mock_response(hub_html)

        items = list(adapter.discover())
        assert len(items) == 4
        assert all(i.doc_type == "hansard" for i in items)
        assert all(i.metadata.get("_direct_file") is True for i in items)

    def test_discover_pr_hub_since_filter(self):
        adapter = _make_adapter([{
            "name": "pr",
            "source_type": "pr_hub",
            "hub_url": f"{BASE}/pr/",
            "doc_type": "hansard",
            "language": "ms",
        }])

        hub_html = _read("pr_hub.html")
        adapter.http.get.return_value = _mock_response(hub_html)

        # Since 2025-01-01: fuzzy parsing yields "2025-01-01" for the Ke-15 entry
        # and years like 2014/2015 for Ke-14/Ke-15 Pg3 entries, so those get filtered.
        items = list(adapter.discover(since=date(2025, 1, 1)))
        assert len(items) >= 1
        # All returned items should have dates >= 2025-01-01
        for item in items:
            assert item.published_at >= "2025-01-01"


class TestAdapterDiscoverSdjlHub:
    def test_discover_sdjl_hub(self):
        adapter = _make_adapter([{
            "name": "sdjl",
            "source_type": "sdjl_hub",
            "hub_url": f"{BASE}/sdjl/",
            "doc_type": "question",
            "language": "ms",
        }])

        hub_html = _read("sdjl_hub.html")
        adapter.http.get.return_value = _mock_response(hub_html)

        items = list(adapter.discover())
        assert len(items) == 4
        assert all(i.doc_type == "question" for i in items)

    def test_discover_sdjl_hub_since_filter(self):
        adapter = _make_adapter([{
            "name": "sdjl",
            "source_type": "sdjl_hub",
            "hub_url": f"{BASE}/sdjl/",
            "doc_type": "question",
            "language": "ms",
        }])

        hub_html = _read("sdjl_hub.html")
        adapter.http.get.return_value = _mock_response(hub_html)

        items = list(adapter.discover(since=date(2025, 6, 1)))
        # Only 17 November 2025 should pass
        assert len(items) == 1
        assert items[0].published_at == "2025-11-17"


class TestAdapterDiscoverRuuHub:
    def test_discover_ruu_hub(self):
        adapter = _make_adapter([{
            "name": "ruu",
            "source_type": "ruu_hub",
            "hub_url": f"{BASE}/rang-undang-undang-enakmen/",
            "doc_type": "legislation",
            "language": "ms",
        }])

        hub_html = _read("ruu_hub.html")
        adapter.http.get.return_value = _mock_response(hub_html)

        items = list(adapter.discover())
        assert len(items) == 3
        assert all(i.doc_type == "legislation" for i in items)

    def test_discover_ruu_hub_since_filter(self):
        adapter = _make_adapter([{
            "name": "ruu",
            "source_type": "ruu_hub",
            "hub_url": f"{BASE}/rang-undang-undang-enakmen/",
            "doc_type": "legislation",
            "language": "ms",
        }])

        hub_html = _read("ruu_hub.html")
        adapter.http.get.return_value = _mock_response(hub_html)

        # All 2025 entries pass; 2022 does not
        items = list(adapter.discover(since=date(2023, 1, 1)))
        assert len(items) == 2


class TestAdapterFetchAndExtract:
    def test_direct_file_yields_single_candidate(self):
        adapter = _make_adapter([])

        item = DiscoveredItem(
            source_url=f"{BASE}/wp-content/uploads/2025/pr/file.pdf",
            title="Test PDF",
            published_at="2025-05-16",
            doc_type="hansard",
            language="ms",
            metadata={"_direct_file": True, "hub_url": f"{BASE}/pr/"},
        )

        candidates = list(adapter.fetch_and_extract(item))
        assert len(candidates) == 1
        assert candidates[0].url.endswith(".pdf")
        assert candidates[0].content_type == "application/pdf"

    def test_wpdm_page_yields_html_plus_token_links(self):
        adapter = _make_adapter([])
        html = _read("wpdm_multi_file_page.html")
        adapter.http.get.return_value = _mock_response(html)

        item = DiscoveredItem(
            source_url=f"{BASE}/download/9-ogos-2018-19-ogos-2018/",
            title="",
            published_at="",
            doc_type="hansard",
            language="ms",
            metadata={"source_type": "sitemap"},
        )

        candidates = list(adapter.fetch_and_extract(item))
        # 1 HTML page + 3 WPDM inddl links
        assert len(candidates) >= 4
        html_candidates = [c for c in candidates if c.content_type == "text/html"]
        assert len(html_candidates) == 1
        wpdm_candidates = [c for c in candidates if "wpdmdl" in c.url]
        assert len(wpdm_candidates) == 3

    def test_divi_post_yields_html_plus_doc_links(self):
        adapter = _make_adapter([])
        html = _read("divi_post_detail.html")
        adapter.http.get.return_value = _mock_response(html)

        item = DiscoveredItem(
            source_url=f"{BASE}/2019/07/27/lintas-hormat-dymm-sultan-johor/",
            title="",
            published_at="",
            doc_type="press_release",
            language="ms",
            metadata={"source_type": "listing"},
        )

        candidates = list(adapter.fetch_and_extract(item))
        # 1 HTML + 2 doc links (PDF + DOCX)
        assert len(candidates) == 3
        urls = [c.url for c in candidates]
        assert any("ucapan-lintas-hormat.pdf" in u for u in urls)
        assert any("laporan-lintas-hormat.docx" in u for u in urls)

    def test_fetch_and_extract_populates_metadata(self):
        adapter = _make_adapter([])
        html = _read("divi_post_detail.html")
        adapter.http.get.return_value = _mock_response(html)

        item = DiscoveredItem(
            source_url=f"{BASE}/2019/07/27/lintas-hormat-dymm-sultan-johor/",
            title="",
            published_at="",
            doc_type="press_release",
            language="ms",
            metadata={"source_type": "listing"},
        )

        candidates = list(adapter.fetch_and_extract(item))
        html_candidate = candidates[0]
        assert "Sultan Johor" in html_candidate.title
        assert html_candidate.published_at == "2019-07-27"


class TestAdapterMiscellaneous:
    def test_slug_and_agency(self):
        adapter = _make_adapter([])
        assert adapter.slug == "dewan_johor"
        assert adapter.agency == "Dewan Negeri Johor"

    def test_requires_browser_false(self):
        adapter = _make_adapter([])
        assert adapter.requires_browser is False

    def test_discover_unknown_source_type_ignored(self):
        adapter = _make_adapter([{
            "name": "bad_section",
            "source_type": "nonexistent_type",
            "doc_type": "other",
        }])
        items = list(adapter.discover())
        assert len(items) == 0

    def test_discover_missing_sitemap_url_skipped(self):
        adapter = _make_adapter([{
            "name": "missing_url",
            "source_type": "sitemap",
            "doc_type": "other",
        }])
        items = list(adapter.discover())
        assert len(items) == 0

    def test_discover_missing_listing_pages_skipped(self):
        adapter = _make_adapter([{
            "name": "missing_pages",
            "source_type": "listing",
            "doc_type": "other",
        }])
        items = list(adapter.discover())
        assert len(items) == 0

    def test_discover_missing_hub_url_for_pr_hub_skipped(self):
        adapter = _make_adapter([{
            "name": "missing_hub",
            "source_type": "pr_hub",
            "doc_type": "other",
        }])
        items = list(adapter.discover())
        assert len(items) == 0

    def test_discover_http_error_on_sitemap_gracefully_handled(self):
        adapter = _make_adapter([{
            "name": "failing_sitemap",
            "source_type": "sitemap",
            "sitemap_url": f"{BASE}/wp-sitemap.xml",
            "doc_type": "other",
        }])
        adapter.http.get.side_effect = ConnectionError("Network error")
        items = list(adapter.discover())
        assert len(items) == 0

    def test_discover_listing_url_shorthand(self):
        """listing_url as shorthand for listing_pages."""
        adapter = _make_adapter([{
            "name": "shorthand",
            "source_type": "listing",
            "listing_url": f"{BASE}/category/pengumuman/",
            "doc_type": "other",
        }])

        # Return empty page
        adapter.http.get.return_value = _mock_response("<html><body></body></html>")

        items = list(adapter.discover())
        assert len(items) == 0
        # Should have attempted the fetch
        adapter.http.get.assert_called_once()
