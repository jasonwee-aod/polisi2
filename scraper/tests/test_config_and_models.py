from __future__ import annotations

import pathlib
import sys
from datetime import date, datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from polisi_scraper.config import ScraperSettings, SettingsError
from polisi_scraper.models import DocumentRecord


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


def _sample_record() -> DocumentRecord:
    return DocumentRecord(
        source_url="https://www.mof.gov.my/policy/report.pdf",
        title="Fiscal Outlook 2026",
        agency="Ministry of Finance",
        file_type="pdf",
        sha256="a" * 64,
        filename="report.pdf",
        discovered_at=datetime(2026, 2, 28, 1, 0, tzinfo=timezone.utc),
        published_at=date(2026, 2, 20),
        metadata={"lang": "en"},
    )


def test_document_record_storage_path_contract() -> None:
    record = _sample_record()
    assert record.storage_path() == "gov-my/ministry-of-finance/2026-02/report.pdf"


def test_document_record_changed_filename_suffix() -> None:
    record = _sample_record()
    changed = record.build_filename(changed_on=date(2026, 2, 28))
    assert changed == "report_2026-02-28.pdf"


def test_document_row_mapping_has_required_fields() -> None:
    row = _sample_record().to_documents_row()
    assert set(row.keys()) == {
        "title",
        "source_url",
        "agency",
        "published_at",
        "file_type",
        "sha256",
        "storage_path",
        "metadata",
        "scraped_at",
    }
