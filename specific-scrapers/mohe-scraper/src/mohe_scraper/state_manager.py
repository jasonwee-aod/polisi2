"""State management for deduplication and incremental crawling."""

import sqlite3
import json
from datetime import datetime
from typing import Optional
from pathlib import Path
import logging

from mohe_scraper.models import StateRecord

logger = logging.getLogger(__name__)


class StateManager:
    """Manages deduplication state in SQLite database."""

    def __init__(self, db_path: str):
        """
        Initialize state manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_url TEXT NOT NULL UNIQUE,
                    sha256 TEXT NOT NULL UNIQUE,
                    http_etag TEXT,
                    http_last_modified TEXT,
                    gcs_uri TEXT,
                    last_seen_at TEXT NOT NULL,
                    doc_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_canonical_url ON state_records(canonical_url)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sha256 ON state_records(sha256)"
            )
            conn.commit()

    def check_url_exists(self, canonical_url: str) -> Optional[StateRecord]:
        """Check if URL already exists in state."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM state_records WHERE canonical_url = ?",
                (canonical_url,)
            )
            row = cursor.fetchone()
            return self._row_to_state_record(row) if row else None

    def check_hash_exists(self, sha256: str) -> Optional[StateRecord]:
        """Check if hash already exists (content dedup)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM state_records WHERE sha256 = ?",
                (sha256,)
            )
            row = cursor.fetchone()
            return self._row_to_state_record(row) if row else None

    def save_record(self, record: StateRecord):
        """Save or update a record in state."""
        now = datetime.utcnow().isoformat() + "Z"
        with sqlite3.connect(self.db_path) as conn:
            # Try to update first
            cursor = conn.execute(
                """
                UPDATE state_records
                SET sha256 = ?, http_etag = ?, http_last_modified = ?, gcs_uri = ?,
                    last_seen_at = ?, is_active = ?, updated_at = ?
                WHERE canonical_url = ?
                """,
                (
                    record.sha256,
                    record.http_etag,
                    record.http_last_modified,
                    record.gcs_uri,
                    record.last_seen_at,
                    record.is_active,
                    now,
                    record.canonical_url,
                )
            )

            # If no rows updated, insert
            if cursor.rowcount == 0:
                conn.execute(
                    """
                    INSERT INTO state_records
                    (canonical_url, sha256, http_etag, http_last_modified, gcs_uri,
                     last_seen_at, doc_type, title, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.canonical_url,
                        record.sha256,
                        record.http_etag,
                        record.http_last_modified,
                        record.gcs_uri,
                        record.last_seen_at,
                        record.doc_type,
                        record.title,
                        record.is_active,
                        now,
                        now,
                    )
                )
            conn.commit()

    def mark_inactive(self, canonical_url: str):
        """Mark a URL as inactive (removed from site)."""
        now = datetime.utcnow().isoformat() + "Z"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE state_records SET is_active = 0, updated_at = ? WHERE canonical_url = ?",
                (now, canonical_url)
            )
            conn.commit()

    def get_stats(self) -> dict:
        """Get statistics about stored state."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) as total, SUM(is_active) as active FROM state_records"
            )
            row = cursor.fetchone()
            total, active = row if row else (0, 0)
            return {
                "total_records": total,
                "active_records": active,
                "inactive_records": total - (active or 0)
            }

    @staticmethod
    def _row_to_state_record(row) -> StateRecord:
        """Convert SQLite row to StateRecord."""
        return StateRecord(
            canonical_url=row["canonical_url"],
            sha256=row["sha256"],
            http_etag=row["http_etag"],
            http_last_modified=row["http_last_modified"],
            gcs_uri=row["gcs_uri"],
            last_seen_at=row["last_seen_at"],
            doc_type=row["doc_type"],
            title=row["title"],
            is_active=bool(row["is_active"])
        )
