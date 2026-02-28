"""Incremental indexing state contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndexedFingerprintRecord:
    """Recorded version identity for one indexed object."""

    storage_path: str
    version_token: str
    document_count: int = 0


class IndexedFingerprintStore:
    """Abstract storage for already-indexed object versions."""

    def has_fingerprint(self, storage_path: str, version_token: str) -> bool:
        raise NotImplementedError

    def mark_indexed(
        self,
        storage_path: str,
        version_token: str,
        *,
        document_count: int = 0,
    ) -> IndexedFingerprintRecord:
        raise NotImplementedError


class InMemoryFingerprintStore(IndexedFingerprintStore):
    """Simple in-memory implementation used by tests and dry runs."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], IndexedFingerprintRecord] = {}

    def has_fingerprint(self, storage_path: str, version_token: str) -> bool:
        return (storage_path, version_token) in self._records

    def mark_indexed(
        self,
        storage_path: str,
        version_token: str,
        *,
        document_count: int = 0,
    ) -> IndexedFingerprintRecord:
        record = IndexedFingerprintRecord(
            storage_path=storage_path,
            version_token=version_token,
            document_count=document_count,
        )
        self._records[(storage_path, version_token)] = record
        return record
