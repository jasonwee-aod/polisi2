from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from polisi_scraper.adapters.base import (
    AdapterStateStore,
    BaseSiteAdapter,
    DocumentCandidate,
    sha256_of_bytes,
    spaces_object_path,
)


class FakeAdapter(BaseSiteAdapter):
    slug = "fake"
    agency = "Fake Agency"

    def discover(self, since=None, max_pages=0):
        return iter([])


def test_sha256_dedup_and_resume(tmp_path: pathlib.Path) -> None:
    state = AdapterStateStore(str(tmp_path / "state.sqlite3"))
    payload = b"policy-document"
    digest = sha256_of_bytes(payload)

    assert digest == sha256_of_bytes(payload)

    source_url = "https://example.gov.my/doc.pdf"
    state.upsert_record(
        canonical_url=source_url,
        source_url=source_url,
        sha256=digest,
        spaces_url="https://bucket.sgp1.digitaloceanspaces.com/gov-docs/fake/raw/2026/02/28/abc_doc.pdf",
        spaces_path="gov-docs/fake/raw/2026/02/28/abc_doc.pdf",
        fetched_at="2026-02-28T00:00:00Z",
    )

    assert state.get_by_url(source_url) is not None
    assert state.sha256_exists(digest)
    path = spaces_object_path("fake", digest, source_url)
    assert path.startswith("gov-docs/fake/raw/")


def test_runner_checkpoint_resume(tmp_path: pathlib.Path) -> None:
    """Test that AdapterStateStore correctly deduplicates by URL and SHA256."""
    db_path = str(tmp_path / "state.sqlite3")
    state = AdapterStateStore(db_path)

    # First insert
    state.upsert_record(
        canonical_url="https://example.gov.my/one.pdf",
        source_url="https://example.gov.my/list",
        sha256="a" * 64,
        spaces_url="https://bucket.sgp1.digitaloceanspaces.com/gov-docs/fake/one.pdf",
        spaces_path="gov-docs/fake/one.pdf",
        fetched_at="2026-02-28T00:00:00Z",
    )
    state.upsert_record(
        canonical_url="https://example.gov.my/two.pdf",
        source_url="https://example.gov.my/list",
        sha256="b" * 64,
        spaces_url="https://bucket.sgp1.digitaloceanspaces.com/gov-docs/fake/two.pdf",
        spaces_path="gov-docs/fake/two.pdf",
        fetched_at="2026-02-28T00:00:00Z",
    )

    # Both should be found
    assert state.get_by_url("https://example.gov.my/one.pdf") is not None
    assert state.get_by_url("https://example.gov.my/two.pdf") is not None
    assert state.sha256_exists("a" * 64)
    assert state.sha256_exists("b" * 64)

    # Duplicate sha256 should be detected
    existing_url = state.get_spaces_url_by_sha256("a" * 64)
    assert existing_url is not None


def test_adapter_contract_normalizes_record_shape() -> None:
    adapter = FakeAdapter()
    assert adapter.slug == "fake"
    assert adapter.agency == "Fake Agency"
    assert hasattr(adapter, "discover")
    assert hasattr(adapter, "fetch_and_extract")

    candidate = DocumentCandidate(
        url="https://example.gov.my/report-2026.pdf",
        source_page_url="https://example.gov.my/list",
        title="Report",
        content_type="application/pdf",
    )
    assert candidate.url.startswith("https://")
    assert candidate.title == "Report"
