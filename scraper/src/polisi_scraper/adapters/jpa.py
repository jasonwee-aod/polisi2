from __future__ import annotations

from datetime import date

from polisi_scraper.adapters.base import BaseSiteAdapter, DocumentCandidate


class JpaAdapter(BaseSiteAdapter):
    slug = "jpa"
    agency = "Public Service Department"

    def iter_document_candidates(self, max_docs: int | None = None) -> list[DocumentCandidate]:
        candidates = [
            DocumentCandidate(
                source_page_url="https://docs.jpa.gov.my/docs/pekeliling",
                document_url="https://docs.jpa.gov.my/docs/pekeliling/2024/pp-bil-1-2024.pdf",
                title="Pekeliling Perkhidmatan Bil. 1/2024",
                file_type="pdf",
                published_at=date(2024, 4, 30),
            ),
            DocumentCandidate(
                source_page_url="https://docs.jpa.gov.my/docs/garis-panduan",
                document_url="https://docs.jpa.gov.my/docs/garis-panduan/2025/pengurusan-talent.xlsx",
                title="Data Pengurusan Talent Perkhidmatan Awam",
                file_type="xlsx",
                published_at=date(2025, 2, 5),
            ),
        ]
        return candidates if max_docs is None else candidates[:max_docs]
