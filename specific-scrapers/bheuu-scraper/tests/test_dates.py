"""
Tests for Strapi date string parsing.
"""
import pytest

from bheuu_scraper.extractor import parse_strapi_date


class TestParseStrapiDate:
    def test_iso_date_passthrough(self):
        """YYYY-MM-DD from publishDate field."""
        assert parse_strapi_date("2024-01-08") == "2024-01-08"

    def test_iso_datetime_utc(self):
        """createdAt / updatedAt format."""
        assert parse_strapi_date("2024-08-14T02:22:22.887Z") == "2024-08-14"

    def test_iso_datetime_with_offset(self):
        assert parse_strapi_date("2025-03-01T09:00:00+08:00") == "2025-03-01"

    def test_published_at_format(self):
        """published_at field from Strapi v3."""
        assert parse_strapi_date("2024-10-08T07:52:58.284Z") == "2024-10-08"

    def test_year_only_string(self):
        """year field on act-protection-archives records."""
        assert parse_strapi_date("2010") == "2010-01-01"

    def test_year_2024(self):
        assert parse_strapi_date("2024") == "2024-01-01"

    def test_empty_string_returns_empty(self):
        assert parse_strapi_date("") == ""

    def test_none_returns_empty(self):
        assert parse_strapi_date(None) == ""

    def test_whitespace_returns_empty(self):
        assert parse_strapi_date("   ") == ""

    def test_invalid_returns_empty(self):
        assert parse_strapi_date("not-a-date") == ""

    def test_start_date(self):
        """startDate field on tender-quotations."""
        assert parse_strapi_date("2024-10-24") == "2024-10-24"

    def test_result_date(self):
        """resultDate field on tender-holders."""
        assert parse_strapi_date("2025-01-06") == "2025-01-06"
