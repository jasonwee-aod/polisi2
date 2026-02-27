from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from polisi_scraper.adapters.base import BaseSiteAdapter, DocumentCandidate
from polisi_scraper.config import ScraperSettings
from polisi_scraper.core.dedup import build_versioned_filename, compute_sha256
from polisi_scraper.core.state_store import CrawlStateStore
from polisi_scraper.runner import run_scrape


class FakeAdapter(BaseSiteAdapter):
    slug = "fake"
    agency = "Fake Agency"

    def __init__(self, candidates: list[DocumentCandidate]) -> None:
        self._candidates = candidates

    def iter_document_candidates(self, max_docs: int | None = None) -> list[DocumentCandidate]:
        if max_docs is None:
            return list(self._candidates)
        return list(self._candidates)[:max_docs]


@dataclass
class FakeUploader:
    uploaded: list[str]

    def upload_bytes(self, data: bytes, object_key: str, content_type: str | None = None) -> str:
        self.uploaded.append(object_key)
        return object_key


def _settings(db_path: str) -> ScraperSettings:
    return ScraperSettings.from_env(
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
            "DO_SPACES_KEY": "spaces-key",
            "DO_SPACES_SECRET": "spaces-secret",
            "DO_SPACES_BUCKET": "gov-docs",
            "DO_SPACES_REGION": "sgp1",
            "DO_SPACES_ENDPOINT": "https://sgp1.digitaloceanspaces.com",
            "SCRAPER_STATE_DB_PATH": db_path,
        }
    )


def test_sha256_dedup_and_resume(tmp_path: pathlib.Path) -> None:
    state = CrawlStateStore(str(tmp_path / "state.sqlite3"))
    payload = b"policy-document"
    digest = compute_sha256(payload)

    assert digest == compute_sha256(payload)

    source_url = "https://example.gov.my/doc.pdf"
    state.mark_processed("fake", source_url, digest, "gov-my/fake/2026-02/doc.pdf")

    assert state.is_already_processed("fake", source_url, digest)
    assert source_url in state.list_processed_urls("fake")
    assert build_versioned_filename("doc.pdf", date(2026, 2, 28)) == "doc_2026-02-28.pdf"


def test_runner_checkpoint_resume(tmp_path: pathlib.Path) -> None:
    db_path = str(tmp_path / "state.sqlite3")
    settings = _settings(db_path)

    candidates = [
        DocumentCandidate(
            source_page_url="https://example.gov.my/list",
            document_url="https://example.gov.my/one.pdf",
            title="One",
            file_type="pdf",
        ),
        DocumentCandidate(
            source_page_url="https://example.gov.my/list",
            document_url="https://example.gov.my/two.pdf",
            title="Two",
            file_type="pdf",
        ),
    ]

    payloads = {
        "https://example.gov.my/one.pdf": b"doc-one",
        "https://example.gov.my/two.pdf": b"doc-two",
    }

    uploader = FakeUploader(uploaded=[])
    adapter = FakeAdapter(candidates)

    summary_1 = run_scrape(
        [adapter],
        settings=settings,
        state_store=CrawlStateStore(db_path),
        uploader=uploader,
        fetcher=lambda url: payloads[url],
    )

    assert summary_1.adapters[0].processed == 2
    assert summary_1.adapters[0].skipped_unchanged == 0
    assert len(uploader.uploaded) == 2

    summary_2 = run_scrape(
        [adapter],
        settings=settings,
        state_store=CrawlStateStore(db_path),
        uploader=FakeUploader(uploaded=[]),
        fetcher=lambda url: payloads[url],
    )

    assert summary_2.adapters[0].processed == 0
    assert summary_2.adapters[0].skipped_unchanged == 2
    assert summary_2.adapters[0].checkpoint == "https://example.gov.my/two.pdf"


def test_adapter_contract_normalizes_record_shape() -> None:
    adapter = FakeAdapter(
        [
            DocumentCandidate(
                source_page_url="https://example.gov.my/list",
                document_url="https://example.gov.my/report-2026.pdf",
                title="Report",
                file_type="pdf",
            )
        ]
    )
    candidate = adapter.iter_document_candidates(max_docs=1)[0]
    record = adapter.to_record(candidate, sha256="b" * 64)

    assert record.agency == "Fake Agency"
    assert record.metadata["adapter"] == "fake"
    assert record.storage_path().startswith("gov-my/fake-agency/")
