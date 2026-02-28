from __future__ import annotations

import os

import jwt

from polisi_api.config import Settings


def test_settings_and_health_contract() -> None:
    from fastapi.testclient import TestClient

    os.environ["SUPABASE_URL"] = "https://example.supabase.co"
    os.environ["SUPABASE_DB_URL"] = "postgresql://postgres:postgres@localhost:5432/postgres"
    from polisi_api.main import create_app

    settings = Settings.from_env(
        {
            "API_ENV": "test",
            "API_ALLOWED_ORIGINS": "http://localhost:3000,https://polisi.local",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_DB_URL": "postgresql://postgres:postgres@localhost:5432/postgres",
            "ANTHROPIC_API_KEY": "test-key",
        }
    )

    assert settings.api_allowed_origins == [
        "http://localhost:3000",
        "https://polisi.local",
    ]
    assert settings.retrieval_limit == 5

    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "environment": "test",
        "service": "polisi-api",
    }


def test_current_user_dependency_rejects_missing_or_invalid_tokens() -> None:
    from fastapi.testclient import TestClient

    os.environ["SUPABASE_URL"] = "https://example.supabase.co"
    os.environ["SUPABASE_DB_URL"] = "postgresql://postgres:postgres@localhost:5432/postgres"
    from polisi_api.main import create_app

    settings = Settings.from_env(
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_DB_URL": "postgresql://postgres:postgres@localhost:5432/postgres",
            "SUPABASE_JWT_SECRET": "test-secret",
        }
    )
    client = TestClient(create_app(settings))

    missing = client.post("/api/chat")
    invalid = client.post("/api/chat", headers={"Authorization": "Bearer not-a-token"})
    valid_token = jwt.encode(
        {
            "sub": "2f16f1d4-6eaf-4a76-89c7-93a09c639e6f",
            "email": "citizen@example.com",
            "role": "authenticated",
            "aud": "authenticated",
            "exp": 4102444800,
        },
        "test-secret",
        algorithm="HS256",
    )
    valid = client.post("/api/chat", headers={"Authorization": f"Bearer {valid_token}"})

    assert missing.status_code == 401
    assert missing.json()["detail"] == "Missing bearer token"
    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "Invalid bearer token"
    assert valid.status_code == 200
    assert valid.json() == {
        "status": "not-implemented",
        "user_id": "2f16f1d4-6eaf-4a76-89c7-93a09c639e6f",
    }
