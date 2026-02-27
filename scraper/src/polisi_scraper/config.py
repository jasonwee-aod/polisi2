"""Environment-backed settings for the scraper runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable


class SettingsError(ValueError):
    """Raised when required runtime settings are missing or invalid."""


_REQUIRED_ENV_VARS: tuple[str, ...] = (
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "DO_SPACES_KEY",
    "DO_SPACES_SECRET",
    "DO_SPACES_BUCKET",
    "DO_SPACES_REGION",
    "DO_SPACES_ENDPOINT",
)


@dataclass(frozen=True)
class ScraperSettings:
    """Centralized runtime settings loaded once at startup."""

    supabase_url: str
    supabase_service_role_key: str
    do_spaces_key: str
    do_spaces_secret: str
    do_spaces_bucket: str
    do_spaces_region: str
    do_spaces_endpoint: str
    scraper_user_agent: str = "PolisiScraper/1.0 (+https://polisigpt.local)"
    scraper_timeout_seconds: int = 30
    scraper_max_retries: int = 3
    scraper_retry_backoff_seconds: float = 1.5
    scraper_state_db_path: str = ".cache/scraper_state.sqlite3"
    scraper_temp_dir: str = ".cache/tmp"
    scraper_politeness_delay_seconds: float = 0.5

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "ScraperSettings":
        source = env if env is not None else dict(os.environ)
        missing = _missing_required_vars(source, _REQUIRED_ENV_VARS)
        if missing:
            joined = ", ".join(missing)
            raise SettingsError(f"Missing required environment variables: {joined}")

        return cls(
            supabase_url=source["SUPABASE_URL"],
            supabase_service_role_key=source["SUPABASE_SERVICE_ROLE_KEY"],
            do_spaces_key=source["DO_SPACES_KEY"],
            do_spaces_secret=source["DO_SPACES_SECRET"],
            do_spaces_bucket=source["DO_SPACES_BUCKET"],
            do_spaces_region=source["DO_SPACES_REGION"],
            do_spaces_endpoint=source["DO_SPACES_ENDPOINT"],
            scraper_user_agent=source.get(
                "SCRAPER_USER_AGENT", "PolisiScraper/1.0 (+https://polisigpt.local)"
            ),
            scraper_timeout_seconds=_coerce_int(source.get("SCRAPER_TIMEOUT_SECONDS"), 30),
            scraper_max_retries=_coerce_int(source.get("SCRAPER_MAX_RETRIES"), 3),
            scraper_retry_backoff_seconds=_coerce_float(
                source.get("SCRAPER_RETRY_BACKOFF_SECONDS"), 1.5
            ),
            scraper_state_db_path=source.get("SCRAPER_STATE_DB_PATH", ".cache/scraper_state.sqlite3"),
            scraper_temp_dir=source.get("SCRAPER_TEMP_DIR", ".cache/tmp"),
            scraper_politeness_delay_seconds=_coerce_float(
                source.get("SCRAPER_POLITENESS_DELAY_SECONDS"), 0.5
            ),
        )



def _missing_required_vars(env: dict[str, str], keys: Iterable[str]) -> list[str]:
    return [key for key in keys if not env.get(key)]



def _coerce_int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise SettingsError(f"Expected integer value, got: {value!r}") from exc



def _coerce_float(value: str | None, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise SettingsError(f"Expected float value, got: {value!r}") from exc
