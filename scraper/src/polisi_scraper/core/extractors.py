"""Default document link scanner for HTML pages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class DownloadLink:
    """A discovered download link on a page."""
    url: str
    label: str
    method: str = "GET"  # GET or PLAYWRIGHT


DOCUMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip",
}

DOWNLOAD_KEYWORDS = re.compile(
    r"muat\s*turun|download|unduh|descargar",
    re.IGNORECASE,
)


def extract_document_links(html: str, base_url: str) -> list[DownloadLink]:
    """Scan HTML for all downloadable document links.

    This is the default implementation. Adapters override for site-specific patterns.

    Finds:
    1. <a href> with document file extensions
    2. <a> where link text matches download keywords
    3. <iframe> with pdfjs-viewer patterns
    4. <a href> matching known CMS attachment patterns
    """
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    links: list[DownloadLink] = []

    def _add(url: str, label: str, method: str = "GET") -> None:
        absolute = urljoin(base_url, url)
        if absolute not in seen and absolute.startswith("http"):
            seen.add(absolute)
            links.append(DownloadLink(url=absolute, label=label, method=method))

    # 1. <a href> with document extensions
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href:
            continue
        absolute = urljoin(base_url, href)
        path_lower = urlparse(absolute).path.lower()

        # Direct document link
        if any(path_lower.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
            label = anchor.get_text(strip=True) or href
            _add(href, label)
            continue

        # Known CMS attachment patterns
        if "/getattachment/" in href or "/file" in path_lower:
            label = anchor.get_text(strip=True) or href
            _add(href, label)
            continue

        # Download keyword in link text
        link_text = anchor.get_text(strip=True)
        if link_text and DOWNLOAD_KEYWORDS.search(link_text):
            _add(href, link_text)
            continue

    # 2. pdfjs-viewer iframes
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"]
        if "viewer" in src.lower() and "file=" in src:
            match = re.search(r"file=([^&]+)", src)
            if match:
                file_url = unquote(match.group(1))
                _add(file_url, "pdfjs-viewer embed")

    return links
