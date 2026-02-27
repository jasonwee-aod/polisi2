"""Dedup helpers for content hashing and versioned filenames."""

from __future__ import annotations

from datetime import date
import hashlib
from pathlib import Path


def compute_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def is_content_changed(previous_sha256: str | None, current_sha256: str) -> bool:
    return previous_sha256 is not None and previous_sha256 != current_sha256


def build_versioned_filename(filename: str, changed_on: date | None) -> str:
    if changed_on is None:
        return filename

    path = Path(filename)
    return f"{path.stem}_{changed_on.isoformat()}{path.suffix}"
