"""Tests for Divi theme date parsing and ISO datetime parsing."""
import pytest

from dewan_johor_scraper.extractor import parse_divi_date, parse_pr_title_date, parse_wp_datetime


class TestParseDiviDate:
    """parse_divi_date handles the English month formats used by the Divi theme
    and the WP Download Manager plugin."""

    def test_abbreviated_month(self):
        assert parse_divi_date("Jul 27, 2019") == "2019-07-27"

    def test_full_month_name(self):
        assert parse_divi_date("November 11, 2019") == "2019-11-11"

    def test_may_abbreviated(self):
        assert parse_divi_date("May 14, 2020") == "2020-05-14"

    def test_jan_abbreviated(self):
        assert parse_divi_date("Jan 15, 2019") == "2019-01-15"

    def test_apr_abbreviated(self):
        assert parse_divi_date("Apr 4, 2019") == "2019-04-04"

    def test_single_digit_day(self):
        assert parse_divi_date("Apr 4, 2019") == "2019-04-04"

    def test_empty_string_returns_empty(self):
        assert parse_divi_date("") == ""

    def test_whitespace_only_returns_empty(self):
        assert parse_divi_date("   ") == ""

    def test_garbage_returns_empty(self):
        assert parse_divi_date("not a date at all!!!") == ""


class TestParseWpDatetime:
    """parse_wp_datetime handles ISO 8601 datetimes from WP meta tags."""

    def test_iso_with_timezone_offset(self):
        assert parse_wp_datetime("2019-07-27T08:30:00+08:00") == "2019-07-27"

    def test_iso_utc(self):
        assert parse_wp_datetime("2019-07-27T00:30:00+00:00") == "2019-07-27"

    def test_date_only(self):
        assert parse_wp_datetime("2019-07-27") == "2019-07-27"

    def test_sitemap_lastmod_format(self):
        # WP native sitemap lastmod: "2020-05-14T13:48:42+08:00"
        assert parse_wp_datetime("2020-05-14T13:48:42+08:00") == "2020-05-14"

    def test_empty_returns_empty(self):
        assert parse_wp_datetime("") == ""

    def test_garbage_returns_empty(self):
        assert parse_wp_datetime("not-a-date") == ""


class TestParsePrTitleDate:
    """parse_pr_title_date extracts dates from Malay-language PR document titles."""

    def test_hingga_range_returns_start_day(self):
        title = "Deraf Verbatim Mesyuarat Pertama bertarikh 16 hingga 26 Mei 2025"
        assert parse_pr_title_date(title) == "2025-05-16"

    def test_simple_date_english_month(self):
        title = "Deraf Verbatim Mesyuarat Pertama bertarikh 11 September 2024"
        assert parse_pr_title_date(title) == "2024-09-11"

    def test_malay_month_april(self):
        title = "Deraf Verbatim bertarikh 21 April 2022"
        assert parse_pr_title_date(title) == "2022-04-21"

    def test_malay_month_mac(self):
        title = "Deraf Verbatim bertarikh 5 Mac 2023"
        assert parse_pr_title_date(title) == "2023-03-05"

    def test_malay_month_ogos(self):
        title = "Penyata Rasmi 3 Ogos 2021"
        assert parse_pr_title_date(title) == "2021-08-03"

    def test_malay_month_julai(self):
        title = "Penyata Rasmi 10 Julai 2019"
        assert parse_pr_title_date(title) == "2019-07-10"

    def test_malay_month_disember(self):
        title = "Penyata Rasmi 1 Disember 2020"
        assert parse_pr_title_date(title) == "2020-12-01"

    def test_hingga_range_with_malay_month(self):
        title = "Deraf Verbatim 3 hingga 7 Februari 2023"
        assert parse_pr_title_date(title) == "2023-02-03"

    def test_empty_returns_empty(self):
        assert parse_pr_title_date("") == ""

    def test_whitespace_only_returns_empty(self):
        assert parse_pr_title_date("   ") == ""

    def test_no_date_in_title_returns_empty(self):
        assert parse_pr_title_date("Deraf Verbatim Mesyuarat Pertama") == ""
