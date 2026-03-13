"""
Data models for scraped records and crawl run metadata.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

PARSER_VERSION = "v1"


@dataclass
class Record:
    """A single scraped document with full provenance."""

    record_id: str
    source_url: str           # Original listing-page URL where the link was found
    canonical_url: str        # Normalized document URL used for dedup
    title: str
    published_at: str         # ISO 8601 date, e.g. "2025-12-04", or ""
    agency: str
    doc_type: str             # press_release | circular | speech | report | other
    content_type: str         # application/pdf | text/html | ...
    language: str             # ms | en
    sha256: str               # Hex digest of raw file bytes
    gcs_bucket: str
    gcs_object: str
    gcs_uri: str              # gs://<bucket>/<object>
    http_etag: str            # ETag response header, or ""
    http_last_modified: str   # Last-Modified response header, or ""
    fetched_at: str           # UTC ISO 8601 datetime
    crawl_run_id: str
    parser_version: str = PARSER_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class CrawlRun:
    """Summary statistics for one crawl execution."""

    crawl_run_id: str
    site_slug: str
    started_at: str
    completed_at: str = ""
    new_count: int = 0
    changed_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
