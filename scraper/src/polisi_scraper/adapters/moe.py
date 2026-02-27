from __future__ import annotations

from datetime import date

from polisi_scraper.adapters.base import BaseSiteAdapter, DocumentCandidate


class MoeAdapter(BaseSiteAdapter):
    slug = "moe"
    agency = "Ministry of Education"

    def iter_document_candidates(self, max_docs: int | None = None) -> list[DocumentCandidate]:
        candidates = [
            DocumentCandidate(
                source_page_url="https://www.moe.gov.my/en/muat-turun/pekeliling",
                document_url="https://www.moe.gov.my/muat-turun/pekeliling/2025/pekeliling-ikhtisas-bil-1-2025.pdf",
                title="Pekeliling Ikhtisas Bil. 1/2025",
                file_type="pdf",
                published_at=date(2025, 1, 15),
            ),
            DocumentCandidate(
                source_page_url="https://www.moe.gov.my/en/muat-turun/laporan",
                document_url="https://www.moe.gov.my/muat-turun/laporan/2024/pelan-tindakan-bahasa-melayu.html",
                title="Pelan Tindakan Bahasa Melayu",
                file_type="html",
                published_at=date(2024, 9, 12),
            ),
        ]
        return candidates if max_docs is None else candidates[:max_docs]
