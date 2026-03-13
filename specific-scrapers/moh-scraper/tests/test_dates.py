"""
Tests for MOH date string parsing.
"""
import pytest

from moh_scraper.extractor import parse_moh_date


class TestParseMohDate:
    # ── Valid formats ─────────────────────────────────────────────────────────

    def test_dd_mm_yyyy_hyphen(self):
        assert parse_moh_date("23-02-2026") == "2026-02-23"

    def test_iso_datetime_with_timezone(self):
        assert parse_moh_date("2026-02-23T00:00:00+08:00") == "2026-02-23"

    def test_iso_datetime_utc(self):
        assert parse_moh_date("2026-02-23T12:34:56Z") == "2026-02-23"

    def test_full_month_name_english(self):
        assert parse_moh_date("23 February 2026") == "2026-02-23"

    def test_abbreviated_month_english(self):
        assert parse_moh_date("23 Feb 2026") == "2026-02-23"

    def test_iso_date_only(self):
        assert parse_moh_date("2026-02-23") == "2026-02-23"

    def test_strips_label_prefix(self):
        # Joomla sometimes renders "Published: 23 February 2026"
        assert parse_moh_date("Published: 23 February 2026") == "2026-02-23"

    def test_strips_label_prefix_malay(self):
        assert parse_moh_date("Diterbitkan: 23 Februari 2026") == "2026-02-23"

    def test_first_of_month(self):
        assert parse_moh_date("01-01-2026") == "2026-01-01"

    def test_end_of_year(self):
        assert parse_moh_date("31-12-2025") == "2025-12-31"

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_empty_string_returns_empty(self):
        assert parse_moh_date("") == ""

    def test_whitespace_only_returns_empty(self):
        assert parse_moh_date("   ") == ""

    def test_garbage_returns_empty(self):
        assert parse_moh_date("not-a-date-xyz") == ""

    def test_none_like_empty(self):
        assert parse_moh_date("") == ""
