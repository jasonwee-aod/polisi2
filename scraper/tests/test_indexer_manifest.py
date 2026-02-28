from __future__ import annotations

from datetime import datetime, timezone
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from polisi_scraper.config import ScraperSettings, SettingsError
from polisi_scraper.indexer.manifest import SpacesCorpusManifest
from polisi_scraper.indexer.state import InMemoryFingerprintStore


BASE_ENV = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
    "DO_SPACES_KEY": "spaces-key",
    "DO_SPACES_SECRET": "spaces-secret",
    "DO_SPACES_BUCKET": "gov-docs",
    "DO_SPACES_REGION": "sgp1",
    "DO_SPACES_ENDPOINT": "https://sgp1.digitaloceanspaces.com",
}


class FakeSpacesClient:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self._pages = pages
        self.calls = 0

    def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
        page = self._pages[self.calls]
        self.calls += 1
        return page


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


def test_spaces_manifest_normalizes_storage_objects() -> None:
    settings = ScraperSettings.from_env(BASE_ENV)
    client = FakeSpacesClient(
        [
            {
                "Contents": [
                    {
                        "Key": "gov-my/ministry-of-finance/2026-02/budget-2026.pdf",
                        "ETag": '"etag-b"',
                        "Size": 2048,
                        "LastModified": datetime(2026, 2, 28, 4, 0, tzinfo=timezone.utc),
                        "Metadata": {"source_url": "https://www.mof.gov.my/budget-2026.pdf"},
                    },
                    {
                        "Key": "gov-my/ministry-of-finance/2026-01/budget-2025.html",
                        "ETag": '"etag-a"',
                        "Size": 1024,
                        "LastModified": datetime(2026, 2, 27, 4, 0, tzinfo=timezone.utc),
                    },
                ],
                "IsTruncated": False,
            }
        ]
    )

    manifest = SpacesCorpusManifest(settings, client=client)
    objects = manifest.list_objects()

    assert [obj.storage_path for obj in objects] == [
        "gov-my/ministry-of-finance/2026-01/budget-2025.html",
        "gov-my/ministry-of-finance/2026-02/budget-2026.pdf",
    ]
    assert objects[0].file_type == "html"
    assert objects[1].version_token == "etag-b"
    assert objects[1].metadata["source_url"] == "https://www.mof.gov.my/budget-2026.pdf"


def test_pending_items_skip_existing_sha() -> None:
    settings = ScraperSettings.from_env(BASE_ENV)
    client = FakeSpacesClient(
        [
            {
                "Contents": [
                    {
                        "Key": "gov-my/ministry-of-health/2026-02/guidelines.docx",
                        "ETag": '"etag-guidelines"',
                        "Metadata": {"sha256": "a" * 64},
                    },
                    {
                        "Key": "gov-my/ministry-of-health/2026-02/report.xlsx",
                        "ETag": '"etag-report"',
                    },
                ],
                "IsTruncated": False,
            }
        ]
    )
    store = InMemoryFingerprintStore()
    store.mark_indexed(
        "gov-my/ministry-of-health/2026-02/guidelines.docx",
        "a" * 64,
        document_count=5,
    )

    manifest = SpacesCorpusManifest(settings, client=client)
    pending = manifest.pending_items(store)

    assert len(pending) == 1
    assert pending[0].storage_path == "gov-my/ministry-of-health/2026-02/report.xlsx"
    assert pending[0].file_type == "xlsx"
