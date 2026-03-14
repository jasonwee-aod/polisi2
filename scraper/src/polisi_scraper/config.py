"""Environment-backed settings for the scraper and indexer runtimes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

# Auto-load .env: scraper/.env (local dev) or /opt/polisigpt/.env (Droplet)
for _candidate in [
    Path(__file__).resolve().parents[3] / ".env",
    Path("/opt/polisigpt/.env"),
]:
    if _candidate.exists():
        load_dotenv(_candidate)
        break


class SettingsError(ValueError):
    """Raised when required runtime settings are missing or invalid."""


_SCRAPER_REQUIRED_ENV_VARS: tuple[str, ...] = (
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "DO_SPACES_KEY",
    "DO_SPACES_SECRET",
    "DO_SPACES_BUCKET",
    "DO_SPACES_REGION",
    "DO_SPACES_ENDPOINT",
)

_INDEXER_REQUIRED_ENV_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "SUPABASE_DB_URL",
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
    openai_api_key: str | None = None
    supabase_db_url: str | None = None
    scraper_user_agent: str = "PolisiScraper/1.0 (+https://polisigpt.local)"
    scraper_timeout_seconds: int = 30
    scraper_max_retries: int = 3
    scraper_retry_backoff_seconds: float = 1.5
    scraper_state_db_path: str = ".cache/scraper_state.sqlite3"
    scraper_temp_dir: str = ".cache/tmp"
    scraper_politeness_delay_seconds: float = 0.5
    indexer_spaces_prefix: str = "gov-docs/"
    indexer_batch_size: int = 16
    indexer_max_items_per_run: int = 0
    indexer_chunk_size: int = 1400
    indexer_chunk_overlap: int = 250
    indexer_similarity_limit: int = 5

    @classmethod
    def from_env(
        cls,
        env: dict[str, str] | None = None,
        *,
        require_indexer: bool = False,
    ) -> "ScraperSettings":
        source = env if env is not None else dict(os.environ)
        required = list(_SCRAPER_REQUIRED_ENV_VARS)
        if require_indexer:
            required.extend(_INDEXER_REQUIRED_ENV_VARS)
        missing = _missing_required_vars(source, required)
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
            openai_api_key=source.get("OPENAI_API_KEY") or None,
            supabase_db_url=source.get("SUPABASE_DB_URL") or None,
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
            indexer_spaces_prefix=source.get("INDEXER_SPACES_PREFIX", "gov-docs/"),
            indexer_batch_size=_coerce_int(source.get("INDEXER_BATCH_SIZE"), 16),
            indexer_max_items_per_run=_coerce_int(source.get("INDEXER_MAX_ITEMS_PER_RUN"), 0),
            indexer_chunk_size=_coerce_int(source.get("INDEXER_CHUNK_SIZE"), 1400),
            indexer_chunk_overlap=_coerce_int(source.get("INDEXER_CHUNK_OVERLAP"), 250),
            indexer_similarity_limit=_coerce_int(source.get("INDEXER_SIMILARITY_LIMIT"), 5),
        )

    def require_indexer(self) -> "ScraperSettings":
        missing: list[str] = []
        if not self.openai_api_key:
            missing.append("OPENAI_API_KEY")
        if not self.supabase_db_url:
            missing.append("SUPABASE_DB_URL")
        if missing:
            joined = ", ".join(missing)
            raise SettingsError(f"Missing required environment variables: {joined}")
        return self



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
