"""Rich adapter interface for government site scrapers."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from polisi_scraper.core.dates import parse_malay_date
from polisi_scraper.core.extractors import DownloadLink, extract_document_links
from polisi_scraper.core.urls import canonical_url, guess_content_type, is_allowed_host, make_absolute

log = logging.getLogger(__name__)

PARSER_VERSION = "v1"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class DiscoveredItem:
    """A page or document discovered during the discover() phase."""
    source_url: str
    title: str
    published_at: str = ""       # ISO 8601 date or ""
    doc_type: str = "other"      # press_release | statement | report | notice | speech | policy | other
    language: str = "ms"
    metadata: dict = field(default_factory=dict)


@dataclass
class DocumentCandidate:
    """A concrete document to download and archive."""
    url: str
    source_page_url: str
    title: str
    published_at: str = ""
    doc_type: str = "other"
    content_type: str = ""
    language: str = "ms"
    filename: str = ""

    def infer_filename(self) -> str:
        if self.filename:
            return self.filename
        path = urlparse(self.url).path
        basename = Path(path).name
        return basename if basename else "document.bin"


@dataclass
class Record:
    """A single scraped document with full provenance."""
    record_id: str
    source_url: str
    canonical_url: str
    title: str
    published_at: str
    agency: str
    doc_type: str
    content_type: str
    language: str
    sha256: str
    spaces_bucket: str
    spaces_path: str
    spaces_url: str
    http_etag: str
    http_last_modified: str
    fetched_at: str
    crawl_run_id: str
    parser_version: str = PARSER_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class CrawlRun:
    """Summary statistics for one crawl execution."""
    crawl_run_id: str
    site_slug: str
    started_at: str
    completed_at: str = ""
    new_count: int = 0
    changed_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Per-adapter state store
# ---------------------------------------------------------------------------

import sqlite3


class AdapterStateStore:
    """Per-adapter SQLite state store for deduplication and run tracking."""

    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                canonical_url TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                sha256 TEXT,
                spaces_url TEXT,
                spaces_path TEXT,
                http_etag TEXT,
                http_last_modified TEXT,
                fetched_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_documents_sha256 ON documents(sha256);

            CREATE TABLE IF NOT EXISTS crawl_runs (
                crawl_run_id TEXT PRIMARY KEY,
                site_slug TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                new_count INTEGER DEFAULT 0,
                changed_count INTEGER DEFAULT 0,
                skipped_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0
            );
        """)
        self._conn.commit()

    def get_by_url(self, canonical_url: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM documents WHERE canonical_url = ?",
            (canonical_url,),
        ).fetchone()
        return dict(row) if row else None

    def get_spaces_url_by_sha256(self, sha256: str) -> str | None:
        row = self._conn.execute(
            "SELECT spaces_url FROM documents WHERE sha256 = ? AND spaces_url IS NOT NULL LIMIT 1",
            (sha256,),
        ).fetchone()
        return row["spaces_url"] if row else None

    def get_spaces_path_by_sha256(self, sha256: str) -> str | None:
        row = self._conn.execute(
            "SELECT spaces_path FROM documents WHERE sha256 = ? AND spaces_path IS NOT NULL LIMIT 1",
            (sha256,),
        ).fetchone()
        return row["spaces_path"] if row else None

    def sha256_exists(self, sha256: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM documents WHERE sha256 = ? LIMIT 1",
            (sha256,),
        ).fetchone()
        return row is not None

    def upsert_record(
        self,
        canonical_url: str,
        source_url: str,
        sha256: str,
        spaces_url: str,
        spaces_path: str,
        http_etag: str = "",
        http_last_modified: str = "",
        fetched_at: str = "",
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO documents (canonical_url, source_url, sha256, spaces_url, spaces_path,
                                   http_etag, http_last_modified, fetched_at, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(canonical_url) DO UPDATE SET
                source_url = excluded.source_url,
                sha256 = excluded.sha256,
                spaces_url = excluded.spaces_url,
                spaces_path = excluded.spaces_path,
                http_etag = excluded.http_etag,
                http_last_modified = excluded.http_last_modified,
                fetched_at = excluded.fetched_at,
                active = 1
            """,
            (canonical_url, source_url, sha256, spaces_url, spaces_path,
             http_etag, http_last_modified, fetched_at),
        )
        self._conn.commit()

    def mark_inactive(self, canonical_url: str) -> None:
        self._conn.execute(
            "UPDATE documents SET active = 0 WHERE canonical_url = ?",
            (canonical_url,),
        )
        self._conn.commit()

    def save_crawl_run(self, run: CrawlRun) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO crawl_runs
                (crawl_run_id, site_slug, started_at, completed_at,
                 new_count, changed_count, skipped_count, failed_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run.crawl_run_id, run.site_slug, run.started_at, run.completed_at,
             run.new_count, run.changed_count, run.skipped_count, run.failed_count),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Spaces archiver
# ---------------------------------------------------------------------------

def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def spaces_object_path(site_slug: str, sha256: str, original_url: str) -> str:
    """Build DO Spaces object path: gov-docs/<slug>/raw/YYYY/MM/DD/<sha256>_<filename>"""
    now = datetime.now(timezone.utc)
    filename = Path(urlparse(original_url).path).name or "document.bin"
    return f"gov-docs/{site_slug}/raw/{now:%Y/%m/%d}/{sha256}_{filename}"


class SpacesArchiver:
    """Upload raw document bytes to DigitalOcean Spaces."""

    def __init__(self, bucket: str, region: str, endpoint: str,
                 key: str, secret: str, dry_run: bool = False) -> None:
        self.bucket = bucket
        self.region = region
        self.dry_run = dry_run
        self._client = None
        if not dry_run:
            import boto3
            self._client = boto3.client(
                "s3",
                region_name=region,
                endpoint_url=endpoint,
                aws_access_key_id=key,
                aws_secret_access_key=secret,
            )

    def upload(self, data: bytes, object_path: str, content_type: str = "") -> str:
        """Upload bytes and return the public URL."""
        if self.dry_run:
            return f"https://{self.bucket}.{self.region}.digitaloceanspaces.com/{object_path}"

        ct = content_type or "application/octet-stream"
        self._client.put_object(
            Bucket=self.bucket,
            Key=object_path,
            Body=data,
            ContentType=ct,
        )
        return f"https://{self.bucket}.{self.region}.digitaloceanspaces.com/{object_path}"


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

class HTTPClient:
    """Requests-based HTTP client with retry, rate-limiting, and host allowlist."""

    def __init__(
        self,
        allowed_hosts: frozenset[str] | None = None,
        request_delay: float = 1.0,
        user_agent: str = "PolisiScraper/2.0 (+https://polisigpt.local)",
        verify_ssl: bool = True,
    ) -> None:
        self.allowed_hosts = allowed_hosts
        self.request_delay = request_delay
        self.verify_ssl = verify_ssl
        self._last_request_time: float = 0.0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        if not verify_ssl:
            self.session.verify = False
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self._last_request_time = time.monotonic()

    @retry(
        retry=retry_if_exception_type((requests.Timeout, requests.ConnectionError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
    def get(self, url: str, stream: bool = False) -> requests.Response:
        if self.allowed_hosts and not is_allowed_host(url, self.allowed_hosts):
            raise ValueError(f"Host not in allowlist: {urlparse(url).netloc}")
        self._throttle()
        resp = self.session.get(url, timeout=30, stream=stream)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            log.warning(f"Rate limited on {url}, sleeping {retry_after}s")
            time.sleep(retry_after)
            resp = self.session.get(url, timeout=30, stream=stream)
        resp.raise_for_status()
        return resp

    def get_bytes(self, url: str) -> tuple[bytes, dict[str, str]]:
        """Fetch URL and return (content_bytes, response_headers)."""
        resp = self.get(url)
        headers = {
            "etag": resp.headers.get("ETag", ""),
            "last-modified": resp.headers.get("Last-Modified", ""),
            "content-type": resp.headers.get("Content-Type", ""),
        }
        return resp.content, headers

    def close(self) -> None:
        self.session.close()


# ---------------------------------------------------------------------------
# Base adapter class
# ---------------------------------------------------------------------------

class BaseSiteAdapter(ABC):
    """Every government site adapter implements these hooks."""

    slug: str = ""
    agency: str = ""
    requires_browser: bool = False

    def __init__(self, config: dict | None = None, http: HTTPClient | None = None,
                 state: AdapterStateStore | None = None, archiver: SpacesArchiver | None = None,
                 browser_pool=None) -> None:
        self.config = config or {}
        self.http = http
        self.state = state
        self.archiver = archiver
        self.browser_pool = browser_pool

    # --- HOOK 1: Discovery ---
    @abstractmethod
    def discover(self, since: date | None = None, max_pages: int = 0) -> Iterable[DiscoveredItem]:
        """Yield pages/documents to process."""
        ...

    # --- HOOK 2: Fetch + Extract Downloads ---
    def fetch_and_extract(self, item: DiscoveredItem) -> Iterable[DocumentCandidate]:
        """Given a discovered item, fetch the page and extract downloadable documents."""
        try:
            resp = self.http.get(item.source_url)
            html = resp.text
        except Exception as e:
            log.warning(f"Failed to fetch {item.source_url}: {e}")
            return

        downloads = self.extract_downloads(html, item.source_url)

        # Also yield the HTML page itself as a candidate
        yield DocumentCandidate(
            url=item.source_url,
            source_page_url=item.source_url,
            title=item.title,
            published_at=item.published_at,
            doc_type=item.doc_type,
            content_type="text/html",
            language=item.language,
        )

        for dl in downloads:
            ct = guess_content_type(dl.url) if dl.url else ""
            yield DocumentCandidate(
                url=dl.url,
                source_page_url=item.source_url,
                title=item.title,
                published_at=item.published_at,
                doc_type=item.doc_type,
                content_type=ct,
                language=item.language,
            )

    # --- HOOK 3: Download Link Extraction ---
    def extract_downloads(self, html: str, base_url: str) -> list[DownloadLink]:
        """Parse HTML and return all downloadable document links."""
        return extract_document_links(html, base_url)

    # --- Optional hooks ---
    def should_skip(self, item: DiscoveredItem) -> bool:
        """Pre-fetch dedup check."""
        if not self.state:
            return False
        c_url = canonical_url(item.source_url)
        existing = self.state.get_by_url(c_url)
        return existing is not None

    def post_process(self, record: Record) -> Record:
        """Transform record after download (e.g., normalize metadata)."""
        return record
