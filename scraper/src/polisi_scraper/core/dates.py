"""Consolidated Malay date parser shared across all adapters."""

from __future__ import annotations

import re
from datetime import date

from dateutil import parser as date_parser

MALAY_MONTHS: dict[str, str] = {
    "januari": "January",
    "februari": "February",
    "mac": "March",
    "april": "April",
    "mei": "May",
    "jun": "June",
    "julai": "July",
    "ogos": "August",
    "september": "September",
    "oktober": "October",
    "november": "November",
    "disember": "December",
}

MALAY_MONTHS_ABBR: dict[str, str] = {
    "jan": "Jan",
    "feb": "Feb",
    "mac": "Mar",
    "apr": "Apr",
    "mei": "May",
    "jun": "Jun",
    "jul": "Jul",
    "ogo": "Aug",
    "sep": "Sep",
    "okt": "Oct",
    "nov": "Nov",
    "dis": "Dec",
}

MALAY_DAYS: set[str] = {
    "isnin", "selasa", "rabu", "khamis", "jumaat", "sabtu", "ahad",
}


def translate_malay_date(text: str) -> str:
    """Replace Malay month names and day names with English equivalents."""
    result = text
    lower = result.lower()

    # Remove day names (e.g. "SELASA" from "18 FEB 2025 SELASA")
    for day in MALAY_DAYS:
        lower = re.sub(rf"\b{day}\b", "", lower, flags=re.IGNORECASE)
        result = re.sub(rf"\b{day}\b", "", result, flags=re.IGNORECASE)

    # Replace full month names (case-insensitive)
    for malay, english in MALAY_MONTHS.items():
        result = re.sub(rf"\b{malay}\b", english, result, flags=re.IGNORECASE)

    # Replace abbreviated month names
    for malay, english in MALAY_MONTHS_ABBR.items():
        result = re.sub(rf"\b{malay}\b", english, result, flags=re.IGNORECASE)

    return result.strip()


def parse_malay_date(text: str) -> str:
    """Parse a date string that may contain Malay month names.

    Returns ISO 8601 date string (YYYY-MM-DD) or empty string on failure.
    """
    if not text or not text.strip():
        return ""

    translated = translate_malay_date(text.strip())
    if not translated:
        return ""

    # Try direct ISO parse first
    iso_match = re.match(r"(\d{4}-\d{2}-\d{2})", translated)
    if iso_match:
        return iso_match.group(1)

    # Strip ordinal suffixes (1st, 2nd, 3rd, 4th, etc.)
    translated = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", translated)

    # Clean separators
    translated = translated.replace("|", " ").replace("•", " ")
    translated = re.sub(r"\s+", " ", translated).strip()

    try:
        dt = date_parser.parse(translated, fuzzy=True, dayfirst=True)
        return dt.date().isoformat()
    except (ValueError, TypeError, OverflowError):
        pass

    # Year-only fallback
    year_match = re.search(r"\b((?:19|20)\d{2})\b", text)
    if year_match:
        return f"{year_match.group(1)}-01-01"

    return ""


def parse_iso_date(text: str) -> str:
    """Parse ISO 8601 datetime or date string to YYYY-MM-DD."""
    if not text or not text.strip():
        return ""
    try:
        dt = date_parser.parse(text.strip())
        return dt.date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return ""
