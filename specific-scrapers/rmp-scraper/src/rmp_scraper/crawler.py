"""
HTTP client with retry, rate-limiting, and host allowlist enforcement.
"""
from __future__ import annotations

import logging
import time
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; rmp-scraper/1.0; "
    "Python-Requests; +mailto:operator@example.com)"
)
REQUEST_TIMEOUT = 30  # seconds

_DEFAULT_ALLOWED_HOSTS: frozenset[str] = frozenset({"www.rmp.gov.my"})


# ── URL helpers ────────────────────────────────────────────────────────────────


def canonical_url(url: str) -> str:
    """
    Normalize a URL for deduplication:
      - Force HTTPS
      - Lowercase scheme and host
      - Strip fragment
      - Preserve path and query string as-is
    """
    parsed = urlparse(url)
    return urlunparse(
        (
            "https",
            parsed.netloc.lower(),
            parsed.path,
            "",           # params
            parsed.query,
            "",           # fragment stripped
        )
    )


def make_absolute(href: str, base_url: str) -> str:
    """Resolve a potentially relative href against a base URL."""
    return urljoin(base_url, href)


def is_allowed_host(url: str, allowed_hosts: Optional[frozenset] = None) -> bool:
    """Return True if the URL's host is in the allowlist."""
    if allowed_hosts is None:
        allowed_hosts = _DEFAULT_ALLOWED_HOSTS
    host = urlparse(url).netloc.lower()
    return host in allowed_hosts


# ── HTTP client ────────────────────────────────────────────────────────────────


class HTTPClient:
    """
    Thin requests.Session wrapper with:
      - Polite per-request delay
      - Automatic retry on transient errors (429, 5xx, timeouts)
      - Host allowlist check
    """

    def __init__(
        self,
        allowed_hosts: Optional[frozenset] = None,
        request_delay: float = 1.5,
    ) -> None:
        self.allowed_hosts = allowed_hosts or _DEFAULT_ALLOWED_HOSTS
        self.request_delay = request_delay
        self._last_request_time: float = 0.0

        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        )
        self.session.headers["Accept-Language"] = "ms,en-US;q=0.9,en;q=0.8"

    # ── internal ──────────────────────────────────────────────────────────────

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self._last_request_time = time.monotonic()

    def _handle_429(self, url: str, resp: requests.Response) -> requests.Response:
        retry_after = int(resp.headers.get("Retry-After", 60))
        log.warning(
            {
                "event": "rate_limited",
                "url": url,
                "retry_after": retry_after,
                "category": "network",
            }
        )
        time.sleep(retry_after)
        return self.session.get(url, timeout=REQUEST_TIMEOUT)

    # ── public ────────────────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type((requests.Timeout, requests.ConnectionError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
    def get(self, url: str, stream: bool = False) -> requests.Response:
        """
        Fetch a URL. Raises ValueError for disallowed hosts.
        Retries on Timeout / ConnectionError (up to 3 attempts).
        Handles 429 with a backoff sleep.
        """
        if not is_allowed_host(url, self.allowed_hosts):
            raise ValueError(
                f"policy: host not in allowlist: {urlparse(url).netloc!r}"
            )

        self._throttle()
        log.debug({"event": "fetch", "url": url})

        resp = self.session.get(url, timeout=REQUEST_TIMEOUT, stream=stream)

        if resp.status_code == 429:
            resp = self._handle_429(url, resp)

        resp.raise_for_status()
        return resp

    def close(self) -> None:
        self.session.close()
