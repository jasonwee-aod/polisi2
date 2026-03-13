from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib.robotparser import RobotFileParser

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from moe_scraper.utils import get_http_timeout, get_rate_limit_rps, polite_sleep


@dataclass(slots=True)
class HttpResult:
    url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    content_type: str


class HttpClient:
    def __init__(
        self,
        user_agent: str,
        crawl_run_id: str,
        timeout: int | None = None,
        rps: float | None = None,
        warmup_url: str | None = None,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.timeout = timeout or get_http_timeout()
        self.rps = rps or get_rate_limit_rps()
        self.crawl_run_id = crawl_run_id
        self.last_request_monotonic = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        if warmup_url:
            try:
                self.session.get(warmup_url, timeout=self.timeout, allow_redirects=True)
            except Exception:  # noqa: BLE001
                pass

    def close(self) -> None:
        self.session.close()

    @retry(
        retry=retry_if_exception_type((requests.RequestException, TimeoutError)),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def fetch(self, url: str) -> HttpResult:
        self.last_request_monotonic = polite_sleep(self.last_request_monotonic, self.rps)
        response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        if response.status_code in {429, 500, 502, 503, 504}:
            raise TimeoutError(f"retryable status code: {response.status_code}")

        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        self.logger.info(
            json.dumps(
                {
                    "crawl_run_id": self.crawl_run_id,
                    "url": response.url,
                    "status": "fetched",
                    "http_status": response.status_code,
                    "content_type": content_type,
                }
            )
        )
        return HttpResult(
            url=response.url,
            status_code=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            content=response.content,
            content_type=content_type,
        )


class RobotsPolicy:
    def __init__(self, base_url: str, user_agent: str) -> None:
        self.parser = RobotFileParser()
        robots_url = base_url.rstrip("/") + "/robots.txt"
        self.parser.set_url(robots_url)
        self.parser.read()
        self.user_agent = user_agent

    def can_fetch(self, url: str) -> bool:
        return self.parser.can_fetch(self.user_agent, url)
