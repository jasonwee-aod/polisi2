"""Environment-backed settings for the Polisi API."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_env: str = Field(default="development", validation_alias=AliasChoices("API_ENV"))
    api_title: str = "Polisi API"
    api_version: str = "0.1.0"
    api_host: str = Field(default="0.0.0.0", validation_alias=AliasChoices("API_HOST"))
    api_port: int = Field(default=8000, validation_alias=AliasChoices("API_PORT"))
    api_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        validation_alias=AliasChoices("API_ALLOWED_ORIGINS"),
    )

    supabase_url: str = Field(validation_alias=AliasChoices("SUPABASE_URL"))
    supabase_db_url: str = Field(validation_alias=AliasChoices("SUPABASE_DB_URL"))
    supabase_jwt_secret: str | None = Field(
        default=None, validation_alias=AliasChoices("SUPABASE_JWT_SECRET")
    )
    supabase_jwks_json: str | None = Field(
        default=None, validation_alias=AliasChoices("SUPABASE_JWKS_JSON")
    )

    anthropic_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY")
    )
    anthropic_model: str = Field(
        default="claude-3-5-sonnet-latest",
        validation_alias=AliasChoices("ANTHROPIC_MODEL"),
    )
    openai_api_key: str | None = Field(default=None, validation_alias=AliasChoices("OPENAI_API_KEY"))

    datagov_api_token: str | None = Field(
        default=None, validation_alias=AliasChoices("DATAGOV_API_TOKEN")
    )

    retrieval_limit: int = Field(default=5, validation_alias=AliasChoices("RETRIEVAL_LIMIT"))
    retrieval_min_similarity: float = Field(
        default=0.45, validation_alias=AliasChoices("RETRIEVAL_MIN_SIMILARITY")
    )
    retrieval_weak_similarity: float = Field(
        default=0.65, validation_alias=AliasChoices("RETRIEVAL_WEAK_SIMILARITY")
    )
    retrieval_rrf_k: int = Field(
        default=60, validation_alias=AliasChoices("RETRIEVAL_RRF_K")
    )
    retrieval_fts_min_similarity: float = Field(
        default=0.50, validation_alias=AliasChoices("RETRIEVAL_FTS_MIN_SIMILARITY")
    )
    retrieval_similarity_dropoff: float = Field(
        default=0.60, validation_alias=AliasChoices("RETRIEVAL_SIMILARITY_DROPOFF")
    )

    # Cross-encoder reranking
    enable_reranking: bool = Field(
        default=True, validation_alias=AliasChoices("ENABLE_RERANKING")
    )
    reranker_model: str = Field(
        default="claude-3-5-haiku-latest",
        validation_alias=AliasChoices("RERANKER_MODEL"),
    )
    reranker_top_n: int = Field(
        default=5, validation_alias=AliasChoices("RERANKER_TOP_N")
    )
    retrieval_prefetch_limit: int = Field(
        default=20, validation_alias=AliasChoices("RETRIEVAL_PREFETCH_LIMIT")
    )

    # Query expansion
    enable_query_expansion: bool = Field(
        default=True, validation_alias=AliasChoices("ENABLE_QUERY_EXPANSION")
    )
    query_expansion_model: str = Field(
        default="claude-3-5-haiku-latest",
        validation_alias=AliasChoices("QUERY_EXPANSION_MODEL"),
    )

    # Conversation-aware retrieval
    conversation_context_turns: int = Field(
        default=3, validation_alias=AliasChoices("CONVERSATION_CONTEXT_TURNS")
    )

    rate_limit_daily_requests: int = Field(
        default=25, validation_alias=AliasChoices("RATE_LIMIT_DAILY_REQUESTS")
    )
    rate_limit_daily_tokens: int = Field(
        default=15000, validation_alias=AliasChoices("RATE_LIMIT_DAILY_TOKENS")
    )

    @field_validator("api_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> list[str]:
        if value is None:
            return ["http://localhost:3000"]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        raise TypeError("API_ALLOWED_ORIGINS must be a comma-separated string or list")

    @field_validator("supabase_jwt_secret", "supabase_jwks_json", mode="before")
    @classmethod
    def _empty_to_none(cls, value: Any) -> str | None:
        if value in ("", None):
            return None
        return str(value)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        if env is None:
            return cls()
        return cls.model_validate(env)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
