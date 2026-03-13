"""URL canonicalization and host allowlist enforcement."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, urlunparse


def canonical_url(url: str) -> str:
    """Normalize a URL for deduplication.

    - Force HTTPS
    - Lowercase scheme and host
    - Strip fragment
    - Preserve path and query string as-is
    """
    parsed = urlparse(url.strip())
    return urlunparse((
        "https",
        parsed.netloc.lower(),
        parsed.path,
        "",            # params
        parsed.query,
        "",            # fragment stripped
    ))


def make_absolute(href: str, base_url: str) -> str:
    """Resolve a potentially relative href against a base URL."""
    return urljoin(base_url, href)


def is_allowed_host(url: str, allowed_hosts: frozenset[str] | set[str]) -> bool:
    """Return True if the URL's host is in the allowlist."""
    host = urlparse(url).netloc.lower()
    return host in allowed_hosts


def guess_content_type(url: str) -> str:
    """Infer MIME type from file extension in URL."""
    path = urlparse(url).path.lower()
    ext_map = {
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".ppt": "application/vnd.ms-powerpoint",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".zip": "application/zip",
        ".html": "text/html",
        ".htm": "text/html",
    }
    for ext, mime in ext_map.items():
        if path.endswith(ext):
            return mime
    return "application/octet-stream"


def is_document_url(url: str) -> bool:
    """Return True if the URL points to a downloadable document."""
    exts = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip"}
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in exts)
