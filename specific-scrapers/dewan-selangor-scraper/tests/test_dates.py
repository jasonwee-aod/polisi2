"""Tests for date parsing utilities."""
import pytest

from dewan_selangor_scraper.extractor import parse_malay_date, parse_wp_datetime, translate_malay_date


class TestTranslateMalayDate:
    def test_disember(self):
        assert translate_malay_date("4 Disember 2025") == "4 December 2025"

    def test_januari(self):
        assert translate_malay_date("1 Januari 2024") == "1 January 2024"

    def test_mac(self):
        assert translate_malay_date("31 Mac 2023") == "31 March 2023"

    def test_case_insensitive(self):
        assert translate_malay_date("1 JANUARI 2024") == "1 January 2024"

    def test_no_malay_month_unchanged(self):
        assert translate_malay_date("15 September 2025") == "15 September 2025"


class TestParseMalayDate:
    def test_full_malay_date(self):
        assert parse_malay_date("4 Disember 2025") == "2025-12-04"

    def test_mac(self):
        assert parse_malay_date("1 Mac 2023") == "2023-03-01"

    def test_mei(self):
        assert parse_malay_date("15 Mei 2024") == "2024-05-15"

    def test_ogos(self):
        assert parse_malay_date("23 Ogos 2021") == "2021-08-23"

    def test_empty_string_returns_empty(self):
        assert parse_malay_date("") == ""

    def test_none_like_whitespace_returns_empty(self):
        assert parse_malay_date("   ") == ""

    def test_invalid_returns_empty(self):
        assert parse_malay_date("not a date") == ""


class TestParseWpDatetime:
    def test_iso_datetime_with_offset(self):
        assert parse_wp_datetime("2025-11-13T09:30:00+08:00") == "2025-11-13"

    def test_iso_datetime_utc(self):
        assert parse_wp_datetime("2025-01-15T02:30:00+00:00") == "2025-01-15"

    def test_date_only(self):
        assert parse_wp_datetime("2025-09-05") == "2025-09-05"

    def test_empty_string_returns_empty(self):
        assert parse_wp_datetime("") == ""

    def test_whitespace_returns_empty(self):
        assert parse_wp_datetime("   ") == ""

    def test_invalid_returns_empty(self):
        assert parse_wp_datetime("not-a-date") == ""
