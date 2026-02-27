from __future__ import annotations

from datetime import date

from polisi_scraper.adapters.base import BaseSiteAdapter, DocumentCandidate


class MofAdapter(BaseSiteAdapter):
    slug = "mof"
    agency = "Ministry of Finance"

    def iter_document_candidates(self, max_docs: int | None = None) -> list[DocumentCandidate]:
        candidates = [
            DocumentCandidate(
                source_page_url="https://www.mof.gov.my/portal/en/news/publications",
                document_url="https://www.mof.gov.my/portal/pdf/ekonomi/belanjawan/ucapan-belanjawan-2026.pdf",
                title="Ucapan Belanjawan 2026",
                file_type="pdf",
                published_at=date(2025, 10, 10),
            ),
            DocumentCandidate(
                source_page_url="https://www.mof.gov.my/portal/en/news/publications",
                document_url="https://www.mof.gov.my/portal/pdf/perolehan/garis-panduan-perolehan-2025.docx",
                title="Garis Panduan Perolehan 2025",
                file_type="docx",
                published_at=date(2025, 6, 2),
            ),
        ]
        return candidates if max_docs is None else candidates[:max_docs]
