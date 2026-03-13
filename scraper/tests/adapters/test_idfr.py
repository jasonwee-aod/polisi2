"""Tests for the IDFR adapter — Joomla 4, four page archetypes.

Covers:
  - Press release listing discovery
  - Speech listing discovery (date from parenthetical, strong tag, year fallback)
  - Publications hub discovery (direct PDF + sub-listing pages)
  - Article body listing discovery (newsletters, JDFR, image-link titles)
  - Date parsing helpers
  - Pagination across multiple speech pages
  - since date filtering
  - fetch_and_extract()
  - Helper functions: _is_doc_link, _extract_year_from_speeches_h1, _since_filter
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
from bs4 import BeautifulSoup

from polisi_scraper.adapters.idfr import (
    IdfrAdapter,
    _extract_speech_date,
    _extract_year_from_speeches_h1,
    _is_doc_link,
    _is_speech_header_row,
    _since_filter,
)
from polisi_scraper.adapters.base import DiscoveredItem, DocumentCandidate, HTTPClient

FIXTURES = Path(__file__).parent.parent / "fixtures" / "idfr"
BASE = "https://www.idfr.gov.my"
ALLOWED_HOSTS = frozenset({"www.idfr.gov.my", "idfr.gov.my"})


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _mock_http(html_by_url: dict[str, str] | None = None) -> MagicMock:
    """Build a mock HTTPClient returning HTML based on URL."""
    http = MagicMock(spec=HTTPClient)

    def fake_get(url, **kwargs):
        resp = MagicMock()
        if html_by_url and url in html_by_url:
            resp.text = html_by_url[url]
        else:
            resp.text = "<html><body></body></html>"
        return resp

    http.get.side_effect = fake_get
    return http


def _make_adapter(config: dict, http: MagicMock | None = None) -> IdfrAdapter:
    adapter = IdfrAdapter.__new__(IdfrAdapter)
    adapter.config = config
    adapter.http = http or _mock_http()
    adapter.state = None
    adapter.archiver = None
    adapter.browser_pool = None
    return adapter


# ── Section configs ───────────────────────────────────────────────────────

_PRESS_SECTION = {
    "name": "press_releases",
    "source_type": "press_listing",
    "doc_type": "press_release",
    "language": "en",
    "listing_url": f"{BASE}/my/media-1/press",
}

_SPEECHES_SECTION = {
    "name": "speeches",
    "source_type": "speeches_listing",
    "doc_type": "speech",
    "language": "en",
    "listing_urls": [f"{BASE}/my/media-1/speeches-2025"],
}

_PUBLICATIONS_SECTION = {
    "name": "publications",
    "source_type": "publications_hub",
    "doc_type": "publication",
    "language": "en",
    "hub_url": f"{BASE}/my/publications",
}

_ARTICLE_BODY_SECTION = {
    "name": "newsletters",
    "source_type": "article_body_listing",
    "doc_type": "publication",
    "language": "en",
    "listing_url": f"{BASE}/my/publication/newsletters",
}


# ═══════════════════════════════════════════════════════════════════════════
# Helper: _is_doc_link
# ═══════════════════════════════════════════════════════════════════════════


class TestIsDocLink:
    @pytest.mark.parametrize("href", [
        "/uploads/report.pdf",
        "/uploads/form.docx",
        "/uploads/data.xlsx",
        "/uploads/slides.pptx",
        "/uploads/archive.zip",
        "/uploads/REPORT.PDF",
    ])
    def test_document_extensions_recognized(self, href):
        assert _is_doc_link(href) is True

    @pytest.mark.parametrize("href", [
        "/my/media-1/news",
        "/page.html",
        "/images/photo.jpg",
        "#section",
        "javascript:void(0)",
    ])
    def test_non_document_extensions_rejected(self, href):
        assert _is_doc_link(href) is False


# ═══════════════════════════════════════════════════════════════════════════
# Helper: _extract_year_from_speeches_h1
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractYearFromSpeechesH1:
    def test_extracts_year_from_fixture(self):
        html = _read("speeches_listing.html")
        soup = BeautifulSoup(html, "lxml")
        assert _extract_year_from_speeches_h1(soup) == "2025"

    def test_returns_empty_when_no_h1(self):
        soup = BeautifulSoup("<html><body><p>No h1</p></body></html>", "lxml")
        assert _extract_year_from_speeches_h1(soup) == ""

    def test_extracts_from_different_year(self):
        html = '<html><body><h1 itemprop="headline">Speeches in 2023</h1></body></html>'
        soup = BeautifulSoup(html, "lxml")
        assert _extract_year_from_speeches_h1(soup) == "2023"

    def test_no_year_in_h1_text(self):
        html = '<html><body><h1 itemprop="headline">Speeches</h1></body></html>'
        soup = BeautifulSoup(html, "lxml")
        assert _extract_year_from_speeches_h1(soup) == ""


# ═══════════════════════════════════════════════════════════════════════════
# Helper: _extract_speech_date
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractSpeechDate:
    def test_parenthetical_date(self):
        result = _extract_speech_date("Opening Remarks (Oct 2, 2025)", [], "2025")
        assert result == "2025-10-02"

    def test_date_from_strong_text(self):
        result = _extract_speech_date("Keynote Address", ["15 January 2025"], "2025")
        assert result == "2025-01-15"

    def test_year_fallback(self):
        result = _extract_speech_date("Some Speech", [], "2025")
        assert result == "2025-01-01"

    def test_no_fallback_year(self):
        result = _extract_speech_date("Some Speech", [], "")
        assert result == ""

    def test_parenthetical_takes_priority(self):
        result = _extract_speech_date(
            "Speech (Oct 2, 2025)", ["15 January 2025"], "2024"
        )
        assert result == "2025-10-02"


# ═══════════════════════════════════════════════════════════════════════════
# Helper: _is_speech_header_row
# ═══════════════════════════════════════════════════════════════════════════


class TestIsSpeechHeaderRow:
    @pytest.mark.parametrize("text", ["No", "no", "Title", "Tajuk", "No.", "#"])
    def test_header_values_detected(self, text):
        soup = BeautifulSoup(f"<table><tr><td>{text}</td><td>Heading</td></tr></table>", "lxml")
        cells = soup.find("tr").find_all("td")
        assert _is_speech_header_row(cells) is True

    def test_data_row_not_header(self):
        soup = BeautifulSoup("<table><tr><td>1</td><td>Data</td></tr></table>", "lxml")
        cells = soup.find("tr").find_all("td")
        assert _is_speech_header_row(cells) is False

    def test_empty_cells_not_header(self):
        assert _is_speech_header_row([]) is False


# ═══════════════════════════════════════════════════════════════════════════
# Helper: _since_filter
# ═══════════════════════════════════════════════════════════════════════════


class TestSinceFilter:
    def test_before_since_returns_true(self):
        assert _since_filter("2023-01-01", date(2024, 1, 1)) is True

    def test_on_since_returns_false(self):
        assert _since_filter("2024-01-01", date(2024, 1, 1)) is False

    def test_after_since_returns_false(self):
        assert _since_filter("2025-01-01", date(2024, 1, 1)) is False

    def test_no_since_returns_false(self):
        assert _since_filter("2020-01-01", None) is False

    def test_empty_date_returns_false(self):
        assert _since_filter("", date(2024, 1, 1)) is False

    def test_invalid_date_returns_false(self):
        assert _since_filter("not-a-date", date(2024, 1, 1)) is False


# ═══════════════════════════════════════════════════════════════════════════
# Press Release Listing
# ═══════════════════════════════════════════════════════════════════════════


class TestDiscoverPressListing:
    def test_extracts_four_pdf_entries(self):
        html = _read("press_listing.html")
        http = _mock_http({_PRESS_SECTION["listing_url"]: html})
        config = {"sections": [_PRESS_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        assert len(items) == 4

    def test_titles_extracted(self):
        html = _read("press_listing.html")
        http = _mock_http({_PRESS_SECTION["listing_url"]: html})
        config = {"sections": [_PRESS_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        titles = [i.title for i in items]
        assert any("AI@WORK" in t for t in titles)
        assert any("KAMPUNG ANGKAT MADANI" in t for t in titles)
        assert any("ANNUAL DINNER 2024" in t for t in titles)
        assert any("FORUM 2023" in t for t in titles)

    def test_hrefs_are_absolute(self):
        html = _read("press_listing.html")
        http = _mock_http({_PRESS_SECTION["listing_url"]: html})
        config = {"sections": [_PRESS_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        assert all(i.source_url.startswith("https://") for i in items)

    def test_hrefs_end_in_pdf(self):
        html = _read("press_listing.html")
        http = _mock_http({_PRESS_SECTION["listing_url"]: html})
        config = {"sections": [_PRESS_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        assert all(i.source_url.lower().endswith(".pdf") for i in items)

    def test_year_dates_assigned(self):
        html = _read("press_listing.html")
        http = _mock_http({_PRESS_SECTION["listing_url"]: html})
        config = {"sections": [_PRESS_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        dates = [i.published_at for i in items]
        assert "2025-01-01" in dates
        assert "2024-01-01" in dates
        assert "2023-01-01" in dates

    def test_no_duplicate_hrefs(self):
        html = _read("press_listing.html")
        http = _mock_http({_PRESS_SECTION["listing_url"]: html})
        config = {"sections": [_PRESS_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        urls = [i.source_url for i in items]
        assert len(urls) == len(set(urls))

    def test_non_pdf_links_excluded(self):
        html = _read("press_listing.html")
        http = _mock_http({_PRESS_SECTION["listing_url"]: html})
        config = {"sections": [_PRESS_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        urls = [i.source_url for i in items]
        assert not any("media-1/news" in u for u in urls)

    def test_empty_html_returns_empty(self):
        http = _mock_http({_PRESS_SECTION["listing_url"]: "<html><body></body></html>"})
        config = {"sections": [_PRESS_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        assert items == []

    def test_missing_listing_url_returns_empty(self):
        section = {**_PRESS_SECTION, "listing_url": ""}
        config = {"sections": [section]}
        adapter = _make_adapter(config, _mock_http())
        items = list(adapter.discover())
        assert items == []

    def test_metadata_contains_listing_url(self):
        html = _read("press_listing.html")
        http = _mock_http({_PRESS_SECTION["listing_url"]: html})
        config = {"sections": [_PRESS_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        assert all(i.metadata.get("listing_url") == _PRESS_SECTION["listing_url"] for i in items)

    def test_since_filtering(self):
        html = _read("press_listing.html")
        http = _mock_http({_PRESS_SECTION["listing_url"]: html})
        config = {"sections": [_PRESS_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        # Filter out 2023 items
        items = list(adapter.discover(since=date(2024, 1, 1)))
        dates = [i.published_at for i in items]
        assert "2023-01-01" not in dates


# ═══════════════════════════════════════════════════════════════════════════
# Speeches Listing
# ═══════════════════════════════════════════════════════════════════════════


class TestDiscoverSpeechesListing:
    def test_extracts_three_entries(self):
        html = _read("speeches_listing.html")
        url = _SPEECHES_SECTION["listing_urls"][0]
        http = _mock_http({url: html})
        config = {"sections": [_SPEECHES_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        assert len(items) == 3

    def test_header_row_excluded(self):
        html = _read("speeches_listing.html")
        url = _SPEECHES_SECTION["listing_urls"][0]
        http = _mock_http({url: html})
        config = {"sections": [_SPEECHES_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        titles = [i.title for i in items]
        assert not any(t.lower() in ("no", "title", "tajuk") for t in titles)

    def test_titles_extracted(self):
        html = _read("speeches_listing.html")
        url = _SPEECHES_SECTION["listing_urls"][0]
        http = _mock_http({url: html})
        config = {"sections": [_SPEECHES_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        titles = [i.title for i in items]
        assert any("OPENING REMARKS" in t for t in titles)
        assert any("KEYNOTE ADDRESS" in t for t in titles)
        assert any("WELCOMING ADDRESS" in t for t in titles)

    def test_hrefs_are_absolute_and_pdf(self):
        html = _read("speeches_listing.html")
        url = _SPEECHES_SECTION["listing_urls"][0]
        http = _mock_http({url: html})
        config = {"sections": [_SPEECHES_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        assert all(i.source_url.startswith("https://") for i in items)
        assert all(i.source_url.lower().endswith(".pdf") for i in items)

    def test_date_from_parenthetical(self):
        html = _read("speeches_listing.html")
        url = _SPEECHES_SECTION["listing_urls"][0]
        http = _mock_http({url: html})
        config = {"sections": [_SPEECHES_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        item = next(i for i in items if "OPENING REMARKS" in i.title)
        assert item.published_at == "2025-10-02"

    def test_date_from_strong_tag(self):
        html = _read("speeches_listing.html")
        url = _SPEECHES_SECTION["listing_urls"][0]
        http = _mock_http({url: html})
        config = {"sections": [_SPEECHES_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        item = next(i for i in items if "KEYNOTE ADDRESS" in i.title)
        assert item.published_at == "2025-01-15"

    def test_year_fallback_when_no_explicit_date(self):
        """Speech with no explicit date gets a 2025-based date (from strong text
        or year fallback).  The exact day depends on fuzzy parsing of the strong
        text 'IDFR ANNUAL PROGRAMME LAUNCH 2025', so we only assert the year."""
        html = _read("speeches_listing.html")
        url = _SPEECHES_SECTION["listing_urls"][0]
        http = _mock_http({url: html})
        config = {"sections": [_SPEECHES_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        item = next(i for i in items if "WELCOMING ADDRESS" in i.title)
        assert item.published_at.startswith("2025-")

    def test_no_duplicate_hrefs(self):
        html = _read("speeches_listing.html")
        url = _SPEECHES_SECTION["listing_urls"][0]
        http = _mock_http({url: html})
        config = {"sections": [_SPEECHES_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        urls = [i.source_url for i in items]
        assert len(urls) == len(set(urls))

    def test_empty_html_returns_empty(self):
        url = _SPEECHES_SECTION["listing_urls"][0]
        http = _mock_http({url: "<html><body></body></html>"})
        config = {"sections": [_SPEECHES_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        assert items == []

    def test_multiple_listing_urls(self):
        """Speeches section with multiple year pages."""
        html = _read("speeches_listing.html")
        url1 = f"{BASE}/my/media-1/speeches-2025"
        url2 = f"{BASE}/my/media-1/speeches-2024"
        section = {
            **_SPEECHES_SECTION,
            "listing_urls": [url1, url2],
        }
        http = _mock_http({url1: html, url2: html})
        config = {"sections": [section], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        # 3 from each page, but dedup is per-page so could be 6
        assert len(items) == 6

    def test_listing_url_fallback_to_singular(self):
        """If listing_urls is missing, falls back to listing_url."""
        html = _read("speeches_listing.html")
        section = {
            "name": "speeches",
            "source_type": "speeches_listing",
            "doc_type": "speech",
            "language": "en",
            "listing_url": f"{BASE}/my/media-1/speeches-2025",
        }
        http = _mock_http({section["listing_url"]: html})
        config = {"sections": [section], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        assert len(items) == 3

    def test_missing_listing_urls_returns_empty(self):
        section = {
            "name": "speeches",
            "source_type": "speeches_listing",
            "doc_type": "speech",
            "language": "en",
        }
        config = {"sections": [section]}
        adapter = _make_adapter(config, _mock_http())
        items = list(adapter.discover())
        assert items == []

    def test_since_filtering_speeches(self):
        html = _read("speeches_listing.html")
        url = _SPEECHES_SECTION["listing_urls"][0]
        http = _mock_http({url: html})
        config = {"sections": [_SPEECHES_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        # Everything in fixture is 2025; filtering at 2026 should exclude all
        items = list(adapter.discover(since=date(2026, 1, 1)))
        assert len(items) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Publications Hub
# ═══════════════════════════════════════════════════════════════════════════


class TestDiscoverPublicationsHub:
    def test_extracts_direct_pdfs(self):
        hub_html = _read("publications_hub.html")
        http = _mock_http({
            _PUBLICATIONS_SECTION["hub_url"]: hub_html,
            # Newsletter sub-page will be fetched
            f"{BASE}/my/publication/newsletters": _read("article_body_listing.html"),
        })
        config = {"sections": [_PUBLICATIONS_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        pdf_items = [i for i in items if i.source_url.lower().endswith(".pdf")]
        assert len(pdf_items) >= 2  # Prospectus + Annual Report + newsletter PDFs

    def test_hub_titles_extracted(self):
        hub_html = _read("publications_hub.html")
        http = _mock_http({
            _PUBLICATIONS_SECTION["hub_url"]: hub_html,
            f"{BASE}/my/publication/newsletters": _read("article_body_listing.html"),
        })
        config = {"sections": [_PUBLICATIONS_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        titles = [i.title for i in items]
        assert any("Prospectus 2026" in t for t in titles)
        assert any("Annual Report 2024" in t for t in titles)

    def test_sub_page_crawled(self):
        """Newsletter sub-listing page should be fetched and its PDFs yielded."""
        hub_html = _read("publications_hub.html")
        newsletter_html = _read("article_body_listing.html")
        newsletter_url = f"{BASE}/my/publication/newsletters"
        http = _mock_http({
            _PUBLICATIONS_SECTION["hub_url"]: hub_html,
            newsletter_url: newsletter_html,
        })
        config = {"sections": [_PUBLICATIONS_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        # Should include newsletter PDFs from sub-page
        newsletter_items = [i for i in items if "Newsletter" in i.title or "newsletter" in i.source_url]
        assert len(newsletter_items) >= 1

    def test_missing_hub_url_returns_empty(self):
        section = {**_PUBLICATIONS_SECTION, "hub_url": ""}
        config = {"sections": [section]}
        adapter = _make_adapter(config, _mock_http())
        items = list(adapter.discover())
        assert items == []

    def test_empty_hub_returns_empty(self):
        http = _mock_http({_PUBLICATIONS_SECTION["hub_url"]: "<html><body></body></html>"})
        config = {"sections": [_PUBLICATIONS_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        assert items == []


# ═══════════════════════════════════════════════════════════════════════════
# Article Body Listing
# ═══════════════════════════════════════════════════════════════════════════


class TestDiscoverArticleBodyListing:
    def test_extracts_three_pdf_entries(self):
        html = _read("article_body_listing.html")
        http = _mock_http({_ARTICLE_BODY_SECTION["listing_url"]: html})
        config = {"sections": [_ARTICLE_BODY_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        assert len(items) == 3

    def test_titles_extracted(self):
        html = _read("article_body_listing.html")
        http = _mock_http({_ARTICLE_BODY_SECTION["listing_url"]: html})
        config = {"sections": [_ARTICLE_BODY_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        titles = [i.title for i in items]
        assert any("Vol. 15 No. 1" in t for t in titles)
        assert any("Vol. 14 No. 2" in t for t in titles)

    def test_hrefs_are_absolute_and_pdf(self):
        html = _read("article_body_listing.html")
        http = _mock_http({_ARTICLE_BODY_SECTION["listing_url"]: html})
        config = {"sections": [_ARTICLE_BODY_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        assert all(i.source_url.startswith("https://") for i in items)
        assert all(i.source_url.lower().endswith(".pdf") for i in items)

    def test_non_pdf_links_excluded(self):
        html = _read("article_body_listing.html")
        http = _mock_http({_ARTICLE_BODY_SECTION["listing_url"]: html})
        config = {"sections": [_ARTICLE_BODY_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        urls = [i.source_url for i in items]
        assert not any("media-1/news" in u for u in urls)

    def test_no_duplicate_hrefs(self):
        html = _read("article_body_listing.html")
        http = _mock_http({_ARTICLE_BODY_SECTION["listing_url"]: html})
        config = {"sections": [_ARTICLE_BODY_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        urls = [i.source_url for i in items]
        assert len(urls) == len(set(urls))

    def test_relative_link_made_absolute(self):
        html = """<html><body>
          <div itemprop="articleBody">
            <a href="/my/images/stories/newsletter/test.pdf">Newsletter</a>
          </div>
        </body></html>"""
        listing_url = f"{BASE}/my/publication/newsletters"
        http = _mock_http({listing_url: html})
        config = {"sections": [_ARTICLE_BODY_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        assert len(items) == 1
        assert items[0].source_url == f"{BASE}/my/images/stories/newsletter/test.pdf"

    def test_image_link_title_from_tr_ancestor(self):
        """Image-only link gets title from <tr> row text."""
        html = """<html><body>
          <div itemprop="articleBody">
            <table><tbody>
              <tr>
                <td>1. Newsletter | Let's Talk: Human Rights -</td>
                <td><a href="/images/e-newsletters/lets_talk.pdf"><img src="pdf.png"/></a></td>
              </tr>
            </tbody></table>
          </div>
        </body></html>"""
        listing_url = f"{BASE}/my/publication/newsletters"
        http = _mock_http({listing_url: html})
        config = {"sections": [_ARTICLE_BODY_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        assert len(items) == 1
        assert "Human Rights" in items[0].title
        assert not items[0].title.startswith("1.")

    def test_empty_html_returns_empty(self):
        listing_url = _ARTICLE_BODY_SECTION["listing_url"]
        http = _mock_http({listing_url: "<html><body></body></html>"})
        config = {"sections": [_ARTICLE_BODY_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        assert items == []

    def test_missing_listing_url_returns_empty(self):
        section = {**_ARTICLE_BODY_SECTION, "listing_url": ""}
        config = {"sections": [section]}
        adapter = _make_adapter(config, _mock_http())
        items = list(adapter.discover())
        assert items == []


# ═══════════════════════════════════════════════════════════════════════════
# fetch_and_extract()
# ═══════════════════════════════════════════════════════════════════════════


class TestFetchAndExtract:
    def test_yields_document_candidate(self):
        adapter = _make_adapter({})
        item = DiscoveredItem(
            source_url=f"{BASE}/my/images/stories/press/test.pdf",
            title="Test Press Release",
            published_at="2025-01-01",
            doc_type="press_release",
            language="en",
            metadata={"listing_url": f"{BASE}/my/media-1/press"},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert len(candidates) == 1
        assert isinstance(candidates[0], DocumentCandidate)

    def test_content_type_inferred(self):
        adapter = _make_adapter({})
        item = DiscoveredItem(
            source_url=f"{BASE}/my/images/stories/press/test.pdf",
            title="Test",
            metadata={},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates[0].content_type == "application/pdf"

    def test_source_page_url_from_metadata(self):
        adapter = _make_adapter({})
        item = DiscoveredItem(
            source_url=f"{BASE}/my/images/stories/press/test.pdf",
            title="Test",
            metadata={"listing_url": f"{BASE}/my/media-1/press"},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates[0].source_page_url == f"{BASE}/my/media-1/press"

    def test_preserves_item_fields(self):
        adapter = _make_adapter({})
        item = DiscoveredItem(
            source_url=f"{BASE}/my/images/test.pdf",
            title="My Title",
            published_at="2025-06-15",
            doc_type="speech",
            language="en",
            metadata={},
        )
        candidates = list(adapter.fetch_and_extract(item))
        c = candidates[0]
        assert c.title == "My Title"
        assert c.published_at == "2025-06-15"
        assert c.doc_type == "speech"
        assert c.language == "en"


# ═══════════════════════════════════════════════════════════════════════════
# Error handling
# ═══════════════════════════════════════════════════════════════════════════


class TestErrorHandling:
    def test_http_error_graceful(self):
        http = MagicMock(spec=HTTPClient)
        http.get.side_effect = Exception("Connection refused")
        config = {"sections": [_PRESS_SECTION], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        assert items == []

    def test_no_sections(self):
        adapter = _make_adapter({}, _mock_http())
        items = list(adapter.discover())
        assert items == []

    def test_unknown_source_type_uses_article_body(self):
        """Unknown source_type defaults to article_body_listing."""
        html = _read("article_body_listing.html")
        section = {
            "name": "unknown",
            "source_type": "something_else",
            "doc_type": "other",
            "language": "en",
            "listing_url": f"{BASE}/my/publication/newsletters",
        }
        http = _mock_http({section["listing_url"]: html})
        config = {"sections": [section], "allowed_hosts": list(ALLOWED_HOSTS)}
        adapter = _make_adapter(config, http)
        items = list(adapter.discover())
        # Falls through to article_body_listing (the else branch)
        assert len(items) == 3


# ═══════════════════════════════════════════════════════════════════════════
# Adapter properties
# ═══════════════════════════════════════════════════════════════════════════


class TestAdapterProperties:
    def test_slug(self):
        assert IdfrAdapter.slug == "idfr"

    def test_agency(self):
        assert "IDFR" in IdfrAdapter.agency

    def test_requires_browser_false(self):
        assert IdfrAdapter.requires_browser is False
