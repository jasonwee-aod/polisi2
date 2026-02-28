from __future__ import annotations

import os

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
