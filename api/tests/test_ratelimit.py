"""Tests for the daily rate limiting system."""

from __future__ import annotations

from polisi_api.chat.skills import SKILL_BY_ID
from polisi_api.config import Settings
from polisi_api.ratelimit import UsageSnapshot


def _build_settings(**overrides: str) -> Settings:
    base = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_DB_URL": "postgresql://postgres:postgres@localhost:5432/postgres",
        "SUPABASE_JWT_SECRET": "test-secret",
        "ANTHROPIC_API_KEY": "test-key",
        "OPENAI_API_KEY": "test-openai-key",
        "RATE_LIMIT_DAILY_REQUESTS": "25",
        "RATE_LIMIT_DAILY_TOKENS": "15000",
    }
    base.update(overrides)
    return Settings.from_env(base)


def test_rate_limit_config_defaults() -> None:
    settings = _build_settings()
    assert settings.rate_limit_daily_requests == 25
    assert settings.rate_limit_daily_tokens == 15000


def test_rate_limit_config_override() -> None:
    settings = _build_settings(
        RATE_LIMIT_DAILY_REQUESTS="50",
        RATE_LIMIT_DAILY_TOKENS="30000",
    )
    assert settings.rate_limit_daily_requests == 50
    assert settings.rate_limit_daily_tokens == 30000


def test_usage_snapshot_dataclass() -> None:
    snap = UsageSnapshot(request_count=5, tokens_budgeted=6000)
    assert snap.request_count == 5
    assert snap.tokens_budgeted == 6000


def test_skill_token_costs_within_budget() -> None:
    """Verify that 4 skill uses fit within the daily token budget."""
    settings = _build_settings()
    max_skill_tokens = max(s.max_tokens for s in SKILL_BY_ID.values())
    # 4 uses of the most expensive skill should be under the daily limit
    assert max_skill_tokens * 4 <= settings.rate_limit_daily_tokens


def test_standard_chat_count_within_budget() -> None:
    """Verify that ~12 standard chats fit within the daily token budget."""
    settings = _build_settings()
    standard_max_tokens = 1200
    assert standard_max_tokens * 12 <= settings.rate_limit_daily_tokens


def test_usage_api_route_returns_structure() -> None:
    import os
    os.environ["SUPABASE_URL"] = "https://example.supabase.co"
    os.environ["SUPABASE_DB_URL"] = "postgresql://postgres:postgres@localhost:5432/postgres"
    from fastapi.testclient import TestClient
    from polisi_api.auth import AuthenticatedUser, get_current_user
    from polisi_api.main import create_app
    from polisi_api.ratelimit import UsageSnapshot, get_usage

    settings = _build_settings()
    app = create_app(settings)
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id="test-user", email="test@example.com", role="authenticated", claims={}
    )
    app.dependency_overrides[get_usage] = lambda: UsageSnapshot(request_count=3, tokens_budgeted=4200)
    client = TestClient(app)

    response = client.get("/api/usage")
    assert response.status_code == 200
    data = response.json()

    assert data["tier"] == "free"
    assert data["requests"]["used"] == 3
    assert data["requests"]["limit"] == 25
    assert data["requests"]["remaining"] == 22
    assert data["tokens"]["used"] == 4200
    assert data["tokens"]["limit"] == 15000
    assert data["tokens"]["remaining"] == 10800
