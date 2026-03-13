"""
Strapi v3 record extraction for bheuu.gov.my.

bheuu.gov.my uses Strapi v3 (https://strapi.bheuu.gov.my) as its CMS backend.
All content is available as JSON from the Strapi REST API — no HTML parsing.

Strapi v3 conventions used here:
  - Collection endpoints return JSON arrays; single-type endpoints return a dict.
  - Pagination via _start (offset) + _limit.
  - Files are stored as nested objects with a "url" field (relative /uploads/...).
  - Date fields: publishDate (YYYY-MM-DD), createdAt / updatedAt (ISO 8601 datetime),
    published_at (ISO 8601 datetime), year (string "2010").

File URL patterns:
  - Absolute full URL: "https://strapi.bheuu.gov.my/uploads/..."  → use as-is
  - Relative path:     "/uploads/..."  → prepend strapi_base
"""
from __future__ import annotations

import logging
from typing import Optional

from dateutil import parser as dateutil_parser

log = logging.getLogger(__name__)

STRAPI_BASE = "https://strapi.bheuu.gov.my"


# ── Date parsing ──────────────────────────────────────────────────────────────


def parse_strapi_date(value: Optional[str]) -> str:
    """
    Parse a Strapi date/datetime string to an ISO 8601 date (YYYY-MM-DD).

    Handles:
      - "YYYY-MM-DD"                    (publishDate, startDate, resultDate)
      - "YYYY-MM-DDTHH:MM:SS.mmmZ"     (createdAt, updatedAt, published_at)
      - "YYYY" or plain year string     (year field in act-protection-archives)

    Returns "" on failure.
    """
    if not value or not value.strip():
        return ""
    value = value.strip()

    # Plain year e.g. "2010"
    if len(value) == 4 and value.isdigit():
        return f"{value}-01-01"

    try:
        dt = dateutil_parser.parse(value)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        return ""


# ── Field extraction helpers ──────────────────────────────────────────────────


def _get_nested(data: dict, dotted_key: str) -> Optional[str]:
    """
    Traverse *data* with a dot-separated key path, return the leaf string.

    Example: _get_nested(rec, "fileName.url") → rec["fileName"]["url"]
    Returns None if any step is missing or the leaf is not a string.
    """
    keys = dotted_key.split(".")
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    if current is None:
        return None
    return str(current) if not isinstance(current, str) else current


def resolve_file_url(raw: Optional[str]) -> str:
    """
    Convert a Strapi file URL to a full HTTPS URL.

    Strapi stores files as either:
      - "/uploads/filename.pdf"                      → prepend strapi base
      - "https://strapi.bheuu.gov.my/uploads/..."   → use as-is
    """
    if not raw:
        return ""
    raw = raw.strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if raw.startswith("/"):
        return f"{STRAPI_BASE}{raw}"
    return raw


def extract_title(record: dict, title_field: str) -> str:
    """Extract the title string from a Strapi record."""
    value = _get_nested(record, title_field) or ""
    # Fallback chains for known title field variants
    if not value and title_field == "title":
        value = (
            record.get("titleEN")
            or record.get("titleBM")
            or record.get("tenderTitle")
            or ""
        )
    return value.strip()


def extract_date(record: dict, date_field: str) -> str:
    """
    Extract and normalise the publication date from a Strapi record.

    Tries *date_field* first, then falls back through common date fields
    in order of preference.
    """
    raw = _get_nested(record, date_field) if date_field else None
    if not raw:
        # fallback priority: publishDate → published_at → startDate → createdAt
        for fallback in ("publishDate", "published_at", "startDate", "resultDate", "createdAt"):
            raw = record.get(fallback)
            if raw:
                break
    return parse_strapi_date(raw)


def extract_file_url(record: dict, file_field: str) -> str:
    """
    Extract the raw file URL from a Strapi record using the configured field path.

    Returns a fully-resolved HTTPS URL, or "" if not found.
    """
    raw = _get_nested(record, file_field) if file_field else None
    return resolve_file_url(raw)


def extract_record_id(record: dict) -> str:
    """Return the Strapi record id (_id or id)."""
    return str(record.get("_id") or record.get("id") or "")


# ── Content-type guessing ─────────────────────────────────────────────────────

_EXT_TO_MIME = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".zip": "application/zip",
}


def guess_content_type(url: str) -> str:
    """Return MIME type based on URL file extension, defaulting to application/pdf."""
    lower = url.lower().split("?")[0]
    for ext, mime in _EXT_TO_MIME.items():
        if lower.endswith(ext):
            return mime
    return "application/pdf"
