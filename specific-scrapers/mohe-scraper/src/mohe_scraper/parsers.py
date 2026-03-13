"""Parsers for extracting records from RSS feeds and HTML pages."""

import logging
import re
from datetime import datetime
from typing import Optional, List
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)


class RSSParser:
    """Parse RSS 2.0 feeds from MOHE."""

    @staticmethod
    def parse_feed(rss_content: str) -> List[dict]:
        """
        Parse RSS feed and extract items.

        Args:
            rss_content: Raw RSS XML content

        Returns:
            List of item dictionaries with fields: title, link, description, pubDate
        """
        try:
            root = ET.fromstring(rss_content)
            items = []

            # Handle RSS 2.0 namespace variations
            for item in root.findall(".//item"):
                item_data = {}

                # Extract standard RSS fields
                title_elem = item.find("title")
                item_data["title"] = title_elem.text if title_elem is not None else "Untitled"

                link_elem = item.find("link")
                item_data["link"] = link_elem.text if link_elem is not None else None

                desc_elem = item.find("description")
                item_data["description"] = desc_elem.text if desc_elem is not None else ""

                # Handle pubDate variations (RSS standard, different formats)
                pubdate_elem = item.find("pubDate")
                item_data["pubDate"] = pubdate_elem.text if pubdate_elem is not None else None

                # Handle enclosures (attachments/files)
                enclosures = []
                for enclosure in item.findall("enclosure"):
                    enclosures.append({
                        "url": enclosure.get("url"),
                        "type": enclosure.get("type"),
                        "length": enclosure.get("length")
                    })
                item_data["enclosures"] = enclosures

                if item_data["link"]:
                    items.append(item_data)

            logger.info(f"Parsed {len(items)} items from RSS feed")
            return items

        except ET.ParseError as e:
            logger.error(f"Failed to parse RSS feed: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error parsing RSS: {e}")
            return []

    @staticmethod
    def parse_date(date_str: Optional[str]) -> Optional[str]:
        """
        Parse date string from RSS and return ISO 8601 format.

        Args:
            date_str: Date string (often in RFC 2822 format from RSS)

        Returns:
            ISO 8601 formatted date string (YYYY-MM-DD) or None if unparseable
        """
        if not date_str:
            return None

        try:
            # dateutil is flexible and handles RSS dates well
            dt = date_parser.parse(date_str)
            return dt.strftime("%Y-%m-%d")
        except Exception as e:
            logger.warning(f"Could not parse date '{date_str}': {e}")
            return None


class HTMLParser:
    """Parse HTML listing pages from MOHE (fallback if RSS unavailable)."""

    @staticmethod
    def _is_docman_file_url(url: str) -> bool:
        """Return True if the URL is a DOCman /file endpoint (binary download)."""
        return url.rstrip("/").endswith("/file")

    @staticmethod
    def parse_listing_page(html_content: str, selectors: dict) -> List[dict]:
        """
        Parse HTML listing page and extract item links.

        Args:
            html_content: Raw HTML content
            selectors: Dictionary with CSS selectors for item_rows, title, published_date

        Returns:
            List of items with title, link, published_date, and is_file_download flag
        """
        try:
            soup = BeautifulSoup(html_content, "lxml")
            items = []

            item_rows = soup.select(selectors.get("item_rows", "tr"))
            for row in item_rows:
                title_elem = row.select_one(selectors.get("title", "a"))
                date_elem = row.select_one(selectors.get("published_date", "td:last-child"))

                if title_elem and title_elem.get("href"):
                    raw_href = title_elem.get("href")
                    items.append({
                        "title": title_elem.get_text(strip=True),
                        "link": raw_href,
                        "published_date": date_elem.get_text(strip=True) if date_elem else None,
                        "is_file_download": HTMLParser._is_docman_file_url(raw_href),
                    })

            logger.info(f"Parsed {len(items)} items from HTML listing page")
            return items

        except Exception as e:
            logger.error(f"Failed to parse HTML listing: {e}")
            return []

    @staticmethod
    def extract_next_page_url(html_content: str) -> Optional[str]:
        """
        Extract next page URL from pagination.

        Args:
            html_content: Raw HTML content

        Returns:
            Next page URL or None if no next page
        """
        try:
            soup = BeautifulSoup(html_content, "lxml")
            next_link = soup.select_one("a[rel='next']")
            return next_link.get("href") if next_link else None
        except Exception as e:
            logger.warning(f"Failed to extract next page URL: {e}")
            return None

    @staticmethod
    def extract_text_content(html_content: str) -> str:
        """
        Extract readable text content from HTML.

        Args:
            html_content: Raw HTML content

        Returns:
            Cleaned text content
        """
        try:
            soup = BeautifulSoup(html_content, "lxml")

            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()

            text = soup.get_text()

            # Clean up whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = " ".join(chunk for chunk in chunks if chunk)

            return text
        except Exception as e:
            logger.warning(f"Failed to extract text: {e}")
            return ""


class DateParser:
    """Utility for flexible date parsing with Malay month support."""

    MALAY_MONTHS = {
        "januari": "January", "februari": "February", "mac": "March", "april": "April",
        "mei": "May", "jun": "June", "julai": "July", "ogos": "August",
        "september": "September", "oktober": "October", "november": "November", "disember": "December",
    }

    @classmethod
    def parse(cls, date_str: Optional[str], language: str = "en") -> Optional[str]:
        """
        Parse date with support for Malay month names.

        Args:
            date_str: Date string
            language: Language code ('en' or 'ms')

        Returns:
            ISO 8601 formatted date (YYYY-MM-DD) or None
        """
        if not date_str:
            return None

        try:
            # Try standard dateutil first (handles RFC 2822, ISO, etc.)
            dt = date_parser.parse(date_str, fuzzy=False)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass

        # Try with Malay month replacement (swap Malay name with English equivalent)
        if language == "ms":
            modified = date_str.lower()
            for malay_month, english_month in cls.MALAY_MONTHS.items():
                modified = modified.replace(malay_month, english_month)

            try:
                dt = date_parser.parse(modified, fuzzy=False)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                pass

        logger.warning(f"Could not parse date: {date_str}")
        return None
