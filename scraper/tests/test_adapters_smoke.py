from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from polisi_scraper.adapters import get_adapter_registry
from polisi_scraper.models import SUPPORTED_FILE_TYPES


def test_adapter_registry_has_five_sites() -> None:
    registry = get_adapter_registry()
    assert set(registry.keys()) == {"mof", "moe", "jpa", "moh", "dosm"}


def test_adapter_smoke_matrix() -> None:
    registry = get_adapter_registry()

    for slug, factory in registry.items():
        adapter = factory()
        candidates = adapter.iter_document_candidates(max_docs=1)

        assert candidates, f"{slug} should return at least one candidate"
        candidate = candidates[0]

        assert candidate.document_url.startswith("https://")
        assert candidate.file_type in SUPPORTED_FILE_TYPES
        assert candidate.title

        record = adapter.to_record(candidate, sha256="a" * 64)
        assert record.storage_path().startswith("gov-my/")
        assert record.metadata["adapter"] == slug
        assert record.metadata["source_page_url"] == candidate.source_page_url
