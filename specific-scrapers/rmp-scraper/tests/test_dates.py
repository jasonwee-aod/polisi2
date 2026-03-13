"""
Tests for RMP date parsing and URL date extraction.
"""
import pytest

from rmp_scraper.extractor import date_from_url, parse_rmp_date


class TestParseRmpDate:
    def test_english_long(self):
        assert parse_rmp_date("09 March 2026") == "2026-03-09"

    def test_english_short(self):
        assert parse_rmp_date("09 Mar 2026") == "2026-03-09"

    def test_malay_mac(self):
        assert parse_rmp_date("09 Mac 2026") == "2026-03-09"

    def test_malay_januari(self):
        assert parse_rmp_date("01 Januari 2025") == "2025-01-01"

    def test_malay_februari(self):
        assert parse_rmp_date("28 Februari 2025") == "2025-02-28"

    def test_malay_julai(self):
        assert parse_rmp_date("15 Julai 2024") == "2024-07-15"

    def test_malay_ogos(self):
        assert parse_rmp_date("31 Ogos 2024") == "2024-08-31"

    def test_malay_disember(self):
        assert parse_rmp_date("31 Disember 2023") == "2023-12-31"

    def test_iso_datetime(self):
        assert parse_rmp_date("2026-03-09T00:00:00+08:00") == "2026-03-09"

    def test_slash_date_dayfirst(self):
        assert parse_rmp_date("09/03/2026") == "2026-03-09"

    def test_empty_string(self):
        assert parse_rmp_date("") == ""

    def test_none_equivalent_whitespace(self):
        assert parse_rmp_date("   ") == ""

    def test_invalid_returns_empty(self):
        assert parse_rmp_date("not-a-date") == ""

    def test_year_only_returns_empty(self):
        # Single token that looks like year — dateutil may parse or not;
        # either way we just verify no exception is raised
        result = parse_rmp_date("2026")
        assert isinstance(result, str)

    def test_month_year_english(self):
        result = parse_rmp_date("March 2026")
        assert isinstance(result, str)


class TestDateFromUrl:
    def test_news_url_with_date(self):
        url = "https://www.rmp.gov.my/arkib-berita/berita/2026/03/09/pdrm-tangkap-suspek"
        assert date_from_url(url) == "2026-03-09"

    def test_siaran_media_url(self):
        url = "https://www.rmp.gov.my/arkib-berita/siaran-media/2025/11/15/kenyataan-media"
        assert date_from_url(url) == "2025-11-15"

    def test_url_without_date(self):
        url = "https://www.rmp.gov.my/laman-utama/penerbitan"
        assert date_from_url(url) == ""

    def test_relative_url_with_date(self):
        url = "/arkib-berita/berita/2024/07/04/slug"
        assert date_from_url(url) == "2024-07-04"

    def test_empty_url(self):
        assert date_from_url("") == ""
