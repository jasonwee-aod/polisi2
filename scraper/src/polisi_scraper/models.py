"""Typed metadata contracts shared by adapters, runner, and persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
import re


SUPPORTED_FILE_TYPES = {"html", "pdf", "docx", "xlsx"}


@dataclass(frozen=True)
class DocumentRecord:
    """Normalized scraper output for one discovered government document."""

    source_url: str
    title: str
    agency: str
    file_type: str
    sha256: str
    filename: str
    discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: date | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.file_type not in SUPPORTED_FILE_TYPES:
            raise ValueError(f"Unsupported file type: {self.file_type}")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.sha256):
            raise ValueError("sha256 must be a 64-char hex digest")

    @property
    def normalized_agency(self) -> str:
        clean = re.sub(r"[^a-z0-9]+", "-", self.agency.lower()).strip("-")
        return clean or "unknown-agency"

    @property
    def year_month(self) -> str:
        source = self.published_at or self.discovered_at.date()
        return source.strftime("%Y-%m")

    def build_filename(self, changed_on: date | None = None) -> str:
        """Keep original filename; append date suffix only for changed versions."""
        if changed_on is None:
            return self.filename

        path = Path(self.filename)
        suffix = changed_on.isoformat()
        return f"{path.stem}_{suffix}{path.suffix}"

    def storage_path(self, changed_on: date | None = None) -> str:
        name = self.build_filename(changed_on=changed_on)
        return f"gov-my/{self.normalized_agency}/{self.year_month}/{name}"

    def to_documents_row(self, changed_on: date | None = None) -> dict[str, object]:
        return {
            "title": self.title,
            "source_url": self.source_url,
            "agency": self.agency,
            "published_at": self.published_at,
            "file_type": self.file_type,
            "sha256": self.sha256,
            "storage_path": self.storage_path(changed_on=changed_on),
            "metadata": self.metadata,
            "scraped_at": self.discovered_at,
        }


@dataclass(frozen=True)
class CrawlRunMetadata:
    run_id: str
    adapter_slug: str
    started_at: datetime
    finished_at: datetime | None
    source_pages_discovered: int
    documents_emitted: int
    documents_skipped: int


@dataclass(frozen=True)
class AdapterOutputEnvelope:
    adapter_slug: str
    records: list[DocumentRecord]
    crawl_run: CrawlRunMetadata
