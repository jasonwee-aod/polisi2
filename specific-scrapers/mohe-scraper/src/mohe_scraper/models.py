"""Data models for MOHE scraper records."""

from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional
import hashlib
import json


@dataclass
class ScraperRecord:
    """Represents a single scraped document or announcement."""

    record_id: str
    source_url: str
    canonical_url: str
    title: str
    published_at: Optional[str]  # ISO 8601 format
    agency: str
    doc_type: str  # announcement, press_release, report, speech, notice, circular, form, manual, guideline, other
    content_type: str  # text/html, application/pdf, etc.
    language: str  # en, ms
    sha256: str
    fetched_at: str  # ISO 8601 format, UTC
    http_etag: Optional[str] = None
    http_last_modified: Optional[str] = None
    gcs_bucket: Optional[str] = None
    gcs_object: Optional[str] = None
    gcs_uri: Optional[str] = None
    crawl_run_id: Optional[str] = None
    parser_version: str = "v1"

    def to_jsonl(self) -> str:
        """Serialize to JSONL format."""
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls, data: dict) -> "ScraperRecord":
        """Create from dictionary."""
        return cls(**data)


@dataclass
class CrawlRun:
    """Represents a single crawl execution."""

    crawl_run_id: str
    site_slug: str
    started_at: str  # ISO 8601 format, UTC
    completed_at: Optional[str] = None
    status: str = "running"  # running, completed, failed
    total_urls_discovered: int = 0
    total_items_fetched: int = 0
    total_items_uploaded: int = 0
    total_items_deduped: int = 0
    total_items_failed: int = 0
    errors: list = field(default_factory=list)  # List of error messages
    dry_run: bool = False

    def to_jsonl(self) -> str:
        """Serialize to JSONL format."""
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls, data: dict) -> "CrawlRun":
        """Create from dictionary."""
        return cls(**data)


@dataclass
class StateRecord:
    """Represents a record in the dedup state database."""

    canonical_url: str
    sha256: str
    http_etag: Optional[str]
    http_last_modified: Optional[str]
    gcs_uri: Optional[str]
    last_seen_at: str  # ISO 8601 format
    doc_type: str
    title: str
    is_active: bool = True


def generate_record_id(canonical_url: str, language: str) -> str:
    """Generate stable record ID from URL and language."""
    combined = f"{canonical_url}#{language}".encode('utf-8')
    return hashlib.sha256(combined).hexdigest()[:16]


def generate_gcs_path(site_slug: str, sha256: str, original_filename: str) -> str:
    """Generate GCS object path following convention."""
    now = datetime.utcnow()
    year = f"{now.year:04d}"
    month = f"{now.month:02d}"
    day = f"{now.day:02d}"

    # Extract extension from original filename
    ext = ""
    if "." in original_filename:
        ext = "." + original_filename.rsplit(".", 1)[-1]

    return f"gov-docs/{site_slug}/raw/{year}/{month}/{day}/{sha256}{ext}"
