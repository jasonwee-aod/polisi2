"""Persistent crawl state for resumable adapter runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path


@dataclass(frozen=True)
class ProcessedDocument:
    adapter_slug: str
    source_url: str
    sha256: str
    storage_path: str
    processed_at: str


class CrawlStateStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._ensure_parent_dir()
        self._init_schema()

    @property
    def db_path(self) -> str:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_parent_dir(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists processed_documents (
                  adapter_slug text not null,
                  source_url text not null,
                  sha256 text not null,
                  storage_path text not null,
                  processed_at text not null,
                  primary key (adapter_slug, source_url, sha256)
                )
                """
            )
            conn.execute(
                """
                create table if not exists checkpoints (
                  adapter_slug text primary key,
                  last_source_url text,
                  state_json text,
                  updated_at text not null
                )
                """
            )

    def get_latest_sha256(self, adapter_slug: str, source_url: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select sha256
                from processed_documents
                where adapter_slug = ? and source_url = ?
                order by processed_at desc
                limit 1
                """,
                (adapter_slug, source_url),
            ).fetchone()
        return row["sha256"] if row else None

    def is_already_processed(self, adapter_slug: str, source_url: str, sha256: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                select 1
                from processed_documents
                where adapter_slug = ? and source_url = ? and sha256 = ?
                limit 1
                """,
                (adapter_slug, source_url, sha256),
            ).fetchone()
        return row is not None

    def mark_processed(self, adapter_slug: str, source_url: str, sha256: str, storage_path: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert or ignore into processed_documents (
                  adapter_slug,
                  source_url,
                  sha256,
                  storage_path,
                  processed_at
                ) values (?, ?, ?, ?, ?)
                """,
                (
                    adapter_slug,
                    source_url,
                    sha256,
                    storage_path,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def list_processed_urls(self, adapter_slug: str) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "select distinct source_url from processed_documents where adapter_slug = ?",
                (adapter_slug,),
            ).fetchall()
        return {row["source_url"] for row in rows}

    def set_checkpoint(self, adapter_slug: str, last_source_url: str, state: dict[str, object] | None = None) -> None:
        payload = json.dumps(state or {}, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                """
                insert into checkpoints (adapter_slug, last_source_url, state_json, updated_at)
                values (?, ?, ?, ?)
                on conflict(adapter_slug)
                do update set
                  last_source_url = excluded.last_source_url,
                  state_json = excluded.state_json,
                  updated_at = excluded.updated_at
                """,
                (adapter_slug, last_source_url, payload, datetime.now(timezone.utc).isoformat()),
            )

    def get_checkpoint(self, adapter_slug: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                "select last_source_url, state_json, updated_at from checkpoints where adapter_slug = ?",
                (adapter_slug,),
            ).fetchone()
        if not row:
            return None
        return {
            "last_source_url": row["last_source_url"],
            "state": json.loads(row["state_json"]),
            "updated_at": row["updated_at"],
        }
