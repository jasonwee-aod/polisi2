"""SQLite-based deduplication and state management."""
import sqlite3
from pathlib import Path
from typing import Optional
from datetime import datetime


class DeduplicationStore:
    """SQLite store for tracking URLs and content hashes."""

    def __init__(self, db_path: str = ".cache/scraper_state.sqlite3"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # URLs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS urls (
                    id INTEGER PRIMARY KEY,
                    canonical_url TEXT UNIQUE NOT NULL,
                    source_url TEXT,
                    etag TEXT,
                    last_modified TEXT,
                    last_checked_at TEXT,
                    status TEXT DEFAULT 'active'
                )
            """)

            # Content hashes table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS content_hashes (
                    id INTEGER PRIMARY KEY,
                    sha256 TEXT UNIQUE NOT NULL,
                    spaces_path TEXT,
                    content_type TEXT,
                    first_seen_at TEXT
                )
            """)

            # Crawl runs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS crawl_runs (
                    crawl_run_id TEXT PRIMARY KEY,
                    site_slug TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    discovered INTEGER DEFAULT 0,
                    fetched INTEGER DEFAULT 0,
                    uploaded INTEGER DEFAULT 0,
                    deduped INTEGER DEFAULT 0,
                    failed INTEGER DEFAULT 0
                )
            """)

            conn.commit()

    def url_exists(self, canonical_url: str) -> bool:
        """Check if canonical URL already exists."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM urls WHERE canonical_url = ? AND status = 'active'",
                (canonical_url,)
            )
            return cursor.fetchone() is not None

    def hash_exists(self, sha256: str) -> Optional[str]:
        """Check if content hash exists, return spaces_path if found."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT spaces_path FROM content_hashes WHERE sha256 = ?",
                (sha256,)
            )
            result = cursor.fetchone()
            return result[0] if result else None

    def store_url(
        self,
        canonical_url: str,
        source_url: str,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
    ):
        """Store or update URL entry."""
        now = datetime.utcnow().isoformat() + "Z"
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO urls
                (canonical_url, source_url, etag, last_modified, last_checked_at, status)
                VALUES (?, ?, ?, ?, ?, 'active')
            """, (canonical_url, source_url, etag, last_modified, now))
            conn.commit()

    def store_hash(
        self,
        sha256: str,
        spaces_path: str,
        content_type: str,
    ):
        """Store content hash mapping."""
        now = datetime.utcnow().isoformat() + "Z"
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO content_hashes
                (sha256, spaces_path, content_type, first_seen_at)
                VALUES (?, ?, ?, ?)
            """, (sha256, spaces_path, content_type, now))
            conn.commit()

    def get_url_headers(self, canonical_url: str) -> tuple:
        """Get stored etag and last_modified for URL."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT etag, last_modified FROM urls WHERE canonical_url = ?",
                (canonical_url,)
            )
            result = cursor.fetchone()
            return result if result else (None, None)

    def start_crawl_run(self, crawl_run_id: str, site_slug: str) -> str:
        """Record start of crawl run."""
        now = datetime.utcnow().isoformat() + "Z"
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO crawl_runs
                (crawl_run_id, site_slug, started_at)
                VALUES (?, ?, ?)
            """, (crawl_run_id, site_slug, now))
            conn.commit()
        return crawl_run_id

    def update_crawl_run(
        self,
        crawl_run_id: str,
        discovered: int = 0,
        fetched: int = 0,
        uploaded: int = 0,
        deduped: int = 0,
        failed: int = 0,
    ):
        """Update crawl run metrics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE crawl_runs SET
                discovered = ?, fetched = ?, uploaded = ?,
                deduped = ?, failed = ?
                WHERE crawl_run_id = ?
            """, (discovered, fetched, uploaded, deduped, failed, crawl_run_id))
            conn.commit()

    def end_crawl_run(self, crawl_run_id: str):
        """Mark crawl run as completed."""
        now = datetime.utcnow().isoformat() + "Z"
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE crawl_runs SET completed_at = ? WHERE crawl_run_id = ?",
                (now, crawl_run_id)
            )
            conn.commit()
