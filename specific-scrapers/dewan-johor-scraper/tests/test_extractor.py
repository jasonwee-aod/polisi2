"""Tests for HTML and XML extractors using local fixtures."""
from pathlib import Path

import pytest

from dewan_johor_scraper.extractor import (
    extract_divi_listing,
    extract_embedded_doc_links,
    extract_post_meta,
    extract_pr_hub,
    extract_ruu_hub,
    extract_sdjl_hub,
    extract_wpdm_file_links,
    extract_wpdm_page_meta,
    get_next_divi_page_url,
    parse_sitemap_xml,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://dewannegeri.johor.gov.my"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── Sitemap parser ────────────────────────────────────────────────────────────


class TestParseSitemapXml:
    def test_sitemap_index_returns_child_sitemaps(self):
        xml = _read("wp_sitemap_index.xml")
        entries = parse_sitemap_xml(xml, f"{BASE}/wp-sitemap.xml")
        assert len(entries) == 5
        assert all(e["is_sitemap_index"] for e in entries)

    def test_sitemap_index_urls_present(self):
        xml = _read("wp_sitemap_index.xml")
        entries = parse_sitemap_xml(xml, f"{BASE}/wp-sitemap.xml")
        urls = [e["url"] for e in entries]
        assert f"{BASE}/wp-sitemap-posts-post-1.xml" in urls
        assert f"{BASE}/wp-sitemap-posts-wpdmpro-1.xml" in urls

    def test_wpdmpro_sitemap_returns_url_entries(self):
        xml = _read("wpdmpro_sitemap.xml")
        entries = parse_sitemap_xml(xml, f"{BASE}/wp-sitemap-posts-wpdmpro-1.xml")
        assert len(entries) == 3
        assert not any(e["is_sitemap_index"] for e in entries)

    def test_wpdmpro_sitemap_urls(self):
        xml = _read("wpdmpro_sitemap.xml")
        entries = parse_sitemap_xml(xml, f"{BASE}/wp-sitemap-posts-wpdmpro-1.xml")
        urls = [e["url"] for e in entries]
        assert f"{BASE}/download/28-jun-2018/" in urls
        assert f"{BASE}/download/27-jun-2019/" in urls

    def test_wpdmpro_sitemap_lastmod(self):
        xml = _read("wpdmpro_sitemap.xml")
        entries = parse_sitemap_xml(xml, f"{BASE}/wp-sitemap-posts-wpdmpro-1.xml")
        entry = next(e for e in entries if "28-jun-2018" in e["url"])
        assert entry["lastmod"].startswith("2020-05-14")

    def test_empty_xml_returns_empty_list(self):
        entries = parse_sitemap_xml("<root/>", f"{BASE}/sitemap.xml")
        assert entries == []


# ── Divi Listing Page ─────────────────────────────────────────────────────────


class TestExtractDiviListing:
    SOURCE = f"{BASE}/category/pengumuman/"

    def test_extracts_three_articles(self):
        html = _read("divi_post_listing.html")
        items = extract_divi_listing(html, self.SOURCE)
        assert len(items) == 3

    def test_titles_extracted(self):
        html = _read("divi_post_listing.html")
        items = extract_divi_listing(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert any("Sultan Johor" in t for t in titles)
        assert any("Hannah Yeoh" in t for t in titles)
        assert any("Mesyuarat Pertama" in t for t in titles)

    def test_hrefs_extracted(self):
        html = _read("divi_post_listing.html")
        items = extract_divi_listing(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert any("lintas-hormat" in h for h in hrefs)

    def test_date_text_from_published_span(self):
        html = _read("divi_post_listing.html")
        items = extract_divi_listing(html, self.SOURCE)
        date_texts = [i["date_text"] for i in items]
        assert "Jul 27, 2019" in date_texts
        assert "Apr 4, 2019" in date_texts
        assert "Jan 15, 2019" in date_texts

    def test_source_url_preserved(self):
        html = _read("divi_post_listing.html")
        items = extract_divi_listing(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_no_duplicate_hrefs(self):
        html = _read("divi_post_listing.html")
        items = extract_divi_listing(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_empty_html_returns_empty_list(self):
        items = extract_divi_listing("<html><body></body></html>", self.SOURCE)
        assert items == []


class TestGetNextDiviPageUrl:
    def test_finds_next_page_link_in_alignright(self):
        html = _read("divi_post_listing.html")
        next_url = get_next_divi_page_url(html)
        assert next_url == f"{BASE}/category/pengumuman/?paged=3"

    def test_returns_none_when_alignright_empty(self):
        html = """<html><body>
          <div class="pagination clearfix">
            <div class="alignleft"><a href="...">« Prev</a></div>
            <div class="alignright"></div>
          </div>
        </body></html>"""
        assert get_next_divi_page_url(html) is None

    def test_returns_none_on_empty_html(self):
        assert get_next_divi_page_url("<html><body></body></html>") is None


# ── Single Post metadata ───────────────────────────────────────────────────────


class TestExtractPostMeta:
    URL = f"{BASE}/2019/07/27/lintas-hormat-dymm-sultan-johor/"

    def test_title_from_h1(self):
        html = _read("divi_post_detail.html")
        meta = extract_post_meta(html, self.URL)
        assert "Sultan Johor" in meta["title"]

    def test_date_from_article_published_time_meta(self):
        html = _read("divi_post_detail.html")
        meta = extract_post_meta(html, self.URL)
        assert meta["published_at"] == "2019-07-27"

    def test_title_from_og_meta_fallback(self):
        html = """<html><head>
          <meta property="og:title" content="Test Title | Dewan Negeri Johor"/>
          <meta property="article:published_time" content="2020-01-01T00:00:00+08:00"/>
        </head><body></body></html>"""
        meta = extract_post_meta(html, f"{BASE}/test/")
        assert meta["title"] == "Test Title"
        assert meta["published_at"] == "2020-01-01"

    def test_date_from_published_span_fallback(self):
        html = """<html><body>
          <h1 class="entry-title">My Post</h1>
          <p class="post-meta">by Author | <span class="published">Jul 27, 2019</span></p>
        </body></html>"""
        meta = extract_post_meta(html, f"{BASE}/test/")
        assert meta["published_at"] == "2019-07-27"

    def test_missing_date_returns_empty(self):
        html = "<html><body><h1 class='entry-title'>Title Only</h1></body></html>"
        meta = extract_post_meta(html, f"{BASE}/test/")
        assert meta["title"] == "Title Only"
        assert meta["published_at"] == ""


# ── WP Download Manager page metadata ─────────────────────────────────────────


class TestExtractWpdmPageMeta:
    URL = f"{BASE}/download/28-jun-2018/"

    def test_title_from_h1(self):
        html = _read("wpdm_single_page.html")
        meta = extract_wpdm_page_meta(html, self.URL)
        assert meta["title"] == "28 Jun 2018"

    def test_date_from_create_date_badge(self):
        html = _read("wpdm_single_page.html")
        meta = extract_wpdm_page_meta(html, self.URL)
        # "Create Date" badge shows "November 11, 2019"
        assert meta["published_at"] == "2019-11-11"

    def test_description_extracted(self):
        html = _read("wpdm_single_page.html")
        meta = extract_wpdm_page_meta(html, self.URL)
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
        meta = extract_wpdm_page_meta(html, f"{BASE}/download/test/")
        assert meta["published_at"] == "2020-06-01"


# ── WP Download Manager file links ────────────────────────────────────────────


class TestExtractWpdmFileLinks:
    URL = f"{BASE}/download/28-jun-2018/"

    def test_extracts_single_inddl_link(self):
        html = _read("wpdm_single_page.html")
        links = extract_wpdm_file_links(html, BASE)
        assert len(links) == 1

    def test_inddl_link_contains_wpdmdl_param(self):
        html = _read("wpdm_single_page.html")
        links = extract_wpdm_file_links(html, BASE)
        assert "wpdmdl=3910" in links[0]

    def test_wpdm_download_link_js_onclick_excluded(self):
        html = _read("wpdm_single_page.html")
        links = extract_wpdm_file_links(html, BASE)
        # wpdm-download-link has href='#' – must not appear
        assert not any(l == f"{BASE}/download/28-jun-2018/#" for l in links)

    def test_extracts_three_inddl_links_from_multi_file(self):
        html = _read("wpdm_multi_file_page.html")
        links = extract_wpdm_file_links(html, BASE)
        assert len(links) == 3

    def test_no_duplicate_links(self):
        html = _read("wpdm_multi_file_page.html")
        links = extract_wpdm_file_links(html, BASE)
        assert len(links) == len(set(links))

    def test_empty_html_returns_empty_list(self):
        links = extract_wpdm_file_links("<html><body></body></html>", BASE)
        assert links == []


# ── Embedded document links ───────────────────────────────────────────────────


class TestExtractEmbeddedDocLinks:
    def test_pdf_link_extracted_from_post(self):
        html = _read("divi_post_detail.html")
        links = extract_embedded_doc_links(html, BASE)
        pdf_links = [l for l in links if "ucapan-lintas-hormat.pdf" in l]
        assert len(pdf_links) == 1

    def test_docx_link_extracted_from_post(self):
        html = _read("divi_post_detail.html")
        links = extract_embedded_doc_links(html, BASE)
        docx_links = [l for l in links if l.endswith(".docx")]
        assert len(docx_links) == 1

    def test_wpdm_inddl_link_extracted(self):
        html = _read("wpdm_single_page.html")
        links = extract_embedded_doc_links(html, BASE)
        wpdm_links = [l for l in links if "wpdmdl" in l]
        assert len(wpdm_links) == 1

    def test_no_duplicate_urls(self):
        html = _read("wpdm_multi_file_page.html")
        links = extract_embedded_doc_links(html, BASE)
        assert len(links) == len(set(links))

    def test_relative_link_made_absolute(self):
        html = """<html><body>
          <div class="entry-content">
            <a href="/wp-content/uploads/2019/07/report.pdf">Download</a>
          </div>
        </body></html>"""
        links = extract_embedded_doc_links(html, BASE)
        assert links == [f"{BASE}/wp-content/uploads/2019/07/report.pdf"]

    def test_no_doc_links_returns_empty(self):
        html = "<html><body><p>No files here</p></body></html>"
        links = extract_embedded_doc_links(html, BASE)
        assert links == []


# ── Penyata Rasmi hub (/pr/) ──────────────────────────────────────────────────


class TestExtractPrHub:
    SOURCE = f"{BASE}/pr/"

    def test_extracts_four_pdf_entries(self):
        html = _read("pr_hub.html")
        items = extract_pr_hub(html, self.SOURCE)
        # Fixture has: 1 (Ke-15 Pg4 Msy1) + 0 placeholder + 2 (Ke-15 Pg3 Msy1 + sambungan) + 1 (Ke-14 Pg1 Msy1) = 4
        assert len(items) == 4

    def test_placeholder_rows_excluded(self):
        html = _read("pr_hub.html")
        items = extract_pr_hub(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert not any("Akan Datang" in t for t in titles)

    def test_dewan_level_assigned(self):
        html = _read("pr_hub.html")
        items = extract_pr_hub(html, self.SOURCE)
        dewan_levels = {i["dewan_level"] for i in items}
        assert "Dewan Negeri Johor Ke-15" in dewan_levels
        assert "Dewan Negeri Johor Ke-14" in dewan_levels

    def test_session_assigned(self):
        html = _read("pr_hub.html")
        items = extract_pr_hub(html, self.SOURCE)
        sessions = {i["session"] for i in items}
        assert "Penggal Persidangan Keempat" in sessions
        assert "Penggal Persidangan Ketiga" in sessions
        assert "Penggal Persidangan Pertama" in sessions

    def test_meeting_assigned(self):
        html = _read("pr_hub.html")
        items = extract_pr_hub(html, self.SOURCE)
        meetings = {i["meeting"] for i in items}
        assert "Mesyuarat Pertama" in meetings
        assert "Mesyuarat Kedua" not in meetings  # only has placeholder row

    def test_hingga_date_extracted(self):
        html = _read("pr_hub.html")
        items = extract_pr_hub(html, self.SOURCE)
        item = next(i for i in items if "16 hingga 26 Mei 2025" in i["title"])
        assert item["date_text"] == "2025-05-16"

    def test_simple_date_extracted(self):
        html = _read("pr_hub.html")
        items = extract_pr_hub(html, self.SOURCE)
        item = next(i for i in items if "11 September 2024" in i["title"])
        assert item["date_text"] == "2024-09-11"

    def test_ke14_date_extracted(self):
        html = _read("pr_hub.html")
        items = extract_pr_hub(html, self.SOURCE)
        item = next(i for i in items if "21 April 2022" in i["title"])
        assert item["date_text"] == "2022-04-21"

    def test_hrefs_are_absolute(self):
        html = _read("pr_hub.html")
        items = extract_pr_hub(html, self.SOURCE)
        assert all(i["href"].startswith("https://") for i in items)

    def test_hrefs_end_in_pdf(self):
        html = _read("pr_hub.html")
        items = extract_pr_hub(html, self.SOURCE)
        assert all(i["href"].lower().endswith(".pdf") for i in items)

    def test_no_duplicate_hrefs(self):
        html = _read("pr_hub.html")
        items = extract_pr_hub(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_source_url_preserved(self):
        html = _read("pr_hub.html")
        items = extract_pr_hub(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_empty_html_returns_empty_list(self):
        items = extract_pr_hub("<html><body></body></html>", self.SOURCE)
        assert items == []


# ── Soalan & Jawapan Lisan hub (/sdjl/) ──────────────────────────────────────


class TestExtractSdjlHub:
    SOURCE = f"{BASE}/sdjl/"

    def test_extracts_four_pdf_entries(self):
        html = _read("sdjl_hub.html")
        items = extract_sdjl_hub(html, self.SOURCE)
        # Fixture: 2 (Pg4 Msy1) + 1 (Pg4 Msy2, placeholder excluded) + 1 (Pg3 Msy1) = 4
        assert len(items) == 4

    def test_placeholder_rows_excluded(self):
        html = _read("sdjl_hub.html")
        items = extract_sdjl_hub(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert not any("Akan Datang" in t for t in titles)

    def test_session_assigned(self):
        html = _read("sdjl_hub.html")
        items = extract_sdjl_hub(html, self.SOURCE)
        sessions = {i["session"] for i in items}
        assert "Penggal Persidangan Keempat" in sessions
        assert "Penggal Persidangan Ketiga" in sessions

    def test_meeting_assigned(self):
        html = _read("sdjl_hub.html")
        items = extract_sdjl_hub(html, self.SOURCE)
        meetings = {i["meeting"] for i in items}
        assert "Mesyuarat Pertama" in meetings
        assert "Mesyuarat Kedua" in meetings

    def test_title_is_link_text(self):
        html = _read("sdjl_hub.html")
        items = extract_sdjl_hub(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert "19 Mei 2025" in titles
        assert "20 Mei 2025" in titles
        assert "11 September 2024" in titles

    def test_date_extracted_from_malay_link_text(self):
        html = _read("sdjl_hub.html")
        items = extract_sdjl_hub(html, self.SOURCE)
        item = next(i for i in items if i["title"] == "19 Mei 2025")
        assert item["date_text"] == "2025-05-19"

    def test_november_date_extracted(self):
        html = _read("sdjl_hub.html")
        items = extract_sdjl_hub(html, self.SOURCE)
        item = next(i for i in items if i["title"] == "17 November 2025")
        assert item["date_text"] == "2025-11-17"

    def test_september_date_extracted(self):
        html = _read("sdjl_hub.html")
        items = extract_sdjl_hub(html, self.SOURCE)
        item = next(i for i in items if i["title"] == "11 September 2024")
        assert item["date_text"] == "2024-09-11"

    def test_hrefs_are_absolute(self):
        html = _read("sdjl_hub.html")
        items = extract_sdjl_hub(html, self.SOURCE)
        assert all(i["href"].startswith("https://") for i in items)

    def test_hrefs_end_in_pdf(self):
        html = _read("sdjl_hub.html")
        items = extract_sdjl_hub(html, self.SOURCE)
        assert all(i["href"].lower().endswith(".pdf") for i in items)

    def test_no_duplicate_hrefs(self):
        html = _read("sdjl_hub.html")
        items = extract_sdjl_hub(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_source_url_preserved(self):
        html = _read("sdjl_hub.html")
        items = extract_sdjl_hub(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_no_dewan_level_key(self):
        # sdjl entries have no dewan_level field (unlike pr_hub)
        html = _read("sdjl_hub.html")
        items = extract_sdjl_hub(html, self.SOURCE)
        assert all("dewan_level" not in i for i in items)

    def test_empty_html_returns_empty_list(self):
        items = extract_sdjl_hub("<html><body></body></html>", self.SOURCE)
        assert items == []


# ── Rang Undang-Undang / Enakmen hub ─────────────────────────────────────────


class TestExtractRuuHub:
    SOURCE = f"{BASE}/rang-undang-undang-enakmen/"

    def test_extracts_three_pdf_entries(self):
        html = _read("ruu_hub.html")
        items = extract_ruu_hub(html, self.SOURCE)
        # Fixture: 1 (Ke-15 Pg4 Msy1) + 0 placeholder + 1 (Ke-15 Pg4 Msy2) + 1 (Ke-14 Pg1 Msy1) = 3
        assert len(items) == 3

    def test_placeholder_rows_excluded(self):
        html = _read("ruu_hub.html")
        items = extract_ruu_hub(html, self.SOURCE)
        # Placeholder row has no link in last column
        assert len(items) == 3

    def test_header_rows_excluded(self):
        html = _read("ruu_hub.html")
        items = extract_ruu_hub(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert not any(t.lower() in ("perkara", "subject", "bil") for t in titles)

    def test_dewan_level_assigned(self):
        html = _read("ruu_hub.html")
        items = extract_ruu_hub(html, self.SOURCE)
        dewan_levels = {i["dewan_level"] for i in items}
        assert "Dewan Negeri Johor Ke-15" in dewan_levels
        assert "Dewan Negeri Johor Ke-14" in dewan_levels

    def test_session_assigned(self):
        html = _read("ruu_hub.html")
        items = extract_ruu_hub(html, self.SOURCE)
        sessions = {i["session"] for i in items}
        assert "Penggal Persidangan Keempat" in sessions
        assert "Penggal Persidangan Pertama" in sessions

    def test_meeting_assigned(self):
        html = _read("ruu_hub.html")
        items = extract_ruu_hub(html, self.SOURCE)
        meetings = {i["meeting"] for i in items}
        assert "Mesyuarat Pertama" in meetings
        assert "Mesyuarat Kedua" in meetings

    def test_title_from_perkara_column(self):
        html = _read("ruu_hub.html")
        items = extract_ruu_hub(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert any("Pentadbiran Tanah" in t for t in titles)
        assert any("Kawalan Banjir" in t for t in titles)
        assert any("Air Bersih" in t for t in titles)

    def test_date_from_tarikh_column(self):
        html = _read("ruu_hub.html")
        items = extract_ruu_hub(html, self.SOURCE)
        item = next(i for i in items if "Pentadbiran Tanah" in i["title"])
        assert item["date_text"] == "2025-05-16"

    def test_september_date_parsed(self):
        html = _read("ruu_hub.html")
        items = extract_ruu_hub(html, self.SOURCE)
        item = next(i for i in items if "Kawalan Banjir" in i["title"])
        assert item["date_text"] == "2025-09-11"

    def test_ke14_date_parsed(self):
        html = _read("ruu_hub.html")
        items = extract_ruu_hub(html, self.SOURCE)
        item = next(i for i in items if "Air Bersih" in i["title"])
        assert item["date_text"] == "2022-04-21"

    def test_hrefs_are_absolute(self):
        html = _read("ruu_hub.html")
        items = extract_ruu_hub(html, self.SOURCE)
        assert all(i["href"].startswith("https://") for i in items)

    def test_hrefs_end_in_pdf(self):
        html = _read("ruu_hub.html")
        items = extract_ruu_hub(html, self.SOURCE)
        assert all(i["href"].lower().endswith(".pdf") for i in items)

    def test_no_duplicate_hrefs(self):
        html = _read("ruu_hub.html")
        items = extract_ruu_hub(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_source_url_preserved(self):
        html = _read("ruu_hub.html")
        items = extract_ruu_hub(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_all_rows_empty_returns_empty_list(self):
        # Page with only placeholder rows (real state of the page currently)
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
        items = extract_ruu_hub(html, self.SOURCE)
        assert items == []

    def test_empty_html_returns_empty_list(self):
        items = extract_ruu_hub("<html><body></body></html>", self.SOURCE)
        assert items == []
