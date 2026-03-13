from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ListingItem:
    """An item discovered from a MOE listing page (table#example row)."""

    url: str
    title: str
    date_str: str | None  # raw date string as it appears in the listing, e.g. "12 Feb 2026"


@dataclass(slots=True)
class CrawlStats:
    discovered: int = 0
    fetched: int = 0
    uploaded: int = 0
    deduped: int = 0
    changed: int = 0
    skipped: int = 0
    failed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "discovered": self.discovered,
            "fetched": self.fetched,
            "uploaded": self.uploaded,
            "deduped": self.deduped,
            "changed": self.changed,
            "skipped": self.skipped,
            "failed": self.failed,
        }
