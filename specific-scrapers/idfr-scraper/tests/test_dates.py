"""Tests for IDFR date parsing."""
import pytest

from idfr_scraper.extractor import parse_idfr_date


class TestParseIdfrDate:
    # Full "DD Month YYYY" – English
    def test_day_month_year_english(self):
        assert parse_idfr_date("25 February 2026") == "2026-02-25"

    def test_day_abbreviated_month_year(self):
        assert parse_idfr_date("25 Feb 2026") == "2026-02-25"

    def test_day_month_year_october(self):
        assert parse_idfr_date("2 October 2025") == "2025-10-02"

    def test_day_month_year_january(self):
        assert parse_idfr_date("15 January 2025") == "2025-01-15"

    def test_day_month_year_december(self):
        assert parse_idfr_date("31 December 2023") == "2023-12-31"

    # "Month DD, YYYY" – alternate format
    def test_month_day_comma_year(self):
        assert parse_idfr_date("October 2, 2025") == "2025-10-02"

    def test_abbreviated_month_day_comma_year(self):
        assert parse_idfr_date("Oct 2, 2025") == "2025-10-02"

    # Malay month names
    def test_malay_februari(self):
        assert parse_idfr_date("25 Februari 2026") == "2026-02-25"

    def test_malay_januari(self):
        assert parse_idfr_date("1 Januari 2024") == "2024-01-01"

    def test_malay_mei(self):
        assert parse_idfr_date("16 Mei 2025") == "2025-05-16"

    def test_malay_ogos(self):
        assert parse_idfr_date("15 Ogos 2023") == "2023-08-15"

    def test_malay_disember(self):
        assert parse_idfr_date("31 Disember 2022") == "2022-12-31"

    # Parenthetical dates
    def test_parenthetical_english(self):
        assert parse_idfr_date("(Oct 2, 2025)") == "2025-10-02"

    def test_parenthetical_full_date(self):
        assert parse_idfr_date("(15 January 2025)") == "2025-01-15"

    # Year-only fallback
    def test_year_only(self):
        assert parse_idfr_date("2025") == "2025-01-01"

    def test_year_only_2023(self):
        assert parse_idfr_date("2023") == "2023-01-01"

    def test_year_with_dash_suffix(self):
        assert parse_idfr_date("2025-01-01") == "2025-01-01"

    # Edge cases
    def test_empty_string_returns_empty(self):
        assert parse_idfr_date("") == ""

    def test_none_handled_as_empty(self):
        # Passing None directly would fail type check, but empty string works
        assert parse_idfr_date("   ") == ""

    def test_garbage_string_returns_empty(self):
        assert parse_idfr_date("not a date at all!!!") == ""

    def test_event_name_with_no_date(self):
        # Event name without date should return ""
        result = parse_idfr_date("IDFR FORUM ON ASEAN")
        assert result == ""

    def test_whitespace_trimmed(self):
        assert parse_idfr_date("  2 October 2025  ") == "2025-10-02"
