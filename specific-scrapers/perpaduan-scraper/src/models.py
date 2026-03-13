"""Data models for Perpaduan scraper."""
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
import json
import uuid


@dataclass
class ScrapedRecord:
    """Represents a single scraped record."""
    source_url: str
    canonical_url: str
    title: str
    published_at: Optional[str]
    agency: str
    doc_type: str  # press_release, statement, report, notice, news, other
    content_type: str
    language: str
    sha256: Optional[str] = None
    spaces_bucket: Optional[str] = None
    spaces_path: Optional[str] = None
    spaces_url: Optional[str] = None
    http_etag: Optional[str] = None
    http_last_modified: Optional[str] = None
    fetched_at: Optional[str] = None
    crawl_run_id: Optional[str] = None
    parser_version: str = "v1"
    record_id: Optional[str] = None

    def __post_init__(self):
        if not self.record_id:
            self.record_id = str(uuid.uuid4())
        if not self.fetched_at:
            self.fetched_at = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class CrawlRun:
    """Summary of a single crawl run."""
    crawl_run_id: str
    site_slug: str
    started_at: str
    completed_at: Optional[str] = None
    discovered: int = 0
    fetched: int = 0
    uploaded: int = 0
    deduped: int = 0
    failed: int = 0
    error_details: dict = None

    def __post_init__(self):
        if self.error_details is None:
            self.error_details = {}

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())
