"""
Integration tests for MCMC HTML extractors using saved fixtures.
"""
from pathlib import Path

import pytest

from mcmc_scraper.extractor import (
    extract_acts_hub_items,
    extract_article_list_items,
    extract_article_meta,
    extract_embedded_doc_links,
    extract_media_box_items,
    get_next_page_number,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── article_list extractor ────────────────────────────────────────────────────


class TestExtractArticleListItems:
    def setup_method(self):
        self.html = _read("press_releases_listing.html")
        self.source = "https://mcmc.gov.my/en/media/press-releases?page=1"

    def test_returns_two_items(self):
        items = extract_article_list_items(self.html, self.source)
        assert len(items) == 2

    def test_first_item_title(self):
        items = extract_article_list_items(self.html, self.source)
        assert "Spectrum Allocation 2026" in items[0]["title"]

    def test_first_item_href(self):
        items = extract_article_list_items(self.html, self.source)
        assert items[0]["href"] == "/en/media/press-releases/mcmc-statement-spectrum-2026"

    def test_first_item_date(self):
        items = extract_article_list_items(self.html, self.source)
        assert items[0]["date_text"] == "MAR 03, 2026"

    def test_first_item_pdf_href(self):
        items = extract_article_list_items(self.html, self.source)
        assert items[0]["pdf_href"].endswith("Spectrum2026.pdf")

    def test_second_item_no_pdf_on_listing(self):
        items = extract_article_list_items(self.html, self.source)
        assert items[1]["pdf_href"] == ""

    def test_second_item_date(self):
        items = extract_article_list_items(self.html, self.source)
        assert items[1]["date_text"] == "FEB 15, 2026"

    def test_no_duplicate_hrefs(self):
        items = extract_article_list_items(self.html, self.source)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))


# ── media_box extractor ───────────────────────────────────────────────────────


class TestExtractMediaBoxItems:
    def setup_method(self):
        self.html = _read("publications_listing.html")
        self.source = "https://mcmc.gov.my/en/resources/publications?page=1"

    def test_returns_three_items(self):
        items = extract_media_box_items(self.html, self.source)
        assert len(items) == 3

    def test_titles_extracted(self):
        items = extract_media_box_items(self.html, self.source)
        titles = [i["title"] for i in items]
        assert "Industry Performance Report 2025" in titles
        assert "National Broadband Survey 2024" in titles
        assert "Spectrum Outlook 2025" in titles

    def test_hrefs_extracted(self):
        items = extract_media_box_items(self.html, self.source)
        hrefs = [i["href"] for i in items]
        assert "/en/resources/publications/industry-performance-report-2025" in hrefs

    def test_date_text_empty(self):
        """media_box items don't have dates on the listing page."""
        items = extract_media_box_items(self.html, self.source)
        for item in items:
            assert item["date_text"] == ""

    def test_no_duplicate_hrefs(self):
        items = extract_media_box_items(self.html, self.source)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))


# ── pagination ────────────────────────────────────────────────────────────────


class TestGetNextPageNumber:
    def test_returns_next_page_when_available(self):
        html = _read("press_releases_listing.html")
        # Active is page 1, page 2 exists → returns 2
        result = get_next_page_number(html)
        assert result == 2

    def test_returns_none_on_last_page(self):
        html = _read("press_releases_listing_last_page.html")
        # Active is page 3, no page 4 in pagination → returns None
        result = get_next_page_number(html)
        assert result is None

    def test_returns_none_when_no_pagination(self):
        html = "<html><body><p>No pagination here</p></body></html>"
        assert get_next_page_number(html) is None

    def test_publications_last_page(self):
        html = _read("publications_listing.html")
        # Only page 1, disabled next → returns None
        result = get_next_page_number(html)
        assert result is None


# ── article_meta extractor ────────────────────────────────────────────────────


class TestExtractArticleMeta:
    def setup_method(self):
        self.html = _read("press_release_detail.html")
        self.source = "https://mcmc.gov.my/en/media/press-releases/mcmc-statement-spectrum-2026"

    def test_extracts_title(self):
        meta = extract_article_meta(self.html, self.source)
        assert "Spectrum Allocation 2026" in meta["title"]

    def test_extracts_date_from_date_div(self):
        meta = extract_article_meta(self.html, self.source)
        assert meta["published_at"] == "2026-03-03"

    def test_title_not_empty(self):
        meta = extract_article_meta(self.html, self.source)
        assert meta["title"] != ""

    def test_returns_dict_with_required_keys(self):
        meta = extract_article_meta(self.html, self.source)
        assert "title" in meta
        assert "published_at" in meta


# ── embedded doc links extractor ──────────────────────────────────────────────


class TestExtractEmbeddedDocLinks:
    def setup_method(self):
        self.html = _read("press_release_detail.html")
        self.base = "https://mcmc.gov.my"

    def test_finds_pdf_in_content(self):
        links = extract_embedded_doc_links(self.html, self.base)
        pdf_links = [l for l in links if ".pdf" in l.lower()]
        assert any("Spectrum2026.pdf" in l for l in pdf_links)

    def test_finds_getattachment_link(self):
        links = extract_embedded_doc_links(self.html, self.base)
        attach_links = [l for l in links if "/getattachment/" in l]
        assert len(attach_links) >= 1

    def test_no_duplicates(self):
        links = extract_embedded_doc_links(self.html, self.base)
        assert len(links) == len(set(links))

    def test_all_links_are_absolute(self):
        links = extract_embedded_doc_links(self.html, self.base)
        for link in links:
            assert link.startswith("http"), f"Not absolute: {link}"


# ── acts_hub extractor ────────────────────────────────────────────────────────


class TestExtractActsHubItems:
    def setup_method(self):
        self.html = _read("acts_hub.html")
        self.source = "https://mcmc.gov.my/en/legal/acts"

    def test_returns_four_items(self):
        items = extract_acts_hub_items(self.html, self.source)
        assert len(items) == 4

    def test_first_item_title(self):
        items = extract_acts_hub_items(self.html, self.source)
        assert "Communications and Multimedia (Amendment) Act 2025" in items[0]["title"]

    def test_first_item_has_detail_href(self):
        items = extract_acts_hub_items(self.html, self.source)
        assert "/en/legal/acts/communications-and-multimedia-amendment-act-2025" in items[0]["detail_href"]

    def test_first_item_has_one_doc_href(self):
        items = extract_acts_hub_items(self.html, self.source)
        assert len(items[0]["doc_hrefs"]) == 1
        assert items[0]["doc_hrefs"][0].endswith(".pdf")

    def test_second_item_act_588(self):
        items = extract_acts_hub_items(self.html, self.source)
        assert "Act 588" in items[1]["title"]
        assert items[1]["detail_href"] != ""
        assert any("Act588" in h for h in items[1]["doc_hrefs"])

    def test_third_item_detail_only_no_docs(self):
        """Digital Signature Act has detail link but no direct PDF on hub row."""
        items = extract_acts_hub_items(self.html, self.source)
        assert "Digital Signature Act" in items[2]["title"]
        assert items[2]["detail_href"] != ""
        assert items[2]["doc_hrefs"] == []

    def test_fourth_item_two_pdfs_no_detail(self):
        """Spectrum Regulations has two PDFs but no More Details link."""
        items = extract_acts_hub_items(self.html, self.source)
        assert "Spectrum" in items[3]["title"]
        assert items[3]["detail_href"] == ""
        assert len(items[3]["doc_hrefs"]) == 2

    def test_no_duplicate_titles(self):
        items = extract_acts_hub_items(self.html, self.source)
        titles = [i["title"] for i in items]
        assert len(titles) == len(set(titles))

    def test_all_doc_hrefs_are_doc_files(self):
        items = extract_acts_hub_items(self.html, self.source)
        doc_exts = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")
        for item in items:
            for href in item["doc_hrefs"]:
                assert any(href.lower().endswith(e) for e in doc_exts), \
                    f"Non-doc in doc_hrefs: {href}"

    def test_source_url_propagated(self):
        items = extract_acts_hub_items(self.html, self.source)
        for item in items:
            assert item["source_url"] == self.source


# ── dispute_resolution static page ───────────────────────────────────────────


class TestDisputeResolutionEmbeddedDocs:
    """
    The dispute-resolution page has no listing structure – it's a single static
    page.  The pipeline archives the HTML then calls extract_embedded_doc_links()
    to find all PDFs and DOCx files.  These tests verify that function works
    correctly against the dispute_resolution fixture.
    """

    def setup_method(self):
        self.html = _read("dispute_resolution.html")
        self.base = "https://mcmc.gov.my"

    def test_finds_guidelines_pdf(self):
        links = extract_embedded_doc_links(self.html, self.base)
        assert any("Guidelines-for-Dispute-Resolution" in l for l in links)

    def test_finds_all_three_form_pdfs(self):
        links = extract_embedded_doc_links(self.html, self.base)
        pdf_links = [l for l in links if l.endswith(".pdf")]
        # Guidelines PDF + Form1 + Form2 + Form3 PDFs = 4 PDFs
        assert len(pdf_links) >= 4

    def test_finds_docx_forms(self):
        links = extract_embedded_doc_links(self.html, self.base)
        docx_links = [l for l in links if l.endswith(".docx")]
        # Form1, Form2, Form3 Word files = 3 DOCX
        assert len(docx_links) == 3

    def test_total_document_count(self):
        """7 documents total: 1 guidelines PDF + 3 form PDFs + 3 form DOCXs."""
        links = extract_embedded_doc_links(self.html, self.base)
        assert len(links) == 7

    def test_no_html_links_included(self):
        """The /en/legal/dispute-resolution/cases HTML link must NOT appear."""
        links = extract_embedded_doc_links(self.html, self.base)
        assert not any("cases" in l for l in links)

    def test_no_duplicates(self):
        links = extract_embedded_doc_links(self.html, self.base)
        assert len(links) == len(set(links))

    def test_all_links_absolute(self):
        links = extract_embedded_doc_links(self.html, self.base)
        for link in links:
            assert link.startswith("http"), f"Relative link leaked: {link}"

    def test_article_meta_title(self):
        """extract_article_meta should pick up the h1 title."""
        meta = extract_article_meta(self.html, self.base)
        assert meta["title"] == "Dispute Resolution"

    def test_article_meta_no_date(self):
        """Static legal pages have no date element."""
        meta = extract_article_meta(self.html, self.base)
        assert meta["published_at"] == ""
