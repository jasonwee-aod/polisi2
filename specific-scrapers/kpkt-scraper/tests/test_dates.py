"""Tests for Malay date translation and parsing."""
import pytest

from kpkt_scraper.extractor import parse_malay_date, translate_malay_date


# ── translate_malay_date ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected_fragment",
    [
        ("4 Disember 2025", "December"),
        ("1 Januari 2026", "January"),
        ("28 Februari 2024", "February"),
        ("1 Mac 2023", "March"),
        ("15 Mei 2022", "May"),
        ("30 Juni 2024", "Juni"),        # 'Juni' is not in our map; should remain unchanged
        ("1 Ogos 2023", "August"),
        ("1 Julai 2024", "July"),
        ("31 Oktober 2024", "October"),
    ],
)
def test_translate_known_months(raw, expected_fragment):
    assert expected_fragment in translate_malay_date(raw)


def test_translate_case_insensitive():
    assert "December" in translate_malay_date("4 DISEMBER 2025")
    assert "March" in translate_malay_date("1 mac 2023")


# ── parse_malay_date ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("4 Disember 2025", "2025-12-04"),
        ("1 Januari 2026", "2026-01-01"),
        ("28 Februari 2024", "2024-02-28"),
        ("1 Mac 2023", "2023-03-01"),
        ("15 April 2022", "2022-04-15"),
        ("31 Mei 2021", "2021-05-31"),
        ("30 Jun 2020", "2020-06-30"),
        ("1 Julai 2024", "2024-07-01"),
        ("1 Ogos 2023", "2023-08-01"),
        ("15 September 2022", "2022-09-15"),
        ("31 Oktober 2024", "2024-10-31"),
        ("30 November 2025", "2025-11-30"),
        ("25 Disember 2024", "2024-12-25"),
    ],
)
def test_parse_known_dates(raw, expected):
    assert parse_malay_date(raw) == expected


def test_parse_empty_string():
    assert parse_malay_date("") == ""


def test_parse_whitespace_only():
    assert parse_malay_date("   ") == ""


def test_parse_invalid_date():
    assert parse_malay_date("not a date at all") == ""


def test_parse_partial_date_no_year():
    # Dates without a year may still parse via dateutil; just check no crash.
    result = parse_malay_date("4 Disember")
    assert isinstance(result, str)
