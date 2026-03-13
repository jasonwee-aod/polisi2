"""Tests for IDFR HTML extractors using local fixtures."""
from pathlib import Path

import pytest

from idfr_scraper.extractor import (
    extract_article_body_listing,
    extract_press_listing,
    extract_publications_hub,
    extract_speeches_listing,
    extract_year_from_speeches_h1,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://www.idfr.gov.my"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── Press Release Listing ─────────────────────────────────────────────────────


class TestExtractPressListing:
    SOURCE = f"{BASE}/my/media-1/press"

    def test_extracts_four_pdf_entries(self):
        html = _read("press_listing.html")
        items = extract_press_listing(html, self.SOURCE)
        assert len(items) == 4

    def test_titles_extracted(self):
        html = _read("press_listing.html")
        items = extract_press_listing(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert any("AI@WORK" in t for t in titles)
        assert any("KAMPUNG ANGKAT MADANI" in t for t in titles)
        assert any("ANNUAL DINNER 2024" in t for t in titles)
        assert any("FORUM 2023" in t for t in titles)

    def test_hrefs_are_absolute(self):
        html = _read("press_listing.html")
        items = extract_press_listing(html, self.SOURCE)
        assert all(i["href"].startswith("https://") for i in items)

    def test_hrefs_end_in_pdf(self):
        html = _read("press_listing.html")
        items = extract_press_listing(html, self.SOURCE)
        assert all(i["href"].lower().endswith(".pdf") for i in items)

    def test_year_dates_extracted(self):
        html = _read("press_listing.html")
        items = extract_press_listing(html, self.SOURCE)
        date_texts = [i["date_text"] for i in items]
        assert "2025-01-01" in date_texts
        assert "2024-01-01" in date_texts
        assert "2023-01-01" in date_texts

    def test_no_duplicate_hrefs(self):
        html = _read("press_listing.html")
        items = extract_press_listing(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_source_url_preserved(self):
        html = _read("press_listing.html")
        items = extract_press_listing(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_non_pdf_links_excluded(self):
        html = _read("press_listing.html")
        items = extract_press_listing(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert not any("media-1/news" in h for h in hrefs)

    def test_empty_html_returns_empty_list(self):
        items = extract_press_listing("<html><body></body></html>", self.SOURCE)
        assert items == []

    def test_missing_article_body_returns_empty_list(self):
        html = "<html><body><p>No content area</p></body></html>"
        items = extract_press_listing(html, self.SOURCE)
        assert items == []


# ── Speeches Listing ──────────────────────────────────────────────────────────


class TestExtractSpeechesListing:
    SOURCE = f"{BASE}/my/media-1/speeches"

    def test_extracts_three_pdf_entries(self):
        html = _read("speeches_listing.html")
        items = extract_speeches_listing(html, self.SOURCE)
        assert len(items) == 3

    def test_header_row_excluded(self):
        html = _read("speeches_listing.html")
        items = extract_speeches_listing(html, self.SOURCE)
        titles = [i["title"] for i in items]
        # "No" and "Title" header values must not appear as items
        assert not any(t.lower() in ("no", "title", "tajuk") for t in titles)

    def test_titles_extracted(self):
        html = _read("speeches_listing.html")
        items = extract_speeches_listing(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert any("OPENING REMARKS" in t for t in titles)
        assert any("KEYNOTE ADDRESS" in t for t in titles)
        assert any("WELCOMING ADDRESS" in t for t in titles)

    def test_hrefs_are_absolute(self):
        html = _read("speeches_listing.html")
        items = extract_speeches_listing(html, self.SOURCE)
        assert all(i["href"].startswith("https://") for i in items)

    def test_hrefs_end_in_pdf(self):
        html = _read("speeches_listing.html")
        items = extract_speeches_listing(html, self.SOURCE)
        assert all(i["href"].lower().endswith(".pdf") for i in items)

    def test_date_from_parenthetical_in_title(self):
        html = _read("speeches_listing.html")
        items = extract_speeches_listing(html, self.SOURCE)
        item = next(i for i in items if "OPENING REMARKS" in i["title"])
        assert item["date_text"] == "2025-10-02"

    def test_date_from_strong_tag(self):
        html = _read("speeches_listing.html")
        items = extract_speeches_listing(html, self.SOURCE)
        item = next(i for i in items if "KEYNOTE ADDRESS" in i["title"])
        assert item["date_text"] == "2025-01-15"

    def test_year_fallback_when_no_date_found(self):
        html = _read("speeches_listing.html")
        items = extract_speeches_listing(html, self.SOURCE)
        item = next(i for i in items if "WELCOMING ADDRESS" in i["title"])
        # No date in title or strong text → falls back to year from H1
        assert item["date_text"] == "2025-01-01"

    def test_no_duplicate_hrefs(self):
        html = _read("speeches_listing.html")
        items = extract_speeches_listing(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_source_url_preserved(self):
        html = _read("speeches_listing.html")
        items = extract_speeches_listing(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_empty_html_returns_empty_list(self):
        items = extract_speeches_listing("<html><body></body></html>", self.SOURCE)
        assert items == []


class TestExtractYearFromSpeechesH1:
    def test_extracts_year_from_h1(self):
        html = _read("speeches_listing.html")
        year = extract_year_from_speeches_h1(html)
        assert year == "2025"

    def test_returns_empty_when_no_h1(self):
        html = "<html><body><p>No h1 here</p></body></html>"
        year = extract_year_from_speeches_h1(html)
        assert year == ""

    def test_extracts_year_from_different_format(self):
        html = """<html><head></head><body>
          <h1 itemprop="headline">Speeches in 2023</h1>
        </body></html>"""
        year = extract_year_from_speeches_h1(html)
        assert year == "2023"


# ── Publications Hub ──────────────────────────────────────────────────────────


class TestExtractPublicationsHub:
    SOURCE = f"{BASE}/my/publications"

    def test_extracts_three_entries(self):
        html = _read("publications_hub.html")
        items = extract_publications_hub(html, self.SOURCE)
        assert len(items) == 3

    def test_titles_extracted(self):
        html = _read("publications_hub.html")
        items = extract_publications_hub(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert any("Prospectus 2026" in t for t in titles)
        assert any("Annual Report 2024" in t for t in titles)
        assert any("Newsletter" in t for t in titles)

    def test_pdf_items_flagged(self):
        html = _read("publications_hub.html")
        items = extract_publications_hub(html, self.SOURCE)
        pdf_items = [i for i in items if i["is_pdf"]]
        assert len(pdf_items) == 2  # Prospectus + Annual Report

    def test_subpage_items_not_flagged_as_pdf(self):
        html = _read("publications_hub.html")
        items = extract_publications_hub(html, self.SOURCE)
        subpage_items = [i for i in items if not i["is_pdf"]]
        assert len(subpage_items) == 1  # Newsletter

    def test_hrefs_are_absolute(self):
        html = _read("publications_hub.html")
        items = extract_publications_hub(html, self.SOURCE)
        assert all(i["href"].startswith("https://") for i in items)

    def test_no_duplicate_hrefs(self):
        html = _read("publications_hub.html")
        items = extract_publications_hub(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_source_url_preserved(self):
        html = _read("publications_hub.html")
        items = extract_publications_hub(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_empty_html_returns_empty_list(self):
        items = extract_publications_hub("<html><body></body></html>", self.SOURCE)
        assert items == []


# ── Generic Article Body Listing ──────────────────────────────────────────────


class TestExtractArticleBodyListing:
    SOURCE = f"{BASE}/my/publication/newsletters"

    def test_extracts_three_pdf_entries(self):
        html = _read("article_body_listing.html")
        items = extract_article_body_listing(html, self.SOURCE)
        assert len(items) == 3

    def test_titles_extracted(self):
        html = _read("article_body_listing.html")
        items = extract_article_body_listing(html, self.SOURCE)
        titles = [i["title"] for i in items]
        assert any("Vol. 15 No. 1" in t for t in titles)
        assert any("Vol. 14 No. 2" in t for t in titles)

    def test_hrefs_are_absolute(self):
        html = _read("article_body_listing.html")
        items = extract_article_body_listing(html, self.SOURCE)
        assert all(i["href"].startswith("https://") for i in items)

    def test_hrefs_end_in_pdf(self):
        html = _read("article_body_listing.html")
        items = extract_article_body_listing(html, self.SOURCE)
        assert all(i["href"].lower().endswith(".pdf") for i in items)

    def test_non_pdf_links_excluded(self):
        html = _read("article_body_listing.html")
        items = extract_article_body_listing(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert not any("media-1/news" in h for h in hrefs)

    def test_no_duplicate_hrefs(self):
        html = _read("article_body_listing.html")
        items = extract_article_body_listing(html, self.SOURCE)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_source_url_preserved(self):
        html = _read("article_body_listing.html")
        items = extract_article_body_listing(html, self.SOURCE)
        assert all(i["source_url"] == self.SOURCE for i in items)

    def test_relative_link_made_absolute(self):
        html = """<html><body>
          <div itemprop="articleBody">
            <a href="/my/images/stories/newsletter/test.pdf">Newsletter</a>
          </div>
        </body></html>"""
        items = extract_article_body_listing(html, self.SOURCE)
        assert len(items) == 1
        assert items[0]["href"] == f"{BASE}/my/images/stories/newsletter/test.pdf"

    def test_image_link_title_from_tr_ancestor(self):
        """Image-based links (<a><img/></a>) get their title from the <tr> row text."""
        html = """<html><body>
          <div itemprop="articleBody">
            <table><tbody>
              <tr>
                <td>1. Newsletter | Let&#39;s Talk: Human Rights -</td>
                <td><a href="/images/e-newsletters/lets_talk.pdf"><img src="pdf.png"/></a></td>
              </tr>
            </tbody></table>
          </div>
        </body></html>"""
        items = extract_article_body_listing(html, self.SOURCE)
        assert len(items) == 1
        assert "Let" in items[0]["title"]
        assert "Human Rights" in items[0]["title"]
        # Should not start with "1. " number prefix
        assert not items[0]["title"].startswith("1.")
        # Should not end with " -"
        assert not items[0]["title"].endswith(" -")

    def test_image_link_jdfr_title_from_tr_ancestor(self):
        """JDFR journal image links get clean titles from <tr> ancestor."""
        html = """<html><body>
          <div itemprop="articleBody">
            <table><tbody>
              <tr>
                <td>3. JDFR Volume 21 Number 1, November 2024 -</td>
                <td><a href="/my/images/JDFR/JDFR_vol21.pdf"><img src="pdf.png"/></a></td>
              </tr>
            </tbody></table>
          </div>
        </body></html>"""
        items = extract_article_body_listing(html, self.SOURCE)
        assert len(items) == 1
        assert "JDFR Volume 21" in items[0]["title"]
        assert not items[0]["title"].startswith("3.")
        assert not items[0]["title"].endswith(" -")

    def test_empty_html_returns_empty_list(self):
        items = extract_article_body_listing("<html><body></body></html>", self.SOURCE)
        assert items == []
