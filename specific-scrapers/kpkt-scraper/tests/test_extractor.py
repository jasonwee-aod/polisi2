"""Integration tests for the KPKT HTML extractor using saved fixtures."""
from pathlib import Path

import pytest

from kpkt_scraper.extractor import extract_siaran_media

FIXTURES = Path(__file__).parent / "fixtures"
LISTING_URL = "https://www.kpkt.gov.my/index.php/pages/view/3470?mid=764"


# ── Pattern A (2025 HTML) ─────────────────────────────────────────────────────


def test_pattern_a_item_count():
    html = (FIXTURES / "siaran_media_pattern_a.html").read_text(encoding="utf-8")
    items = extract_siaran_media(html, LISTING_URL)
    assert len(items) == 3


def test_pattern_a_first_item_title():
    html = (FIXTURES / "siaran_media_pattern_a.html").read_text(encoding="utf-8")
    items = extract_siaran_media(html, LISTING_URL)
    assert "KPKT Serah Kunci Rumah" in items[0]["title"]


def test_pattern_a_first_item_date():
    html = (FIXTURES / "siaran_media_pattern_a.html").read_text(encoding="utf-8")
    items = extract_siaran_media(html, LISTING_URL)
    assert items[0]["date_text"] == "4 Disember 2025"


def test_pattern_a_href_points_to_pdf():
    html = (FIXTURES / "siaran_media_pattern_a.html").read_text(encoding="utf-8")
    items = extract_siaran_media(html, LISTING_URL)
    for item in items:
        assert item["href"].endswith(".pdf"), f"Expected .pdf href, got: {item['href']}"


def test_pattern_a_source_url_preserved():
    html = (FIXTURES / "siaran_media_pattern_a.html").read_text(encoding="utf-8")
    items = extract_siaran_media(html, LISTING_URL)
    for item in items:
        assert item["source_url"] == LISTING_URL


# ── Pattern B (2024 HTML) ─────────────────────────────────────────────────────


def test_pattern_b_item_count():
    html = (FIXTURES / "siaran_media_pattern_b.html").read_text(encoding="utf-8")
    items = extract_siaran_media(html, LISTING_URL)
    assert len(items) == 3


def test_pattern_b_first_item_title():
    html = (FIXTURES / "siaran_media_pattern_b.html").read_text(encoding="utf-8")
    items = extract_siaran_media(html, LISTING_URL)
    assert "Pencapaian SPNB" in items[0]["title"]


def test_pattern_b_first_item_date():
    html = (FIXTURES / "siaran_media_pattern_b.html").read_text(encoding="utf-8")
    items = extract_siaran_media(html, LISTING_URL)
    assert items[0]["date_text"] == "1 Disember 2024"


def test_pattern_b_no_duplicate_hrefs():
    html = (FIXTURES / "siaran_media_pattern_b.html").read_text(encoding="utf-8")
    items = extract_siaran_media(html, LISTING_URL)
    hrefs = [item["href"] for item in items]
    assert len(hrefs) == len(set(hrefs)), "Duplicate hrefs found"


# ── Edge cases ────────────────────────────────────────────────────────────────


def test_no_accordion_returns_empty():
    html = "<html><body><p>No accordion content here</p></body></html>"
    items = extract_siaran_media(html, LISTING_URL)
    assert items == []


def test_empty_html_returns_empty():
    items = extract_siaran_media("", LISTING_URL)
    assert items == []


def test_no_duplicate_hrefs_across_patterns():
    """Even if an href somehow appears in both Pattern A and B, dedup prevents double entries."""
    html = """
    <div id="accordion_999">
      <h3>Disember</h3>
      <div>
        <p><strong>1 Disember 2025</strong><br/>
          <a href="/doc.pdf">Title A</a>
        </p>
        <!-- same href again as Pattern B (edge case) -->
        <a href="/doc.pdf">1 Disember 2025\nTitle B</a>
      </div>
    </div>
    """
    items = extract_siaran_media(html, LISTING_URL)
    hrefs = [item["href"] for item in items]
    assert hrefs.count("/doc.pdf") == 1
