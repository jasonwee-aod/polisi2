from __future__ import annotations

from datetime import date

from polisi_scraper.adapters.base import BaseSiteAdapter, DocumentCandidate


class MohAdapter(BaseSiteAdapter):
    slug = "moh"
    agency = "Ministry of Health"

    def iter_document_candidates(self, max_docs: int | None = None) -> list[DocumentCandidate]:
        candidates = [
            DocumentCandidate(
                source_page_url="https://www.moh.gov.my/index.php/database_stores/store_view_page/21",
                document_url="https://www.moh.gov.my/resources/index/published_file/publications/CPG/diabetes-cpg-2025.pdf",
                title="Clinical Practice Guideline: Diabetes 2025",
                file_type="pdf",
                published_at=date(2025, 7, 19),
            ),
            DocumentCandidate(
                source_page_url="https://www.moh.gov.my/index.php/database_stores/store_view_page/21",
                document_url="https://www.moh.gov.my/resources/index/published_file/publications/garis-panduan-kesihatan-awam.docx",
                title="Garis Panduan Kesihatan Awam",
                file_type="docx",
                published_at=date(2024, 11, 2),
            ),
        ]
        return candidates if max_docs is None else candidates[:max_docs]
