"""
Tests for MCMC date string parsing.
"""
import pytest

from mcmc_scraper.extractor import parse_mcmc_date


class TestParseMcmcDate:
    def test_listing_format_short_month_caps(self):
        """MAR 03, 2026 → 2026-03-03 (listing page format)"""
        assert parse_mcmc_date("MAR 03, 2026") == "2026-03-03"

    def test_listing_format_feb(self):
        assert parse_mcmc_date("FEB 15, 2026") == "2026-02-15"

    def test_listing_format_jan(self):
        assert parse_mcmc_date("JAN 01, 2025") == "2025-01-01"

    def test_listing_format_dec(self):
        assert parse_mcmc_date("DEC 31, 2024") == "2024-12-31"

    def test_detail_format_dd_mon_yyyy(self):
        """03 Mar 2026 → 2026-03-03 (detail page format)"""
        assert parse_mcmc_date("03 Mar 2026") == "2026-03-03"

    def test_detail_format_full_month(self):
        """3 March 2026 → 2026-03-03"""
        assert parse_mcmc_date("3 March 2026") == "2026-03-03"

    def test_iso_date_passthrough(self):
        """ISO format should still parse correctly"""
        assert parse_mcmc_date("2026-03-03") == "2026-03-03"

    def test_iso_datetime(self):
        """ISO datetime with timezone"""
        assert parse_mcmc_date("2026-03-03T09:00:00+08:00") == "2026-03-03"

    def test_empty_string_returns_empty(self):
        assert parse_mcmc_date("") == ""

    def test_none_like_whitespace_returns_empty(self):
        assert parse_mcmc_date("   ") == ""

    def test_invalid_date_returns_empty(self):
        assert parse_mcmc_date("not-a-date") == ""

    def test_january_long_format(self):
        assert parse_mcmc_date("January 15, 2025") == "2025-01-15"
