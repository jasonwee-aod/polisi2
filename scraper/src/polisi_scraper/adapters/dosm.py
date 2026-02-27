from __future__ import annotations

from datetime import date

from polisi_scraper.adapters.base import BaseSiteAdapter, DocumentCandidate


class DosmAdapter(BaseSiteAdapter):
    slug = "dosm"
    agency = "Department of Statistics Malaysia"

    def iter_document_candidates(self, max_docs: int | None = None) -> list[DocumentCandidate]:
        candidates = [
            DocumentCandidate(
                source_page_url="https://open.dosm.gov.my/data-catalogue",
                document_url="https://storage.dosm.gov.my/open-data/labour-force-survey-2025.xlsx",
                title="Labour Force Survey 2025",
                file_type="xlsx",
                published_at=date(2025, 8, 14),
            ),
            DocumentCandidate(
                source_page_url="https://www.dosm.gov.my/portal-main/release-content",
                document_url="https://www.dosm.gov.my/release-content/consumer-price-index-feb-2025.html",
                title="Consumer Price Index February 2025",
                file_type="html",
                published_at=date(2025, 3, 22),
            ),
        ]
        return candidates if max_docs is None else candidates[:max_docs]
