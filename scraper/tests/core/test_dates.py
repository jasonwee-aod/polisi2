"""Tests for polisi_scraper.core.dates — Malay date translation and parsing."""

from __future__ import annotations

import pytest

from polisi_scraper.core.dates import parse_iso_date, parse_malay_date, translate_malay_date


# ---------------------------------------------------------------------------
# translate_malay_date
# ---------------------------------------------------------------------------


class TestTranslateMalayDate:
    """translate_malay_date should replace Malay month/day names with English."""

    @pytest.mark.parametrize(
        "malay, expected_english",
        [
            ("Januari", "January"),
            ("Februari", "February"),
            ("Mac", "March"),
            ("April", "April"),
            ("Mei", "May"),
            ("Jun", "June"),
            ("Julai", "July"),
            ("Ogos", "August"),
            ("September", "September"),
            ("Oktober", "October"),
            ("November", "November"),
            ("Disember", "December"),
        ],
    )
    def test_full_months(self, malay: str, expected_english: str) -> None:
        result = translate_malay_date(f"15 {malay} 2024")
        assert expected_english in result

    @pytest.mark.parametrize(
        "abbr, expected_english",
        [
            ("Jan", "Jan"),
            ("Feb", "Feb"),
            ("Mac", "Mar"),
            ("Apr", "Apr"),
            ("Mei", "May"),
            ("Jun", "Jun"),
            ("Jul", "Jul"),
            ("Ogo", "Aug"),
            ("Sep", "Sep"),
            ("Okt", "Oct"),
            ("Nov", "Nov"),
            ("Dis", "Dec"),
        ],
    )
    def test_abbreviated_months(self, abbr: str, expected_english: str) -> None:
        result = translate_malay_date(f"15 {abbr} 2024")
        assert expected_english in result

    @pytest.mark.parametrize(
        "day_name",
        ["Isnin", "Selasa", "Rabu", "Khamis", "Jumaat", "Sabtu", "Ahad"],
    )
    def test_day_name_stripping(self, day_name: str) -> None:
        result = translate_malay_date(f"18 Feb 2025 {day_name}")
        assert day_name.lower() not in result.lower()

    def test_combined_day_and_month(self) -> None:
        result = translate_malay_date("18 Februari 2025 Selasa")
        assert "February" in result
        assert "selasa" not in result.lower()

    def test_case_insensitive(self) -> None:
        result = translate_malay_date("15 OGOS 2024")
        assert "August" in result

    def test_empty_string(self) -> None:
        assert translate_malay_date("") == ""

    def test_no_malay_words(self) -> None:
        result = translate_malay_date("15 January 2024")
        assert result == "15 January 2024"


# ---------------------------------------------------------------------------
# parse_malay_date
# ---------------------------------------------------------------------------


class TestParseMalayDate:
    """parse_malay_date should return ISO 8601 YYYY-MM-DD strings."""

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("15 Januari 2024", "2024-01-15"),
            ("1 Mac 2023", "2023-03-01"),
            ("28 Februari 2020", "2020-02-28"),
            ("31 Ogos 2019", "2019-08-31"),
            ("25 Disember 2023", "2023-12-25"),
        ],
    )
    def test_full_malay_dates(self, text: str, expected: str) -> None:
        assert parse_malay_date(text) == expected

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("2024-03-15", "2024-03-15"),
            ("2023-01-01", "2023-01-01"),
            ("2020-12-31", "2020-12-31"),
        ],
    )
    def test_iso_dates(self, text: str, expected: str) -> None:
        assert parse_malay_date(text) == expected

    def test_year_only_fallback(self) -> None:
        # dateutil fuzzy parser handles bare years and most year-containing
        # strings by filling in today's month/day.  So bare "2024" returns a
        # valid date with the right year (not necessarily Jan 1).
        result_bare = parse_malay_date("2024")
        assert result_bare.startswith("2024-")

        result_tahun = parse_malay_date("Tahun 2023")
        assert result_tahun.startswith("2023-")

        # The year-only regex fallback (YYYY-01-01) triggers only when dateutil
        # raises.  Conflicting large numbers cause dateutil to fail, leaving
        # the regex to extract the 4-digit year.
        result_fallback = parse_malay_date("99999 2019 99999")
        assert result_fallback == "2019-01-01"

    @pytest.mark.parametrize("text", ["", "   ", None])
    def test_empty_whitespace_none(self, text) -> None:
        assert parse_malay_date(text) == ""

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("1st Januari 2024", "2024-01-01"),
            ("2nd Mac 2023", "2023-03-02"),
            ("3rd Mei 2022", "2022-05-03"),
            ("4th Julai 2021", "2021-07-04"),
        ],
    )
    def test_ordinal_suffixes_stripped(self, text: str, expected: str) -> None:
        assert parse_malay_date(text) == expected

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("15 | Januari | 2024", "2024-01-15"),
            ("15 \u2022 Mac \u2022 2023", "2023-03-15"),
        ],
    )
    def test_separator_cleaning(self, text: str, expected: str) -> None:
        assert parse_malay_date(text) == expected

    def test_fuzzy_parsing_extra_text(self) -> None:
        result = parse_malay_date("Tarikh: 15 Jun 2024, Kuala Lumpur")
        assert result == "2024-06-15"

    def test_18_feb_2025_selasa(self) -> None:
        """Real-world pattern from KPKT: '18 FEB 2025 SELASA'."""
        assert parse_malay_date("18 FEB 2025 SELASA") == "2025-02-18"

    def test_nonsense_returns_empty(self) -> None:
        assert parse_malay_date("abcxyz") == ""


# ---------------------------------------------------------------------------
# parse_iso_date
# ---------------------------------------------------------------------------


class TestParseIsoDate:
    """parse_iso_date should normalize ISO 8601 strings to YYYY-MM-DD."""

    def test_standard_iso(self) -> None:
        assert parse_iso_date("2024-03-15") == "2024-03-15"

    def test_datetime_iso(self) -> None:
        assert parse_iso_date("2024-03-15T14:30:00Z") == "2024-03-15"
        assert parse_iso_date("2024-03-15T14:30:00+08:00") == "2024-03-15"

    @pytest.mark.parametrize("text", ["", "   ", None])
    def test_empty_or_none(self, text) -> None:
        assert parse_iso_date(text) == ""

    def test_invalid_returns_empty(self) -> None:
        assert parse_iso_date("not-a-date") == ""
