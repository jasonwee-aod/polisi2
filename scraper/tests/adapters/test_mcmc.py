"""
Comprehensive tests for the MCMC adapter — article-list-box extraction,
media-box extraction, Bootstrap pagination, /getattachment/ link handling,
acts hub extraction, static pages, date parsing, since filtering,
article detail metadata, and discover/fetch hooks.

Uses fixture files from tests/fixtures/mcmc/ and inline HTML where needed.
60+ tests covering all major code paths.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from polisi_scraper.adapters.mcmc import (
    BASE_URL,
    McmcAdapter,
    _build_listing_url,
    _extract_acts_hub_items,
    _extract_article_list_items,
    _extract_article_meta,
    _extract_embedded_doc_links,
    _extract_media_box_items,
    _get_next_page_number,
    _parse_mcmc_date,
)
from polisi_scraper.adapters.base import DiscoveredItem, DocumentCandidate


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "mcmc"

SOURCE_URL_PR = "https://mcmc.gov.my/en/media/press-releases?page=1"
SOURCE_URL_PUB = "https://mcmc.gov.my/en/resources/publications?page=1"
SOURCE_URL_ACTS = "https://mcmc.gov.my/en/legal/acts"
SOURCE_URL_DR = "https://mcmc.gov.my/en/legal/dispute-resolution"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ===================================================================
# _parse_mcmc_date
# ===================================================================


class TestParseMcmcDate:
    def test_mar_format(self):
        assert _parse_mcmc_date("MAR 03, 2026") == "2026-03-03"

    def test_feb_format(self):
        assert _parse_mcmc_date("FEB 15, 2026") == "2026-02-15"

    def test_jan_format(self):
        assert _parse_mcmc_date("JAN 10, 2012") == "2012-01-10"

    def test_day_month_year(self):
        assert _parse_mcmc_date("03 Mar 2026") == "2026-03-03"

    def test_full_month_name(self):
        assert _parse_mcmc_date("January 15, 2025") == "2025-01-15"

    def test_empty_string_returns_empty(self):
        assert _parse_mcmc_date("") == ""

    def test_whitespace_only_returns_empty(self):
        assert _parse_mcmc_date("   ") == ""

    def test_none_returns_empty(self):
        # The function checks for falsy input
        assert _parse_mcmc_date(None) == ""

    def test_iso_format_passthrough(self):
        assert _parse_mcmc_date("2026-03-03") == "2026-03-03"


# ===================================================================
# _extract_article_list_items
# ===================================================================


class TestExtractArticleListItems:
    def setup_method(self):
        self.html = _read("press_releases_listing.html")

    def test_returns_two_items(self):
        items = _extract_article_list_items(self.html, SOURCE_URL_PR)
        assert len(items) == 2

    def test_first_item_title(self):
        items = _extract_article_list_items(self.html, SOURCE_URL_PR)
        assert "Spectrum Allocation 2026" in items[0]["title"]

    def test_first_item_href(self):
        items = _extract_article_list_items(self.html, SOURCE_URL_PR)
        assert items[0]["href"] == "/en/media/press-releases/mcmc-statement-spectrum-2026"

    def test_first_item_date(self):
        items = _extract_article_list_items(self.html, SOURCE_URL_PR)
        assert items[0]["date_text"] == "MAR 03, 2026"

    def test_first_item_pdf_href(self):
        items = _extract_article_list_items(self.html, SOURCE_URL_PR)
        assert items[0]["pdf_href"].endswith("Spectrum2026.pdf")

    def test_second_item_no_pdf_on_listing(self):
        items = _extract_article_list_items(self.html, SOURCE_URL_PR)
        assert items[1]["pdf_href"] == ""

    def test_second_item_date(self):
        items = _extract_article_list_items(self.html, SOURCE_URL_PR)
        assert items[1]["date_text"] == "FEB 15, 2026"

    def test_second_item_title(self):
        items = _extract_article_list_items(self.html, SOURCE_URL_PR)
        assert "Digital Connectivity" in items[1]["title"]

    def test_no_duplicate_hrefs(self):
        items = _extract_article_list_items(self.html, SOURCE_URL_PR)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_source_url_propagated(self):
        items = _extract_article_list_items(self.html, SOURCE_URL_PR)
        for item in items:
            assert item["source_url"] == SOURCE_URL_PR

    def test_empty_html_returns_empty(self):
        items = _extract_article_list_items("<html><body></body></html>", SOURCE_URL_PR)
        assert items == []

    def test_skips_javascript_hrefs(self):
        html = """
        <div class="article-list-box">
          <div class="article-list-content">
            <h5><a href="javascript:void(0)">Bad</a></h5>
          </div>
        </div>
        """
        items = _extract_article_list_items(html, SOURCE_URL_PR)
        assert items == []

    def test_skips_mailto_hrefs(self):
        html = """
        <div class="article-list-box">
          <div class="article-list-content">
            <h5><a href="mailto:x@y.com">Email</a></h5>
          </div>
        </div>
        """
        items = _extract_article_list_items(html, SOURCE_URL_PR)
        assert items == []

    def test_dedup_across_article_list_boxes(self):
        html = """
        <div class="article-list-box">
          <div class="article-list-content">
            <h5><a href="/en/same">Title A</a></h5>
          </div>
        </div>
        <div class="article-list-box">
          <div class="article-list-content">
            <h5><a href="/en/same">Title B</a></h5>
          </div>
        </div>
        """
        items = _extract_article_list_items(html, SOURCE_URL_PR)
        assert len(items) == 1

    def test_last_page_single_item(self):
        html = _read("press_releases_listing_last_page.html")
        items = _extract_article_list_items(html, SOURCE_URL_PR)
        assert len(items) == 1
        assert "Oldest Press Release" in items[0]["title"]

    def test_no_date_div_returns_empty_date(self):
        html = """
        <div class="article-list-box">
          <div class="article-list-content">
            <h5><a href="/en/item">Title</a></h5>
          </div>
        </div>
        """
        items = _extract_article_list_items(html, SOURCE_URL_PR)
        assert items[0]["date_text"] == ""


# ===================================================================
# _extract_media_box_items
# ===================================================================


class TestExtractMediaBoxItems:
    def setup_method(self):
        self.html = _read("publications_listing.html")

    def test_returns_three_items(self):
        items = _extract_media_box_items(self.html, SOURCE_URL_PUB)
        assert len(items) == 3

    def test_titles_extracted(self):
        items = _extract_media_box_items(self.html, SOURCE_URL_PUB)
        titles = [i["title"] for i in items]
        assert "Industry Performance Report 2025" in titles
        assert "National Broadband Survey 2024" in titles
        assert "Spectrum Outlook 2025" in titles

    def test_hrefs_extracted(self):
        items = _extract_media_box_items(self.html, SOURCE_URL_PUB)
        hrefs = [i["href"] for i in items]
        assert "/en/resources/publications/industry-performance-report-2025" in hrefs
        assert "/en/resources/publications/broadband-survey-2024" in hrefs
        assert "/en/resources/publications/spectrum-outlook-2025" in hrefs

    def test_date_text_empty(self):
        """media_box items don't have dates on the listing page."""
        items = _extract_media_box_items(self.html, SOURCE_URL_PUB)
        for item in items:
            assert item["date_text"] == ""

    def test_pdf_href_empty(self):
        """media_box items have no direct PDF link on the listing page."""
        items = _extract_media_box_items(self.html, SOURCE_URL_PUB)
        for item in items:
            assert item["pdf_href"] == ""

    def test_no_duplicate_hrefs(self):
        items = _extract_media_box_items(self.html, SOURCE_URL_PUB)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_source_url_propagated(self):
        items = _extract_media_box_items(self.html, SOURCE_URL_PUB)
        for item in items:
            assert item["source_url"] == SOURCE_URL_PUB

    def test_empty_html_returns_empty(self):
        items = _extract_media_box_items("<html><body></body></html>", SOURCE_URL_PUB)
        assert items == []

    def test_skips_javascript_hrefs(self):
        html = '<a class="media-box" href="javascript:void(0)"><div class="media-caption"><h4>Bad</h4></div></a>'
        items = _extract_media_box_items(html, SOURCE_URL_PUB)
        assert items == []

    def test_caption_without_h_tag_falls_back_to_text(self):
        html = '<a class="media-box" href="/en/item"><div class="media-caption">Caption Text</div></a>'
        items = _extract_media_box_items(html, SOURCE_URL_PUB)
        assert len(items) == 1
        assert items[0]["title"] == "Caption Text"

    def test_no_caption_falls_back_to_a_text(self):
        html = '<a class="media-box" href="/en/item">Link Text</a>'
        items = _extract_media_box_items(html, SOURCE_URL_PUB)
        assert len(items) == 1
        assert items[0]["title"] == "Link Text"


# ===================================================================
# _get_next_page_number
# ===================================================================


class TestGetNextPageNumber:
    def test_returns_2_on_first_page(self):
        html = _read("press_releases_listing.html")
        assert _get_next_page_number(html) == 2

    def test_returns_none_on_last_page(self):
        html = _read("press_releases_listing_last_page.html")
        assert _get_next_page_number(html) is None

    def test_returns_none_when_no_pagination(self):
        assert _get_next_page_number("<html><body></body></html>") is None

    def test_publications_last_page(self):
        html = _read("publications_listing.html")
        assert _get_next_page_number(html) is None

    def test_returns_none_when_no_active_item(self):
        html = """
        <ul class="pagination">
          <li class="page-item"><a class="page-link" href="?page=1">1</a></li>
        </ul>
        """
        assert _get_next_page_number(html) is None

    def test_returns_none_when_active_has_no_page_link(self):
        html = """
        <ul class="pagination">
          <li class="page-item active"><span>1</span></li>
        </ul>
        """
        assert _get_next_page_number(html) is None

    def test_returns_none_when_active_text_not_numeric(self):
        html = """
        <ul class="pagination">
          <li class="page-item active"><a class="page-link" href="?page=1">abc</a></li>
        </ul>
        """
        assert _get_next_page_number(html) is None


# ===================================================================
# _build_listing_url
# ===================================================================


class TestBuildListingUrl:
    def test_appends_page_param(self):
        url = _build_listing_url("https://mcmc.gov.my/en/press", 2)
        assert url == "https://mcmc.gov.my/en/press?page=2"

    def test_existing_query_uses_ampersand(self):
        url = _build_listing_url("https://mcmc.gov.my/en/press?lang=en", 3)
        assert url == "https://mcmc.gov.my/en/press?lang=en&page=3"


# ===================================================================
# _extract_acts_hub_items
# ===================================================================


class TestExtractActsHubItems:
    def setup_method(self):
        self.html = _read("acts_hub.html")

    def test_returns_four_items(self):
        items = _extract_acts_hub_items(self.html, SOURCE_URL_ACTS)
        assert len(items) == 4

    def test_first_item_title(self):
        items = _extract_acts_hub_items(self.html, SOURCE_URL_ACTS)
        assert "Communications and Multimedia (Amendment) Act 2025" in items[0]["title"]

    def test_first_item_has_detail_href(self):
        items = _extract_acts_hub_items(self.html, SOURCE_URL_ACTS)
        assert "/en/legal/acts/communications-and-multimedia-amendment-act-2025" in items[0]["detail_href"]

    def test_first_item_has_one_doc_href(self):
        items = _extract_acts_hub_items(self.html, SOURCE_URL_ACTS)
        assert len(items[0]["doc_hrefs"]) == 1
        assert items[0]["doc_hrefs"][0].endswith(".pdf")

    def test_second_item_act_588(self):
        items = _extract_acts_hub_items(self.html, SOURCE_URL_ACTS)
        assert "Act 588" in items[1]["title"]
        assert items[1]["detail_href"] != ""
        assert any("Act588" in h for h in items[1]["doc_hrefs"])

    def test_third_item_detail_only_no_docs(self):
        """Digital Signature Act has detail link but no direct PDF on hub."""
        items = _extract_acts_hub_items(self.html, SOURCE_URL_ACTS)
        assert "Digital Signature Act" in items[2]["title"]
        assert items[2]["detail_href"] != ""
        assert items[2]["doc_hrefs"] == []

    def test_fourth_item_two_pdfs_no_detail(self):
        """Spectrum Regulations has two PDFs but no More Details link."""
        items = _extract_acts_hub_items(self.html, SOURCE_URL_ACTS)
        assert "Spectrum" in items[3]["title"]
        assert items[3]["detail_href"] == ""
        assert len(items[3]["doc_hrefs"]) == 2

    def test_no_duplicate_titles(self):
        items = _extract_acts_hub_items(self.html, SOURCE_URL_ACTS)
        titles = [i["title"] for i in items]
        assert len(titles) == len(set(titles))

    def test_all_doc_hrefs_are_doc_files(self):
        items = _extract_acts_hub_items(self.html, SOURCE_URL_ACTS)
        doc_exts = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")
        for item in items:
            for href in item["doc_hrefs"]:
                assert any(href.lower().endswith(e) for e in doc_exts), \
                    f"Non-doc in doc_hrefs: {href}"

    def test_source_url_propagated(self):
        items = _extract_acts_hub_items(self.html, SOURCE_URL_ACTS)
        for item in items:
            assert item["source_url"] == SOURCE_URL_ACTS

    def test_empty_html_returns_empty(self):
        items = _extract_acts_hub_items("<html><body></body></html>", SOURCE_URL_ACTS)
        assert items == []


# ===================================================================
# _extract_article_meta
# ===================================================================


class TestExtractArticleMeta:
    def setup_method(self):
        self.html = _read("press_release_detail.html")
        self.source = "https://mcmc.gov.my/en/media/press-releases/mcmc-statement-spectrum-2026"

    def test_extracts_title(self):
        meta = _extract_article_meta(self.html, self.source)
        assert "Spectrum Allocation 2026" in meta["title"]

    def test_extracts_date_from_date_div(self):
        meta = _extract_article_meta(self.html, self.source)
        assert meta["published_at"] == "2026-03-03"

    def test_title_not_empty(self):
        meta = _extract_article_meta(self.html, self.source)
        assert meta["title"] != ""

    def test_returns_dict_with_required_keys(self):
        meta = _extract_article_meta(self.html, self.source)
        assert "title" in meta
        assert "published_at" in meta

    def test_og_title_fallback(self):
        html = """
        <html><head><meta property="og:title" content="OG Title"></head>
        <body><main></main></body></html>
        """
        meta = _extract_article_meta(html, self.source)
        assert meta["title"] == "OG Title"

    def test_title_tag_fallback(self):
        html = """
        <html><head><title>Page Title | MCMC</title></head>
        <body></body></html>
        """
        meta = _extract_article_meta(html, self.source)
        assert meta["title"] == "Page Title"

    def test_no_date_returns_empty(self):
        html = "<html><body><h1>No Date</h1></body></html>"
        meta = _extract_article_meta(html, self.source)
        assert meta["published_at"] == ""

    def test_article_published_time_meta(self):
        html = """
        <html><head>
          <meta property="article:published_time" content="2026-01-15T10:00:00+08:00">
        </head><body><main><h1>Test</h1></main></body></html>
        """
        meta = _extract_article_meta(html, self.source)
        assert meta["published_at"] == "2026-01-15"

    def test_dc_date_meta(self):
        html = """
        <html><head>
          <meta name="DC.date" content="2025-12-31">
        </head><body><main><h1>Test</h1></main></body></html>
        """
        meta = _extract_article_meta(html, self.source)
        assert meta["published_at"] == "2025-12-31"

    def test_dispute_resolution_title(self):
        html = _read("dispute_resolution.html")
        meta = _extract_article_meta(html, SOURCE_URL_DR)
        assert meta["title"] == "Dispute Resolution"

    def test_dispute_resolution_no_date(self):
        html = _read("dispute_resolution.html")
        meta = _extract_article_meta(html, SOURCE_URL_DR)
        assert meta["published_at"] == ""


# ===================================================================
# _extract_embedded_doc_links
# ===================================================================


class TestExtractEmbeddedDocLinks:
    def setup_method(self):
        self.html = _read("press_release_detail.html")

    def test_finds_pdf_in_content(self):
        links = _extract_embedded_doc_links(self.html, BASE_URL)
        pdf_links = [l for l in links if ".pdf" in l.lower()]
        assert any("Spectrum2026.pdf" in l for l in pdf_links)

    def test_finds_getattachment_link(self):
        links = _extract_embedded_doc_links(self.html, BASE_URL)
        attach_links = [l for l in links if "/getattachment/" in l]
        assert len(attach_links) >= 1

    def test_no_duplicates(self):
        links = _extract_embedded_doc_links(self.html, BASE_URL)
        assert len(links) == len(set(links))

    def test_all_links_are_absolute(self):
        links = _extract_embedded_doc_links(self.html, BASE_URL)
        for link in links:
            assert link.startswith("http"), f"Not absolute: {link}"

    def test_dispute_resolution_finds_guidelines_pdf(self):
        html = _read("dispute_resolution.html")
        links = _extract_embedded_doc_links(html, BASE_URL)
        assert any("Guidelines-for-Dispute-Resolution" in l for l in links)

    def test_dispute_resolution_finds_all_form_pdfs(self):
        html = _read("dispute_resolution.html")
        links = _extract_embedded_doc_links(html, BASE_URL)
        pdf_links = [l for l in links if l.endswith(".pdf")]
        assert len(pdf_links) >= 4

    def test_dispute_resolution_finds_docx_forms(self):
        html = _read("dispute_resolution.html")
        links = _extract_embedded_doc_links(html, BASE_URL)
        docx_links = [l for l in links if l.endswith(".docx")]
        assert len(docx_links) == 3

    def test_dispute_resolution_total_doc_count(self):
        html = _read("dispute_resolution.html")
        links = _extract_embedded_doc_links(html, BASE_URL)
        assert len(links) == 7

    def test_dispute_resolution_no_html_links(self):
        html = _read("dispute_resolution.html")
        links = _extract_embedded_doc_links(html, BASE_URL)
        assert not any("cases" in l for l in links)

    def test_empty_html_returns_empty(self):
        links = _extract_embedded_doc_links("<html><body></body></html>", BASE_URL)
        assert links == []

    def test_javascript_href_ignored(self):
        html = """
        <div class="contentZone">
          <a href="javascript:void(0)">Bad</a>
        </div>
        """
        links = _extract_embedded_doc_links(html, BASE_URL)
        assert links == []

    def test_mailto_ignored(self):
        html = """
        <div class="contentZone">
          <a href="mailto:test@mcmc.gov.my">Email</a>
        </div>
        """
        links = _extract_embedded_doc_links(html, BASE_URL)
        assert links == []

    def test_btn_pdf_outside_content_captured(self):
        """PDF buttons outside the content zone should also be captured."""
        html = """
        <html><body>
          <div class="contentZone"><p>Content</p></div>
          <a class="btn" href="/docs/extra.pdf">Download</a>
        </body></html>
        """
        links = _extract_embedded_doc_links(html, BASE_URL)
        assert any("extra.pdf" in l for l in links)


# ===================================================================
# McmcAdapter.discover() — listing integration
# ===================================================================


class TestMcmcAdapterDiscoverListing:
    def _make_adapter(self, config, responses):
        """Create adapter with mocked HTTP returning pre-set HTML per call."""
        mock_http = MagicMock()
        call_count = [0]

        def side_effect(url):
            resp = MagicMock()
            if call_count[0] < len(responses):
                resp.text = responses[call_count[0]]
            else:
                resp.text = "<html><body></body></html>"
            call_count[0] += 1
            return resp

        mock_http.get.side_effect = side_effect
        return McmcAdapter(config=config, http=mock_http)

    def test_discover_article_list_items(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "press_releases",
                "source_type": "listing",
                "listing_url": f"{BASE_URL}/en/media/press-releases",
                "listing_archetype": "article_list",
                "doc_type": "press_release",
                "language": "en",
            }],
        }
        adapter = self._make_adapter(config, [
            _read("press_releases_listing.html"),
            _read("press_releases_listing_last_page.html"),
            "<html><body></body></html>",
        ])
        items = list(adapter.discover())
        assert len(items) >= 2

    def test_discover_media_box_items(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "publications",
                "source_type": "listing",
                "listing_url": f"{BASE_URL}/en/resources/publications",
                "listing_archetype": "media_box",
                "doc_type": "report",
                "language": "en",
            }],
        }
        adapter = self._make_adapter(config, [_read("publications_listing.html")])
        items = list(adapter.discover())
        assert len(items) == 3

    def test_discover_max_pages(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "press_releases",
                "source_type": "listing",
                "listing_url": f"{BASE_URL}/en/media/press-releases",
                "listing_archetype": "article_list",
                "doc_type": "press_release",
                "language": "en",
            }],
        }
        adapter = self._make_adapter(config, [
            _read("press_releases_listing.html"),
            _read("press_releases_listing_last_page.html"),
        ])
        items = list(adapter.discover(max_pages=1))
        # Only first page fetched -> 2 items
        assert len(items) == 2

    def test_discover_since_filter(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "press_releases",
                "source_type": "listing",
                "listing_url": f"{BASE_URL}/en/media/press-releases",
                "listing_archetype": "article_list",
                "doc_type": "press_release",
                "language": "en",
            }],
        }
        adapter = self._make_adapter(config, [
            _read("press_releases_listing.html"),
            "<html><body></body></html>",
        ])
        # "MAR 03, 2026" and "FEB 15, 2026" — only first passes since=2026-03-01
        items = list(adapter.discover(since=date(2026, 3, 1)))
        assert len(items) == 1
        assert "Spectrum" in items[0].title

    def test_discover_doc_type_propagated(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "press_releases",
                "source_type": "listing",
                "listing_url": f"{BASE_URL}/en/media/press-releases",
                "listing_archetype": "article_list",
                "doc_type": "press_release",
                "language": "en",
            }],
        }
        adapter = self._make_adapter(config, [
            _read("press_releases_listing.html"),
            "<html><body></body></html>",
        ])
        items = list(adapter.discover())
        assert all(item.doc_type == "press_release" for item in items)

    def test_discover_language_propagated(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "test",
                "source_type": "listing",
                "listing_url": f"{BASE_URL}/en/test",
                "listing_archetype": "article_list",
                "doc_type": "other",
                "language": "ms",
            }],
        }
        adapter = self._make_adapter(config, [
            _read("press_releases_listing.html"),
            "<html><body></body></html>",
        ])
        items = list(adapter.discover())
        assert all(item.language == "ms" for item in items)

    def test_discover_metadata_includes_archetype(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "press_releases",
                "source_type": "listing",
                "listing_url": f"{BASE_URL}/en/media/press-releases",
                "listing_archetype": "article_list",
                "doc_type": "press_release",
                "language": "en",
            }],
        }
        adapter = self._make_adapter(config, [
            _read("press_releases_listing.html"),
            "<html><body></body></html>",
        ])
        items = list(adapter.discover())
        assert all(item.metadata.get("archetype") == "article_list" for item in items)

    def test_discover_empty_listing_stops(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "test",
                "source_type": "listing",
                "listing_url": f"{BASE_URL}/en/test",
                "listing_archetype": "article_list",
                "doc_type": "other",
                "language": "en",
            }],
        }
        adapter = self._make_adapter(config, ["<html><body></body></html>"])
        items = list(adapter.discover())
        assert items == []

    def test_discover_http_error_breaks(self):
        mock_http = MagicMock()
        mock_http.get.side_effect = Exception("Network error")
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "test",
                "source_type": "listing",
                "listing_url": f"{BASE_URL}/en/test",
                "listing_archetype": "article_list",
                "doc_type": "other",
                "language": "en",
            }],
        }
        adapter = McmcAdapter(config=config, http=mock_http)
        items = list(adapter.discover())
        assert items == []

    def test_discover_no_sections(self):
        config = {"base_url": BASE_URL, "sections": []}
        adapter = self._make_adapter(config, [])
        items = list(adapter.discover())
        assert items == []

    def test_discover_pdf_href_in_metadata(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "press_releases",
                "source_type": "listing",
                "listing_url": f"{BASE_URL}/en/media/press-releases",
                "listing_archetype": "article_list",
                "doc_type": "press_release",
                "language": "en",
            }],
        }
        adapter = self._make_adapter(config, [
            _read("press_releases_listing.html"),
            "<html><body></body></html>",
        ])
        items = list(adapter.discover())
        # First item should have pdf_href in metadata
        assert items[0].metadata.get("pdf_href", "").endswith("Spectrum2026.pdf")
        assert items[1].metadata.get("pdf_href") == ""


# ===================================================================
# McmcAdapter.discover() — acts_hub
# ===================================================================


class TestMcmcAdapterDiscoverActsHub:
    def _make_adapter(self, config, html):
        mock_http = MagicMock()
        resp = MagicMock()
        resp.text = html
        mock_http.get.return_value = resp
        return McmcAdapter(config=config, http=mock_http)

    def test_discover_acts_hub_yields_items(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "acts",
                "source_type": "acts_hub",
                "hub_url": f"{BASE_URL}/en/legal/acts",
                "doc_type": "legislation",
                "language": "en",
            }],
        }
        adapter = self._make_adapter(config, _read("acts_hub.html"))
        items = list(adapter.discover())
        # 4 acts: 2 with detail+docs, 1 detail-only, 1 docs-only
        # Act1: detail + 1 doc = 2; Act2: detail + 1 doc = 2; Act3: detail = 1; Act4: 2 docs = 2
        assert len(items) == 7

    def test_discover_acts_hub_doc_type_propagated(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "acts",
                "source_type": "acts_hub",
                "hub_url": f"{BASE_URL}/en/legal/acts",
                "doc_type": "legislation",
                "language": "en",
            }],
        }
        adapter = self._make_adapter(config, _read("acts_hub.html"))
        items = list(adapter.discover())
        assert all(item.doc_type == "legislation" for item in items)

    def test_discover_acts_hub_metadata(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "acts",
                "source_type": "acts_hub",
                "hub_url": f"{BASE_URL}/en/legal/acts",
                "doc_type": "legislation",
                "language": "en",
            }],
        }
        adapter = self._make_adapter(config, _read("acts_hub.html"))
        items = list(adapter.discover())
        for item in items:
            assert item.metadata.get("archetype") == "acts_hub"

    def test_discover_acts_hub_http_error(self):
        mock_http = MagicMock()
        mock_http.get.side_effect = Exception("Error")
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "acts",
                "source_type": "acts_hub",
                "hub_url": f"{BASE_URL}/en/legal/acts",
                "doc_type": "legislation",
                "language": "en",
            }],
        }
        adapter = McmcAdapter(config=config, http=mock_http)
        items = list(adapter.discover())
        assert items == []

    def test_discover_acts_hub_missing_hub_url(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "acts",
                "source_type": "acts_hub",
                "doc_type": "legislation",
                "language": "en",
            }],
        }
        adapter = self._make_adapter(config, "")
        items = list(adapter.discover())
        assert items == []


# ===================================================================
# McmcAdapter.discover() — static_page
# ===================================================================


class TestMcmcAdapterDiscoverStaticPage:
    def test_discover_static_page(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "dispute_resolution",
                "source_type": "static_page",
                "page_url": f"{BASE_URL}/en/legal/dispute-resolution",
                "doc_type": "guideline",
                "language": "en",
            }],
        }
        mock_http = MagicMock()
        adapter = McmcAdapter(config=config, http=mock_http)
        items = list(adapter.discover())
        assert len(items) == 1
        assert items[0].doc_type == "guideline"
        assert items[0].metadata.get("archetype") == "static_page"

    def test_discover_static_page_missing_url(self):
        config = {
            "base_url": BASE_URL,
            "sections": [{
                "name": "test",
                "source_type": "static_page",
                "doc_type": "other",
                "language": "en",
            }],
        }
        mock_http = MagicMock()
        adapter = McmcAdapter(config=config, http=mock_http)
        items = list(adapter.discover())
        assert items == []


# ===================================================================
# McmcAdapter.fetch_and_extract()
# ===================================================================


class TestMcmcAdapterFetchAndExtract:
    def _make_adapter(self, html):
        mock_http = MagicMock()
        resp = MagicMock()
        resp.text = html
        mock_http.get.return_value = resp
        return McmcAdapter(config={"base_url": BASE_URL}, http=mock_http)

    def test_html_page_yields_html_candidate(self):
        adapter = self._make_adapter(_read("press_release_detail.html"))
        item = DiscoveredItem(
            source_url=f"{BASE_URL}/en/media/press-releases/spectrum-2026",
            title="Spectrum 2026",
            published_at="2026-03-03",
            doc_type="press_release",
            language="en",
            metadata={"listing_url": SOURCE_URL_PR, "date_text": "MAR 03, 2026", "archetype": "article_list"},
        )
        candidates = list(adapter.fetch_and_extract(item))
        html_candidates = [c for c in candidates if c.content_type == "text/html"]
        assert len(html_candidates) == 1

    def test_html_page_extracts_embedded_docs(self):
        adapter = self._make_adapter(_read("press_release_detail.html"))
        item = DiscoveredItem(
            source_url=f"{BASE_URL}/en/media/press-releases/spectrum-2026",
            title="Spectrum 2026",
            published_at="2026-03-03",
            doc_type="press_release",
            language="en",
            metadata={"listing_url": SOURCE_URL_PR, "date_text": "MAR 03, 2026", "archetype": "article_list"},
        )
        candidates = list(adapter.fetch_and_extract(item))
        # HTML + PDF (Spectrum2026.pdf in content) + getattachment + btn PDF (deduped with content PDF)
        doc_candidates = [c for c in candidates if c.content_type != "text/html"]
        assert len(doc_candidates) >= 1

    def test_direct_pdf_url_yields_without_html_fetch(self):
        mock_http = MagicMock()
        adapter = McmcAdapter(config={"base_url": BASE_URL}, http=mock_http)
        item = DiscoveredItem(
            source_url=f"{BASE_URL}/docs/report.pdf",
            title="Report",
            published_at="2026-01-01",
            doc_type="report",
            language="en",
            metadata={"listing_url": SOURCE_URL_PR},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert len(candidates) == 1
        assert candidates[0].content_type == "application/pdf"
        mock_http.get.assert_not_called()

    def test_getattachment_url_yields_directly(self):
        mock_http = MagicMock()
        adapter = McmcAdapter(config={"base_url": BASE_URL}, http=mock_http)
        item = DiscoveredItem(
            source_url=f"{BASE_URL}/getattachment/abc-123/file.pdf.aspx",
            title="Attachment",
            published_at="2026-01-01",
            doc_type="report",
            language="en",
            metadata={"listing_url": SOURCE_URL_PR},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert len(candidates) == 1
        mock_http.get.assert_not_called()

    def test_listing_row_pdf_href_yielded(self):
        adapter = self._make_adapter(_read("press_release_detail.html"))
        item = DiscoveredItem(
            source_url=f"{BASE_URL}/en/media/press-releases/spectrum-2026",
            title="Spectrum 2026",
            published_at="2026-03-03",
            doc_type="press_release",
            language="en",
            metadata={
                "listing_url": SOURCE_URL_PR,
                "date_text": "MAR 03, 2026",
                "pdf_href": "/docs/listing-row.pdf",
                "archetype": "article_list",
            },
        )
        candidates = list(adapter.fetch_and_extract(item))
        urls = [c.url for c in candidates]
        assert any("listing-row.pdf" in u for u in urls)

    def test_http_error_yields_nothing(self):
        mock_http = MagicMock()
        mock_http.get.side_effect = Exception("Timeout")
        adapter = McmcAdapter(config={"base_url": BASE_URL}, http=mock_http)
        item = DiscoveredItem(
            source_url=f"{BASE_URL}/en/article",
            title="Test",
            published_at="",
            doc_type="other",
            language="en",
            metadata={},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates == []

    def test_title_from_detail_page_used(self):
        adapter = self._make_adapter(_read("press_release_detail.html"))
        item = DiscoveredItem(
            source_url=f"{BASE_URL}/en/media/press-releases/spectrum-2026",
            title="",
            published_at="",
            doc_type="press_release",
            language="en",
            metadata={"listing_url": SOURCE_URL_PR, "date_text": "MAR 03, 2026"},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert "Spectrum Allocation 2026" in candidates[0].title

    def test_published_at_from_detail_page(self):
        adapter = self._make_adapter(_read("press_release_detail.html"))
        item = DiscoveredItem(
            source_url=f"{BASE_URL}/en/media/press-releases/spectrum-2026",
            title="",
            published_at="",
            doc_type="press_release",
            language="en",
            metadata={"listing_url": SOURCE_URL_PR, "date_text": ""},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates[0].published_at == "2026-03-03"

    def test_date_text_fallback_from_metadata(self):
        # detail page with no date
        adapter = self._make_adapter("<html><body><h1>No Date</h1></body></html>")
        item = DiscoveredItem(
            source_url=f"{BASE_URL}/en/article",
            title="Test",
            published_at="",
            doc_type="other",
            language="en",
            metadata={"listing_url": SOURCE_URL_PR, "date_text": "MAR 03, 2026"},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates[0].published_at == "2026-03-03"


# ===================================================================
# McmcAdapter.extract_downloads()
# ===================================================================


class TestMcmcAdapterExtractDownloads:
    def test_returns_links_from_detail_page(self):
        adapter = McmcAdapter(config={"base_url": BASE_URL})
        html = _read("press_release_detail.html")
        links = adapter.extract_downloads(html, BASE_URL)
        assert len(links) >= 1

    def test_returns_links_from_dispute_page(self):
        adapter = McmcAdapter(config={"base_url": BASE_URL})
        html = _read("dispute_resolution.html")
        links = adapter.extract_downloads(html, BASE_URL)
        assert len(links) >= 7

    def test_combines_generic_and_specific(self):
        """The override should include both generic and MCMC-specific results."""
        adapter = McmcAdapter(config={"base_url": BASE_URL})
        html = """
        <html><body>
          <div class="contentZone">
            <a href="/docs/in-content.pdf">PDF</a>
          </div>
          <a class="btn" href="/docs/btn-only.pdf">Button PDF</a>
        </body></html>
        """
        links = adapter.extract_downloads(html, BASE_URL)
        urls = [l.url for l in links]
        assert any("in-content.pdf" in u for u in urls)
        assert any("btn-only.pdf" in u for u in urls)

    def test_no_duplicates(self):
        adapter = McmcAdapter(config={"base_url": BASE_URL})
        html = _read("press_release_detail.html")
        links = adapter.extract_downloads(html, BASE_URL)
        urls = [l.url for l in links]
        assert len(urls) == len(set(urls))
