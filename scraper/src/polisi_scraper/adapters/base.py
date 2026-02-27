"""Base contract for all government site adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from polisi_scraper.models import DocumentRecord


@dataclass(frozen=True)
class DocumentCandidate:
    source_page_url: str
    document_url: str
    title: str
    file_type: str
    published_at: date | None = None
    filename: str | None = None


class BaseSiteAdapter(ABC):
    """Common adapter contract used by the runner orchestration."""

    slug: str
    agency: str

    @abstractmethod
    def iter_document_candidates(self, max_docs: int | None = None) -> list[DocumentCandidate]:
        """Return normalized document candidates for this source."""

    def to_record(
        self,
        candidate: DocumentCandidate,
        *,
        sha256: str,
        discovered_at: datetime | None = None,
    ) -> DocumentRecord:
        return DocumentRecord(
            source_url=candidate.document_url,
            title=candidate.title,
            agency=self.agency,
            file_type=candidate.file_type,
            sha256=sha256,
            filename=candidate.filename or infer_filename(candidate.document_url, candidate.file_type),
            discovered_at=discovered_at or datetime.now(timezone.utc),
            published_at=candidate.published_at,
            metadata={
                "adapter": self.slug,
                "source_page_url": candidate.source_page_url,
            },
        )


def infer_filename(url: str, fallback_type: str) -> str:
    path = unquote(urlparse(url).path)
    basename = Path(path).name
    if basename:
        return basename
    return f"document.{fallback_type}"
