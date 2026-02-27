from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from polisi_scraper.config import ScraperSettings, SettingsError


REQUIRED_ENV = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
    "DO_SPACES_KEY": "spaces-key",
    "DO_SPACES_SECRET": "spaces-secret",
    "DO_SPACES_BUCKET": "gov-docs",
    "DO_SPACES_REGION": "sgp1",
    "DO_SPACES_ENDPOINT": "https://sgp1.digitaloceanspaces.com",
}


def test_settings_validation() -> None:
    with pytest.raises(SettingsError) as err:
        ScraperSettings.from_env({})

    assert "Missing required environment variables" in str(err.value)

    settings = ScraperSettings.from_env(REQUIRED_ENV)
    assert settings.do_spaces_bucket == "gov-docs"
    assert settings.scraper_timeout_seconds == 30
