"""
Tests for the Statistics page extractors and date-from-title parsing.

Covers three new findings from /index.php/pages/view/490?mid=661:
  1. extract_date_from_title  – date recovery from Malay title strings
  2. Statistik KPKT fixture   – <h3>YEAR</h3> + <a> in <td> thumbnail grid
  3. Piagam Pelanggan fixture – <a> in <li> list with month dates in title
"""
from pathlib import Path

import pytest

from kpkt_scraper.extractor import (
    extract_container_attachments,
    extract_date_from_title,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "https://www.kpkt.gov.my"
SOURCE_700 = "https://www.kpkt.gov.my/index.php/pages/view/700?mid=586"
SOURCE_131 = "https://www.kpkt.gov.my/index.php/pages/view/131"


# ── extract_date_from_title ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "title, expected",
    [
        # "Sehingga DD Month YYYY" → exact date
        ("Statistik Terpilih KPKT Sehingga 31 Mac 2022", "2022-03-31"),
        ("Statistik Terpilih KPKT Sehingga 30 Jun 2022", "2022-06-30"),
        ("Perangkaan Sehingga 30 September 2021",        "2021-09-30"),
        # "Bulan Month YYYY" → first day of month
        ("Pencapaian Piagam Pelanggan bagi Bulan Januari 2026", "2026-01-01"),
        ("Pencapaian Piagam Pelanggan bagi Bulan Disember 2025", "2025-12-01"),
        ("Bilangan transaksi online bagi Oktober 2021",          "2021-10-01"),
        # Bare "Month YYYY" in title
        ("Statistik Terpilih KPKT Sehingga September 2019", "2019-09-01"),
        # Year only → January 1
        ("Statistik KPKT 2024 (Tahunan)",          "2024-01-01"),
        ("Statistik Siri Masa MyKPKT 2023",         "2023-01-01"),
        ("Perangkaan 2016 (Tahunan)",               "2016-01-01"),
        # No date in string
        ("Senarai Borang Tribunal",                 ""),
        ("",                                        ""),
    ],
)
def test_extract_date_from_title(title, expected):
    assert extract_date_from_title(title) == expected


def test_extract_date_case_insensitive():
    assert extract_date_from_title("sehingga 31 MAC 2022") == "2022-03-31"


# ── Statistik KPKT fixture (<h3> + <td> grid, no .container_attachments) ─────


def test_statistik_kpkt_item_count():
    html = (FIXTURES / "statistik_kpkt.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_700, BASE_URL, "report")
    # 2 from 2024 section + 3 from 2022 section = 5 PDFs
    # Archive page links (/index.php/pages/view/...) must NOT be included
    assert len(items) == 5


def test_statistik_kpkt_no_archive_page_links():
    """Navigation links to archive sub-pages must not be captured."""
    html = (FIXTURES / "statistik_kpkt.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_700, BASE_URL, "report")
    for item in items:
        assert "/index.php/pages/view/" not in item["href"]


def test_statistik_kpkt_all_hrefs_absolute():
    html = (FIXTURES / "statistik_kpkt.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_700, BASE_URL, "report")
    for item in items:
        assert item["href"].startswith("https://"), f"Relative href: {item['href']}"


def test_statistik_kpkt_date_from_sehingga_title():
    html = (FIXTURES / "statistik_kpkt.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_700, BASE_URL, "report")
    mac_items = [i for i in items if "Mac 2022" in i["title"]]
    assert len(mac_items) == 1
    assert mac_items[0]["date_text"] == "2022-03-31"


def test_statistik_kpkt_date_year_only():
    html = (FIXTURES / "statistik_kpkt.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_700, BASE_URL, "report")
    annual_2024 = [i for i in items if "Tahunan" in i["title"] and "2024" in i["title"]]
    assert len(annual_2024) == 1
    assert annual_2024[0]["date_text"] == "2024-01-01"


# ── Piagam Pelanggan fixture (<li> list) ──────────────────────────────────────


def test_piagam_item_count():
    html = (FIXTURES / "piagam_pelanggan.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_131, BASE_URL, "report")
    # 3 monthly PDFs; ARKIB link is /pages/view/137 → filtered out
    assert len(items) == 3


def test_piagam_no_arkib_link():
    html = (FIXTURES / "piagam_pelanggan.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_131, BASE_URL, "report")
    for item in items:
        assert "/pages/view/" not in item["href"]


def test_piagam_date_from_bulan_title():
    html = (FIXTURES / "piagam_pelanggan.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_131, BASE_URL, "report")
    jan_items = [i for i in items if "Januari 2026" in i["title"]]
    assert len(jan_items) == 1
    assert jan_items[0]["date_text"] == "2026-01-01"


def test_piagam_date_disember():
    html = (FIXTURES / "piagam_pelanggan.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_131, BASE_URL, "report")
    dec_items = [i for i in items if "Disember 2025" in i["title"]]
    assert len(dec_items) == 1
    assert dec_items[0]["date_text"] == "2025-12-01"


def test_piagam_title_from_li_text():
    """Title should come from the <li> text, not just the bare link text."""
    html = (FIXTURES / "piagam_pelanggan.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_131, BASE_URL, "report")
    for item in items:
        assert "Piagam Pelanggan" in item["title"], (
            f"Expected 'Piagam Pelanggan' in title, got: {item['title']!r}"
        )


def test_piagam_all_hrefs_are_pdf():
    html = (FIXTURES / "piagam_pelanggan.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_131, BASE_URL, "report")
    for item in items:
        assert item["href"].endswith(".pdf"), f"Non-PDF href: {item['href']}"
