from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class UrlState:
    canonical_url: str
    source_url: str
    sha256: str | None
    http_etag: str | None
    http_last_modified: str | None
    gcs_bucket: str | None
    gcs_object: str | None
    gcs_uri: str | None


@dataclass(slots=True)
class PayloadState:
    sha256: str
    gcs_bucket: str | None
    gcs_object: str | None
    gcs_uri: str | None


class StateStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS payloads (
              sha256 TEXT PRIMARY KEY,
              gcs_bucket TEXT,
              gcs_object TEXT,
              gcs_uri TEXT,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS records (
              canonical_url TEXT PRIMARY KEY,
              source_url TEXT NOT NULL,
              sha256 TEXT,
              http_etag TEXT,
              http_last_modified TEXT,
              gcs_bucket TEXT,
              gcs_object TEXT,
              gcs_uri TEXT,
              fetched_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1,
              FOREIGN KEY (sha256) REFERENCES payloads(sha256)
            );
            """
        )
        self.conn.commit()

    def get_url_state(self, canonical_url: str) -> UrlState | None:
        row = self.conn.execute(
            """
            SELECT canonical_url, source_url, sha256, http_etag, http_last_modified, gcs_bucket, gcs_object, gcs_uri
            FROM records
            WHERE canonical_url = ?
            """,
            (canonical_url,),
        ).fetchone()
        if not row:
            return None
        return UrlState(**dict(row))

    def get_payload(self, sha256: str) -> PayloadState | None:
        row = self.conn.execute(
            """
            SELECT sha256, gcs_bucket, gcs_object, gcs_uri
            FROM payloads
            WHERE sha256 = ?
            """,
            (sha256,),
        ).fetchone()
        if not row:
            return None
        return PayloadState(**dict(row))

    def upsert_payload(
        self,
        sha256: str,
        gcs_bucket: str | None,
        gcs_object: str | None,
        gcs_uri: str | None,
        created_at: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO payloads (sha256, gcs_bucket, gcs_object, gcs_uri, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(sha256) DO UPDATE SET
              gcs_bucket = excluded.gcs_bucket,
              gcs_object = excluded.gcs_object,
              gcs_uri = excluded.gcs_uri
            """,
            (sha256, gcs_bucket, gcs_object, gcs_uri, created_at),
        )
        self.conn.commit()

    def upsert_record(
        self,
        canonical_url: str,
        source_url: str,
        sha256: str,
        http_etag: str | None,
        http_last_modified: str | None,
        gcs_bucket: str | None,
        gcs_object: str | None,
        gcs_uri: str | None,
        fetched_at: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO records (
              canonical_url, source_url, sha256, http_etag, http_last_modified,
              gcs_bucket, gcs_object, gcs_uri, fetched_at, last_seen_at, active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(canonical_url) DO UPDATE SET
              source_url = excluded.source_url,
              sha256 = excluded.sha256,
              http_etag = excluded.http_etag,
              http_last_modified = excluded.http_last_modified,
              gcs_bucket = excluded.gcs_bucket,
              gcs_object = excluded.gcs_object,
              gcs_uri = excluded.gcs_uri,
              fetched_at = excluded.fetched_at,
              last_seen_at = excluded.last_seen_at,
              active = 1
            """,
            (
                canonical_url,
                source_url,
                sha256,
                http_etag,
                http_last_modified,
                gcs_bucket,
                gcs_object,
                gcs_uri,
                fetched_at,
                fetched_at,
            ),
        )
        self.conn.commit()

    def mark_inactive_missing(self, seen_canonical_urls: set[str], seen_at: str) -> None:
        placeholders = ",".join("?" for _ in seen_canonical_urls)
        if not placeholders:
            self.conn.execute("UPDATE records SET active = 0, last_seen_at = ?", (seen_at,))
        else:
            self.conn.execute(
                f"UPDATE records SET active = 0, last_seen_at = ? WHERE canonical_url NOT IN ({placeholders})",
                (seen_at, *seen_canonical_urls),
            )
        self.conn.commit()
