"""Shared HTTP client with retry and timeout behavior."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HttpClientError(RuntimeError):
    """Raised when retries are exhausted."""


@dataclass(frozen=True)
class HttpClientConfig:
    timeout_seconds: int = 30
    max_retries: int = 3
    retry_backoff_seconds: float = 1.5
    user_agent: str = "PolisiScraper/1.0 (+https://polisigpt.local)"


class HttpClient:
    def __init__(self, config: HttpClientConfig | None = None) -> None:
        self._config = config or HttpClientConfig()

    @property
    def config(self) -> HttpClientConfig:
        return self._config

    def get_bytes(self, url: str, headers: Mapping[str, str] | None = None) -> bytes:
        merged_headers = {"User-Agent": self._config.user_agent}
        if headers:
            merged_headers.update(dict(headers))

        attempts = self._config.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            request = Request(url, headers=merged_headers)
            try:
                with urlopen(request, timeout=self._config.timeout_seconds) as resp:
                    return resp.read()
            except (HTTPError, URLError, TimeoutError) as exc:
                last_error = exc
                if attempt == attempts:
                    break
                delay = self._config.retry_backoff_seconds * attempt
                time.sleep(delay)

        raise HttpClientError(f"Failed to fetch {url!r} after {attempts} attempts") from last_error
