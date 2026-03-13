"""
SQLite-backed state store for deduplication and run tracking.

Deduplication strategy:
  1. Pre-fetch:  if canonical_url already exists → skip.
  2. Post-fetch: if sha256 already in DB → reuse existing spaces_url, skip re-upload.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .models import Record


class StateStore:
    """Thread-safe (single connection) SQLite state store."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                record_id          TEXT PRIMARY KEY,
                canonical_url      TEXT UNIQUE NOT NULL,
                sha256             TEXT,
                spaces_url         TEXT,
                spaces_path        TEXT,
                http_etag          TEXT,
                http_last_modified TEXT,
                fetched_at         TEXT,
                status             TEXT DEFAULT 'active'
            );

            CREATE INDEX IF NOT EXISTS idx_sha256
                ON documents(sha256);

            CREATE INDEX IF NOT EXISTS idx_canonical_url
                ON documents(canonical_url);

            CREATE TABLE IF NOT EXISTS crawl_runs (
                crawl_run_id  TEXT PRIMARY KEY,
                site_slug     TEXT NOT NULL,
                started_at    TEXT,
                completed_at  TEXT,
                new_count     INTEGER DEFAULT 0,
                changed_count INTEGER DEFAULT 0,
                skipped_count INTEGER DEFAULT 0,
                failed_count  INTEGER DEFAULT 0
            );
            """
        )
        self.conn.commit()

    # ── Read operations ───────────────────────────────────────────────────────

    def get_by_url(self, canonical_url: str) -> Optional[sqlite3.Row]:
        """Return the stored row for a canonical URL, or None."""
        cur = self.conn.execute(
            "SELECT * FROM documents WHERE canonical_url = ?",
            (canonical_url,),
        )
        return cur.fetchone()

    def get_spaces_url_by_sha256(self, sha256: str) -> Optional[str]:
        """Return an existing spaces_url for content already uploaded, or None."""
        cur = self.conn.execute(
            "SELECT spaces_url FROM documents "
            "WHERE sha256 = ? AND spaces_url IS NOT NULL LIMIT 1",
            (sha256,),
        )
        row = cur.fetchone()
        return row["spaces_url"] if row else None

    def get_spaces_path_by_sha256(self, sha256: str) -> Optional[str]:
        """Return an existing spaces_path for content already uploaded, or None."""
        cur = self.conn.execute(
            "SELECT spaces_path FROM documents "
            "WHERE sha256 = ? AND spaces_path IS NOT NULL LIMIT 1",
            (sha256,),
        )
        row = cur.fetchone()
        return row["spaces_path"] if row else None

    # ── Write operations ──────────────────────────────────────────────────────

    def upsert_record(self, record: Record) -> None:
        """Insert or update a document record."""
        self.conn.execute(
            """
            INSERT INTO documents
                (record_id, canonical_url, sha256, spaces_url, spaces_path,
                 http_etag, http_last_modified, fetched_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
            ON CONFLICT(canonical_url) DO UPDATE SET
                sha256             = excluded.sha256,
                spaces_url         = excluded.spaces_url,
                spaces_path        = excluded.spaces_path,
                http_etag          = excluded.http_etag,
                http_last_modified = excluded.http_last_modified,
                fetched_at         = excluded.fetched_at,
                status             = 'active'
            """,
            (
                record.record_id,
                record.canonical_url,
                record.sha256,
                record.spaces_url,
                record.spaces_path,
                record.http_etag,
                record.http_last_modified,
                record.fetched_at,
            ),
        )
        self.conn.commit()

    def save_crawl_run(
        self,
        crawl_run_id: str,
        site_slug: str,
        started_at: str,
        completed_at: str,
        new_count: int,
        changed_count: int,
        skipped_count: int,
        failed_count: int,
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO crawl_runs
                (crawl_run_id, site_slug, started_at, completed_at,
                 new_count, changed_count, skipped_count, failed_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                crawl_run_id,
                site_slug,
                started_at,
                completed_at,
                new_count,
                changed_count,
                skipped_count,
                failed_count,
            ),
        )
        self.conn.commit()

    def mark_inactive(self, canonical_url: str) -> None:
        """Soft-delete a URL that is no longer reachable."""
        self.conn.execute(
            "UPDATE documents SET status = 'inactive' WHERE canonical_url = ?",
            (canonical_url,),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
