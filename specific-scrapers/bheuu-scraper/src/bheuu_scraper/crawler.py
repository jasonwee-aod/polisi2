"""
HTTP client and URL utilities for the BHEUU scraper.

bheuu.gov.my uses a Nuxt.js frontend backed by Strapi v3 at
strapi.bheuu.gov.my.  All content is fetched directly from the Strapi
REST API as JSON — no HTML parsing is required.

Host allowlist:
    www.bheuu.gov.my   – Nuxt frontend (not fetched, just tracked as source)
    strapi.bheuu.gov.my – Strapi API + file uploads
"""
from __future__ import annotations

import logging
import time
from typing import Optional
from urllib.parse import urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

_DOC_EXTENSIONS = frozenset(
    [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip"]
)


# ── URL utilities ─────────────────────────────────────────────────────────────


def canonical_url(url: str) -> str:
    """
    Normalize a URL to a canonical form for deduplication.

    Rules:
      - Force HTTPS.
      - Lowercase the host.
      - Strip fragment (#…).
      - Preserve path, query string, and port.
    """
    parsed = urlparse(url.strip())
    normalized = parsed._replace(
        scheme="https",
        netloc=parsed.netloc.lower(),
        fragment="",
    )
    return urlunparse(normalized)


def is_allowed_host(url: str, allowed_hosts: frozenset[str]) -> bool:
    """Return True if the URL's host (lowercased) is in the allowlist."""
    host = urlparse(url).netloc.lower()
    # strip port if present
    host = host.split(":")[0]
    return host in allowed_hosts


def make_absolute(href: str, base_url: str) -> str:
    """
    Resolve *href* relative to *base_url*.

    If *href* is already an absolute URL it is returned unchanged.
    """
    if href.startswith("http://") or href.startswith("https://"):
        return href
    parsed_base = urlparse(base_url)
    if href.startswith("/"):
        return f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
    # relative path – join with base path directory
    base_path = parsed_base.path.rstrip("/")
    return f"{parsed_base.scheme}://{parsed_base.netloc}{base_path}/{href}"


def resolve_file_url(raw_url: str, strapi_base: str) -> str:
    """
    Resolve a Strapi file URL to a full absolute HTTPS URL.

    Strapi v3 stores file URLs in two forms:
      - Absolute: "https://strapi.bheuu.gov.my/uploads/file.pdf"
      - Relative: "/uploads/file.pdf"

    Both are resolved against *strapi_base*.
    """
    if not raw_url:
        return ""
    return make_absolute(raw_url, strapi_base)


def is_document_url(url: str) -> bool:
    """Return True if the URL path ends with a known document extension."""
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in _DOC_EXTENSIONS)


def get_nested(data: dict, dotted_key: str) -> Optional[str]:
    """
    Traverse *data* using a dot-separated key path and return the leaf value.

    Example: get_nested(record, "fileName.url") accesses record["fileName"]["url"].
    Returns None if any key is missing or the value is not a string.
    """
    keys = dotted_key.split(".")
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current if isinstance(current, str) else None


# ── HTTP client ───────────────────────────────────────────────────────────────


class HTTPClient:
    """
    Thin wrapper around requests.Session with retry/backoff and polite delay.

    Used for both Strapi API calls (JSON) and binary file downloads.
    """

    def __init__(
        self,
        allowed_hosts: frozenset[str] = frozenset(),
        request_delay: float = 1.0,
        timeout: float = 30.0,
    ) -> None:
        self.allowed_hosts = allowed_hosts
        self.request_delay = request_delay
        self.timeout = timeout
        self._last_request_time: float = 0.0

        retry = Retry(
            total=4,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session = requests.Session()
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; BHEUUScraper/1.0; "
                    "+https://www.bheuu.gov.my)"
                ),
                "Accept": "application/json, */*",
            }
        )

    def _polite_wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self._last_request_time = time.monotonic()

    def get(
        self,
        url: str,
        params: Optional[dict] = None,
        stream: bool = False,
    ) -> requests.Response:
        """
        Perform a GET request with polite delay and retries.

        Raises requests.HTTPError for 4xx/5xx after retries are exhausted.
        """
        self._polite_wait()
        log.debug({"event": "http_get", "url": url, "params": params})
        resp = self._session.get(
            url,
            params=params,
            timeout=self.timeout,
            stream=stream,
            allow_redirects=True,
        )
        resp.raise_for_status()
        return resp

    def get_json(self, url: str, params: Optional[dict] = None) -> object:
        """Fetch JSON from a URL and return the parsed object."""
        resp = self.get(url, params=params)
        return resp.json()

    def close(self) -> None:
        self._session.close()
