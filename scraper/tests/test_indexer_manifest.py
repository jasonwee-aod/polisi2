from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from polisi_scraper.config import ScraperSettings, SettingsError


BASE_ENV = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
    "DO_SPACES_KEY": "spaces-key",
    "DO_SPACES_SECRET": "spaces-secret",
    "DO_SPACES_BUCKET": "gov-docs",
    "DO_SPACES_REGION": "sgp1",
    "DO_SPACES_ENDPOINT": "https://sgp1.digitaloceanspaces.com",
}


def test_indexer_settings_validation() -> None:
    with pytest.raises(SettingsError) as err:
        ScraperSettings.from_env(BASE_ENV, require_indexer=True)

    assert "OPENAI_API_KEY" in str(err.value)
    assert "SUPABASE_DB_URL" in str(err.value)

    settings = ScraperSettings.from_env(
        {
            **BASE_ENV,
            "OPENAI_API_KEY": "openai-key",
            "SUPABASE_DB_URL": "postgresql://postgres:password@db.example.supabase.co:5432/postgres",
            "INDEXER_BATCH_SIZE": "24",
            "INDEXER_CHUNK_OVERLAP": "300",
        },
        require_indexer=True,
    )
    settings.require_indexer()

    assert settings.indexer_batch_size == 24
    assert settings.indexer_chunk_overlap == 300
    assert settings.openai_api_key == "openai-key"
