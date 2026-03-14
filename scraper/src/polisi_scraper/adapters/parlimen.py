"""Parlimen adapter — Malaysian Parliament (parlimen.gov.my).

Scrapes four key document sections via the dhtmlXTree AJAX API and
static HTML pages:

1. Hansard (Penyata Rasmi)       — DR & DN parliamentary debate records
2. Jawapan Lisan                 — Oral question replies
3. Jawapan Bukan Lisan           — Written question replies
4. Akta-Akta                     — Acts/legislation

The AJAX tree API exposes a 4-level hierarchy:
    Level 0 (root):      ?arkib=yes&ajx=0           -> Parlimen list
    Level 1 (penggal):   ?arkib=yes&ajx=1&id=0_15   -> Penggal within Parlimen
    Level 2 (mesyuarat): ?arkib=yes&ajx=1&id=0_15_4 -> Mesyuarat within Penggal
    Level 3 (PDFs):      ?arkib=yes&ajx=1&id=0_15_4_1 -> Leaf nodes with PDF URLs

PDF URLs are extracted from <userdata name="myurl"> elements containing
javascript:loadResult('/files/...pdf', '...') calls.

SSL verification is disabled (known certificate issues).
A session cookie (GENPRO_SESSION) is required for PDF downloads.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from polisi_scraper.adapters.base import BaseSiteAdapter, DiscoveredItem, DocumentCandidate
from polisi_scraper.adapters.registry import register_adapter
from polisi_scraper.core.urls import guess_content_type

log = logging.getLogger(__name__)

BASE_URL = "https://www.parlimen.gov.my"

# Regex to extract PDF path from javascript:loadResult('/files/...pdf', '...')
_LOAD_RESULT_RE = re.compile(
    r"loadResult\(\s*['\"]([^'\"]+\.pdf)['\"]",
    re.IGNORECASE,
)

# Regex to extract a date from Hansard filenames like DR-03022025.pdf
_HANSARD_DATE_RE = re.compile(r"[A-Z]{2,4}-?(\d{2})(\d{2})(\d{4})\.pdf", re.IGNORECASE)


def _parse_filename_date(filename: str) -> str:
    """Try to extract ISO date from a parlimen PDF filename.

    Patterns: DR-03022025.pdf -> 2025-02-03, JDR05032025.pdf -> 2025-03-05
    """
    m = _HANSARD_DATE_RE.search(filename)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        try:
            return f"{yyyy}-{mm}-{dd}"
        except ValueError:
            pass
    return ""


def _extract_pdf_urls_from_xml(xml_text: str, base_url: str) -> list[dict]:
    """Parse dhtmlXTree AJAX XML and extract PDF info from leaf nodes.

    Returns list of dicts: {"url": str, "title": str, "date": str}
    """
    soup = BeautifulSoup(xml_text, "lxml-xml")
    results: list[dict] = []

    for item in soup.find_all("item"):
        userdata = item.find("userdata", attrs={"name": "myurl"})
        if not userdata:
            continue
        text = userdata.get_text(strip=True)
        m = _LOAD_RESULT_RE.search(text)
        if not m:
            continue
        pdf_path = m.group(1)
        pdf_url = urljoin(base_url, pdf_path)
        title = item.get("text", "")
        filename = pdf_path.split("/")[-1]
        pub_date = _parse_filename_date(filename)

        results.append({
            "url": pdf_url,
            "title": title,
            "date": pub_date,
            "filename": filename,
        })

    return results


def _extract_child_ids_from_xml(xml_text: str) -> list[str]:
    """Parse dhtmlXTree AJAX XML and extract child node IDs for recursion."""
    soup = BeautifulSoup(xml_text, "lxml-xml")
    ids: list[str] = []
    for item in soup.find_all("item"):
        child_attr = item.get("child", "0")
        item_id = item.get("id", "")
        if item_id:
            ids.append(item_id)
    return ids


@register_adapter
class ParlimenAdapter(BaseSiteAdapter):
    slug = "parlimen"
    agency = "Parlimen Malaysia"
    requires_browser = False

    def _base_url(self) -> str:
        return self.config.get("base_url", BASE_URL)

    def discover(self, since: date | None = None, max_pages: int = 0) -> Iterable[DiscoveredItem]:
        """Walk all configured sections and yield DiscoveredItems."""
        sections = self.config.get("sections", [])
        pages_fetched = 0

        for section in sections:
            source_type = section.get("source_type", "ajax_tree")
            doc_type = section.get("doc_type", "report")
            language = section.get("language", "ms")
            section_name = section.get("name", "unknown")

            log.info("[parlimen] discover section=%s source_type=%s", section_name, source_type)

            if source_type == "ajax_tree":
                archive_url = section.get("archive_url", "")
                if not archive_url:
                    continue
                for item in self._discover_from_ajax_tree(
                    archive_url, doc_type, language, since, section_name,
                ):
                    pages_fetched += 1
                    if max_pages and pages_fetched >= max_pages:
                        log.info("[parlimen] max_pages=%d reached", max_pages)
                        return
                    yield item

            elif source_type == "static":
                page_url = section.get("url", "")
                if not page_url:
                    continue
                yield from self._discover_from_static_page(
                    page_url, doc_type, language, section_name,
                )

    def _discover_from_ajax_tree(
        self,
        archive_url: str,
        doc_type: str,
        language: str,
        since: date | None,
        section_name: str,
    ) -> Iterable[DiscoveredItem]:
        """Walk the dhtmlXTree 4-level AJAX API to find all PDFs."""
        base = self._base_url()

        # Ensure we have a session cookie by hitting the archive page first
        log.info("[parlimen] initializing session: %s", archive_url)
        try:
            self.http.get(archive_url)
        except Exception as exc:
            log.error("[parlimen] session init failed %s: %s", archive_url, exc)
            return

        # Level 0: get all Parlimen
        root_url = f"{archive_url}&ajx=0"
        log.info("[parlimen] fetching tree root: %s", root_url)
        try:
            resp = self.http.get(root_url)
        except Exception as exc:
            log.error("[parlimen] tree root fetch error: %s", exc)
            return

        parlimen_ids = _extract_child_ids_from_xml(resp.text)
        log.info("[parlimen] %s: found %d parlimen", section_name, len(parlimen_ids))

        for parlimen_id in parlimen_ids:
            # Level 1: get Penggal within each Parlimen
            level1_url = f"{archive_url}&ajx=1&id={parlimen_id}"
            log.info("[parlimen] fetching penggal: %s", level1_url)
            try:
                resp1 = self.http.get(level1_url)
            except Exception as exc:
                log.error("[parlimen] penggal fetch error %s: %s", parlimen_id, exc)
                continue

            penggal_ids = _extract_child_ids_from_xml(resp1.text)

            for penggal_id in penggal_ids:
                # Level 2: get Mesyuarat within each Penggal
                level2_url = f"{archive_url}&ajx=1&id={penggal_id}"
                log.info("[parlimen] fetching mesyuarat: %s", level2_url)
                try:
                    resp2 = self.http.get(level2_url)
                except Exception as exc:
                    log.error("[parlimen] mesyuarat fetch error %s: %s", penggal_id, exc)
                    continue

                mesyuarat_ids = _extract_child_ids_from_xml(resp2.text)

                for mesyuarat_id in mesyuarat_ids:
                    # Level 3: get leaf PDFs
                    level3_url = f"{archive_url}&ajx=1&id={mesyuarat_id}"
                    log.info("[parlimen] fetching PDFs: %s", level3_url)
                    try:
                        resp3 = self.http.get(level3_url)
                    except Exception as exc:
                        log.error("[parlimen] PDF list fetch error %s: %s", mesyuarat_id, exc)
                        continue

                    pdfs = _extract_pdf_urls_from_xml(resp3.text, base)
                    log.info("[parlimen] %s: %d PDFs from %s",
                             section_name, len(pdfs), mesyuarat_id)

                    for pdf in pdfs:
                        pub_date = pdf.get("date", "")
                        if since and pub_date:
                            try:
                                if date.fromisoformat(pub_date) < since:
                                    continue
                            except ValueError:
                                pass

                        yield DiscoveredItem(
                            source_url=pdf["url"],
                            title=pdf.get("title", pdf.get("filename", "")),
                            published_at=pub_date,
                            doc_type=doc_type,
                            language=language,
                            metadata={
                                "section": section_name,
                                "source_type": "ajax_tree",
                                "filename": pdf.get("filename", ""),
                                "parlimen_id": mesyuarat_id,
                            },
                        )

    def _discover_from_static_page(
        self,
        page_url: str,
        doc_type: str,
        language: str,
        section_name: str,
    ) -> Iterable[DiscoveredItem]:
        """Scrape PDF links from a static HTML page (e.g. Akta-Akta)."""
        base = self._base_url()

        log.info("[parlimen] fetch static page: %s", page_url)
        try:
            resp = self.http.get(page_url)
        except Exception as exc:
            log.error("[parlimen] static page fetch error %s: %s", page_url, exc)
            return

        soup = BeautifulSoup(resp.text, "lxml")
        seen: set[str] = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href.lower().endswith(".pdf"):
                continue
            abs_url = urljoin(base, href)
            if abs_url in seen:
                continue
            seen.add(abs_url)

            title = a.get_text(strip=True) or abs_url.split("/")[-1]

            yield DiscoveredItem(
                source_url=abs_url,
                title=title,
                published_at="",
                doc_type=doc_type,
                language=language,
                metadata={
                    "section": section_name,
                    "source_type": "static",
                },
            )

        log.info("[parlimen] %s: %d PDFs from static page", section_name, len(seen))

    def fetch_and_extract(self, item: DiscoveredItem) -> Iterable[DocumentCandidate]:
        """Yield the PDF as a direct download candidate."""
        ct = guess_content_type(item.source_url)
        yield DocumentCandidate(
            url=item.source_url,
            source_page_url=item.metadata.get("section", item.source_url),
            title=item.title,
            published_at=item.published_at,
            doc_type=item.doc_type,
            content_type=ct or "application/pdf",
            language=item.language,
        )
