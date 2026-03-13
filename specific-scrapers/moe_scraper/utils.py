from __future__ import annotations

import hashlib
import os
import posixpath
import random
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from dateutil import parser as date_parser

MALAY_MONTHS = {
    "januari": "january",
    "februari": "february",
    "mac": "march",
    "april": "april",
    "mei": "may",
    "jun": "june",
    "julai": "july",
    "ogos": "august",
    "september": "september",
    "oktober": "october",
    "november": "november",
    "disember": "december",
}

MALAY_DAYS = {
    "isnin",
    "selasa",
    "rabu",
    "khamis",
    "jumaat",
    "sabtu",
    "ahad",
}

DOWNLOAD_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".ppt",
    ".pptx",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = "https"
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = parsed.path or "/"
    # Collapse duplicate slashes and remove trailing slash for non-root paths.
    path = re.sub(r"/{2,}", "/", path)
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    query_items = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    query = urlencode(sorted(query_items))
    return urlunparse((scheme, netloc, path, "", query, ""))


def is_allowed_host(url: str, allowed_hosts: set[str]) -> bool:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    normalized_allowed = {h[4:] if h.startswith("www.") else h for h in allowed_hosts}
    return host in normalized_allowed


def is_downloadable_url(url: str) -> bool:
    path = Path(urlparse(url).path.lower())
    return path.suffix in DOWNLOAD_EXTENSIONS


def stable_record_id(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:24]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def parse_http_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(UTC).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        return None


def parse_publication_date(value: str | None) -> str | None:
    if not value:
        return None

    lowered = value.lower()
    for day in MALAY_DAYS:
        lowered = re.sub(rf"\b{day}\b", "", lowered)
    for malay, english in MALAY_MONTHS.items():
        lowered = re.sub(rf"\b{malay}\b", english, lowered)

    cleaned = normalize_whitespace(lowered)
    cleaned = cleaned.replace("|", " ").replace("•", " ")
    try:
        dt = date_parser.parse(cleaned, fuzzy=True, dayfirst=True)
    except (TypeError, ValueError, OverflowError):
        return None
    return dt.date().isoformat()


def doc_type_from_text(url: str, title: str) -> str:
    text = f"{url} {title}".lower()
    if any(token in text for token in ("kenyataan media", "press release", "media release")):
        return "press_release"
    if any(token in text for token in ("kenyataan", "media", "press")):
        return "press_release"
    if any(token in text for token in ("surat siaran", "statement", "siaran")):
        return "statement"
    if any(token in text for token in ("laporan", "report")):
        return "report"
    if any(token in text for token in ("pekeliling", "circular", "pengumuman", "notice", "iklan", "arahan")):
        return "notice"
    if any(token in text for token in ("ucapan", "speech")):
        return "speech"
    return "other"


def get_rate_limit_rps(default: float = 1.0) -> float:
    raw = os.getenv("SCRAPER_RATE_LIMIT_RPS")
    if not raw:
        return default
    try:
        return max(0.1, float(raw))
    except ValueError:
        return default


def get_http_timeout(default: int = 30) -> int:
    raw = os.getenv("SCRAPER_HTTP_TIMEOUT")
    if not raw:
        return default
    try:
        return max(5, int(raw))
    except ValueError:
        return default


def polite_sleep(last_request_monotonic: float, rps: float) -> float:
    min_gap = 1.0 / max(0.1, rps)
    now = time.monotonic()
    elapsed = now - last_request_monotonic
    wait_time = max(0.0, min_gap - elapsed) + random.uniform(0.0, 0.2)
    if wait_time > 0:
        time.sleep(wait_time)
    return time.monotonic()


def make_gcs_object_path(site_slug: str, sha256: str, original_filename: str, fetched_at: str) -> str:
    dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    safe_name = original_filename or "document.bin"
    safe_name = posixpath.basename(safe_name)
    return f"gov-docs/{site_slug}/raw/{dt:%Y/%m/%d}/{sha256}_{safe_name}"


def make_spaces_object_path(sha256: str, original_filename: str, date_ref: str) -> str:
    """Generate a DO Spaces object path compatible with the Polisi indexing manifest.

    Format: polisi/gov-my/ministry-of-education/{YYYY-MM}/{sha256[:16]}_{filename}
    The manifest normalises five-segment paths of this form.
    """
    year_month = date_ref[:7]  # "YYYY-MM" from any ISO-8601 date/datetime string
    safe_name = posixpath.basename(original_filename) or "document.bin"
    safe_name = re.sub(r"[^\w.\-]", "_", safe_name)
    return f"polisi/gov-my/ministry-of-education/{year_month}/{sha256[:16]}_{safe_name}"
