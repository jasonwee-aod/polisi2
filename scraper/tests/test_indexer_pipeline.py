from __future__ import annotations

import hashlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from polisi_scraper.indexer.manifest import PendingIndexItem, SpacesCorpusManifest
from polisi_scraper.indexer.pipeline import IndexingPipeline
from polisi_scraper.indexer.store import DocumentsStore


class FakeManifest(SpacesCorpusManifest):
    def __init__(self, items: list[PendingIndexItem]) -> None:
        self._items = items

    def pending_items(self, fingerprints: DocumentsStore) -> list[PendingIndexItem]:
        return [item for item in self._items if not fingerprints.has_fingerprint(item.storage_path, item.version_token)]

    def list_objects(self) -> list[object]:
        return list(self._items)


class FakeFetcher:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads

    def get_bytes(self, storage_path: str) -> bytes:
        return self.payloads[storage_path]


class FakeEmbeddings:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), float(index + 1)] for index, text in enumerate(texts)]


def _pending_item(file_type: str, storage_path: str, *, title: str) -> PendingIndexItem:
    return PendingIndexItem(
        storage_path=storage_path,
        agency="ministry-of-finance",
        year_month="2026-02",
        filename=pathlib.Path(storage_path).name,
        file_type=file_type,
        version_token="version-1",
        title=title,
        source_url="https://www.mof.gov.my/doc",
        metadata={},
    )


def test_documents_schema_supports_multiple_chunks_per_version() -> None:
    sql = pathlib.Path("supabase/migrations/20260228_02_phase2_documents_chunks.sql").read_text()

    assert "documents_storage_version_chunk_unique" in sql
    assert "version_token text" in sql
    assert "create or replace function public.match_documents" in sql


def test_indexing_pipeline_persists_chunks_and_fingerprints() -> None:
    item = _pending_item("html", "gov-my/ministry-of-finance/2026-02/budget.html", title="Budget")
    payload = b"<html><body><h1>Subsidy</h1><p>Fuel subsidy continues for 2026 households.</p></body></html>"
    store = DocumentsStore()
    pipeline = IndexingPipeline(
        FakeManifest([item]),
        FakeFetcher({item.storage_path: payload}),
        FakeEmbeddings(),
        store,
    )

    result = pipeline.run()

    assert result.processed_documents == 1
    assert result.persisted_chunks == 1
    assert store.has_fingerprint(item.storage_path, item.version_token)
    assert store.match_documents([50.0, 1.0], limit=1)[0].title == "Budget"
    assert store._records[0].sha256 == hashlib.sha256(payload).hexdigest()
