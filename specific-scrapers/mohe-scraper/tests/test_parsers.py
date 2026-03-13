"""Tests for RSS and HTML parsing."""

import pytest
from mohe_scraper.parsers import RSSParser, HTMLParser, DateParser
from tests.fixtures import (
    SAMPLE_DOCMAN_HTML,
    SAMPLE_DOCMAN_HTML_EMPTY_TABLE,
    SAMPLE_DOCMAN_HTML_NO_TABLE,
)


class TestRSSParser:
    """Test RSS feed parsing."""

    def test_parse_rss_basic(self):
        """Test basic RSS parsing."""
        rss_content = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Test Item</title>
      <link>https://mohe.gov.my/test</link>
      <description>Test Description</description>
      <pubDate>Thu, 27 Feb 2026 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""

        items = RSSParser.parse_feed(rss_content)
        assert len(items) == 1
        assert items[0]["title"] == "Test Item"
        assert items[0]["link"] == "https://mohe.gov.my/test"

    def test_parse_rss_multiple_items(self):
        """Test parsing multiple RSS items."""
        rss_content = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Item 1</title>
      <link>https://mohe.gov.my/test1</link>
    </item>
    <item>
      <title>Item 2</title>
      <link>https://mohe.gov.my/test2</link>
    </item>
  </channel>
</rss>"""

        items = RSSParser.parse_feed(rss_content)
        assert len(items) == 2

    def test_parse_rss_missing_link(self):
        """Test that items without links are skipped."""
        rss_content = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>No Link Item</title>
      <description>No link provided</description>
    </item>
    <item>
      <title>Valid Item</title>
      <link>https://mohe.gov.my/test</link>
    </item>
  </channel>
</rss>"""

        items = RSSParser.parse_feed(rss_content)
        assert len(items) == 1
        assert items[0]["title"] == "Valid Item"

    def test_parse_date_rfc2822(self):
        """Test parsing RFC 2822 date format (RSS standard)."""
        date_str = "Thu, 27 Feb 2026 10:00:00 GMT"
        result = RSSParser.parse_date(date_str)
        assert result == "2026-02-27"

    def test_parse_date_iso8601(self):
        """Test parsing ISO 8601 format."""
        date_str = "2026-02-27"
        result = RSSParser.parse_date(date_str)
        assert result == "2026-02-27"

    def test_parse_date_invalid(self):
        """Test handling of unparseable dates."""
        date_str = "invalid date string"
        result = RSSParser.parse_date(date_str)
        assert result is None

    def test_parse_date_none(self):
        """Test handling of None date."""
        result = RSSParser.parse_date(None)
        assert result is None


class TestDateParser:
    """Test flexible date parsing with Malay support."""

    def test_parse_english_format(self):
        """Test parsing English date format."""
        date_str = "27 February 2026"
        result = DateParser.parse(date_str, language="en")
        assert result == "2026-02-27"

    def test_parse_iso_format(self):
        """Test parsing ISO 8601 format."""
        date_str = "2026-02-27"
        result = DateParser.parse(date_str, language="en")
        assert result == "2026-02-27"

    def test_parse_malay_month(self):
        """Test parsing Malay month names."""
        date_str = "27 Februari 2026"
        result = DateParser.parse(date_str, language="ms")
        assert result == "2026-02-27"

    def test_parse_malay_months_all(self):
        """Test all Malay month names."""
        test_cases = [
            ("1 Januari 2026", "2026-01-01"),
            ("1 Februari 2026", "2026-02-01"),
            ("1 Mac 2026", "2026-03-01"),
            ("1 April 2026", "2026-04-01"),
            ("1 Mei 2026", "2026-05-01"),
            ("1 Jun 2026", "2026-06-01"),
            ("1 Julai 2026", "2026-07-01"),
            ("1 Ogos 2026", "2026-08-01"),
            ("1 September 2026", "2026-09-01"),
            ("1 Oktober 2026", "2026-10-01"),
            ("1 November 2026", "2026-11-01"),
            ("1 Disember 2026", "2026-12-01"),
        ]

        for date_str, expected in test_cases:
            result = DateParser.parse(date_str, language="ms")
            assert result == expected, f"Failed for {date_str}"

    def test_parse_invalid(self):
        """Test handling of unparseable dates."""
        result = DateParser.parse("invalid", language="en")
        assert result is None

    def test_parse_none(self):
        """Test handling of None."""
        result = DateParser.parse(None, language="en")
        assert result is None


class TestHTMLParserDOCman:
    """Test DOCman HTML listing page parsing (staff downloads section)."""

    DOCMAN_SELECTORS = {
        "item_rows": ".k-js-documents-table tr",
        "title": "a[href*='/file']",
        "published_date": "td:nth-child(2)",
        "next_page": None,
    }

    def test_parse_docman_returns_correct_count(self):
        """Parse a DOCman table and get the right number of items."""
        items = HTMLParser.parse_listing_page(SAMPLE_DOCMAN_HTML, self.DOCMAN_SELECTORS)
        assert len(items) == 3

    def test_parse_docman_title_extracted(self):
        """Titles come from the anchor link text."""
        items = HTMLParser.parse_listing_page(SAMPLE_DOCMAN_HTML, self.DOCMAN_SELECTORS)
        assert items[0]["title"] == "Arahan Pentadbiran Bil. 1 Tahun 2024"
        assert items[1]["title"] == "Arahan Pentadbiran Bil. 2 Tahun 2023"

    def test_parse_docman_link_ends_with_file(self):
        """Download links must end in /file (DOCman binary endpoint)."""
        items = HTMLParser.parse_listing_page(SAMPLE_DOCMAN_HTML, self.DOCMAN_SELECTORS)
        for item in items:
            assert item["link"].endswith("/file"), (
                f"Expected /file suffix, got: {item['link']}"
            )

    def test_parse_docman_is_file_download_flag(self):
        """is_file_download flag must be True for all DOCman items."""
        items = HTMLParser.parse_listing_page(SAMPLE_DOCMAN_HTML, self.DOCMAN_SELECTORS)
        for item in items:
            assert item["is_file_download"] is True

    def test_parse_docman_date_extracted(self):
        """Date string is extracted from the second table cell."""
        items = HTMLParser.parse_listing_page(SAMPLE_DOCMAN_HTML, self.DOCMAN_SELECTORS)
        assert items[0]["published_date"] == "15 Januari 2024"
        assert items[1]["published_date"] == "20 Mac 2023"

    def test_parse_docman_malay_date_parseable(self):
        """Dates extracted from DOCman are parseable by DateParser with ms language."""
        items = HTMLParser.parse_listing_page(SAMPLE_DOCMAN_HTML, self.DOCMAN_SELECTORS)
        for item in items:
            result = DateParser.parse(item["published_date"], language="ms")
            assert result is not None, (
                f"DateParser returned None for: {item['published_date']}"
            )
            assert len(result) == 10  # YYYY-MM-DD

    def test_parse_docman_specific_dates(self):
        """Spot-check exact date conversions for Malay months."""
        items = HTMLParser.parse_listing_page(SAMPLE_DOCMAN_HTML, self.DOCMAN_SELECTORS)
        assert DateParser.parse(items[0]["published_date"], language="ms") == "2024-01-15"
        assert DateParser.parse(items[1]["published_date"], language="ms") == "2023-03-20"
        assert DateParser.parse(items[2]["published_date"], language="ms") == "2023-02-05"

    def test_parse_docman_empty_table(self):
        """Empty tbody returns empty list, not an error."""
        items = HTMLParser.parse_listing_page(
            SAMPLE_DOCMAN_HTML_EMPTY_TABLE, self.DOCMAN_SELECTORS
        )
        assert items == []

    def test_parse_docman_no_table(self):
        """Missing table returns empty list gracefully."""
        items = HTMLParser.parse_listing_page(
            SAMPLE_DOCMAN_HTML_NO_TABLE, self.DOCMAN_SELECTORS
        )
        assert items == []

    def test_parse_docman_header_row_excluded(self):
        """The thead header row must not appear as an item (no /file link in header)."""
        items = HTMLParser.parse_listing_page(SAMPLE_DOCMAN_HTML, self.DOCMAN_SELECTORS)
        titles = [item["title"] for item in items]
        assert "Tajuk" not in titles
        assert "Tarikh" not in titles
