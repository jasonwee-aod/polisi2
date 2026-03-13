"""Tests for polisi_scraper.core.urls — URL utilities."""

from __future__ import annotations

import pytest

from polisi_scraper.core.urls import (
    canonical_url,
    guess_content_type,
    is_allowed_host,
    is_document_url,
    make_absolute,
)


# ---------------------------------------------------------------------------
# canonical_url
# ---------------------------------------------------------------------------


class TestCanonicalUrl:
    """canonical_url normalizes URLs for deduplication."""

    def test_forces_https(self) -> None:
        result = canonical_url("http://example.gov.my/page")
        assert result.startswith("https://")

    def test_lowercases_host(self) -> None:
        result = canonical_url("http://WWW.EXAMPLE.GOV.MY/page")
        assert "www.example.gov.my" in result

    def test_strips_fragment(self) -> None:
        result = canonical_url("https://example.gov.my/page#section1")
        assert "#" not in result

    def test_preserves_query(self) -> None:
        result = canonical_url("https://example.gov.my/page?id=42&lang=ms")
        assert "id=42&lang=ms" in result

    def test_preserves_path(self) -> None:
        result = canonical_url("https://example.gov.my/a/b/c.pdf")
        assert "/a/b/c.pdf" in result

    def test_idempotent(self) -> None:
        url = "https://example.gov.my/page?q=1"
        assert canonical_url(url) == canonical_url(canonical_url(url))

    def test_strips_whitespace(self) -> None:
        result = canonical_url("  https://example.gov.my/page  ")
        assert result == "https://example.gov.my/page"


# ---------------------------------------------------------------------------
# make_absolute
# ---------------------------------------------------------------------------


class TestMakeAbsolute:
    """make_absolute resolves relative paths against a base URL."""

    def test_relative_path(self) -> None:
        result = make_absolute("/docs/file.pdf", "https://example.gov.my/page")
        assert result == "https://example.gov.my/docs/file.pdf"

    def test_already_absolute(self) -> None:
        result = make_absolute("https://other.gov.my/file.pdf", "https://example.gov.my/")
        assert result == "https://other.gov.my/file.pdf"

    def test_fragment_only(self) -> None:
        result = make_absolute("#section", "https://example.gov.my/page")
        assert result == "https://example.gov.my/page#section"

    def test_relative_without_leading_slash(self) -> None:
        result = make_absolute("file.pdf", "https://example.gov.my/docs/index.html")
        assert result == "https://example.gov.my/docs/file.pdf"


# ---------------------------------------------------------------------------
# is_allowed_host
# ---------------------------------------------------------------------------


class TestIsAllowedHost:
    """is_allowed_host checks URL hostname against an allowlist."""

    def test_in_allowlist(self) -> None:
        hosts = frozenset({"example.gov.my", "other.gov.my"})
        assert is_allowed_host("https://example.gov.my/page", hosts) is True

    def test_not_in_allowlist(self) -> None:
        hosts = frozenset({"example.gov.my"})
        assert is_allowed_host("https://evil.com/page", hosts) is False

    def test_case_insensitive(self) -> None:
        hosts = frozenset({"example.gov.my"})
        assert is_allowed_host("https://EXAMPLE.GOV.MY/page", hosts) is True

    def test_empty_allowlist(self) -> None:
        assert is_allowed_host("https://example.gov.my/page", frozenset()) is False


# ---------------------------------------------------------------------------
# guess_content_type
# ---------------------------------------------------------------------------


class TestGuessContentType:
    """guess_content_type maps file extensions to MIME types."""

    @pytest.mark.parametrize(
        "url, expected_mime",
        [
            ("https://example.gov.my/file.pdf", "application/pdf"),
            ("https://example.gov.my/file.doc", "application/msword"),
            (
                "https://example.gov.my/file.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            ("https://example.gov.my/file.xls", "application/vnd.ms-excel"),
            (
                "https://example.gov.my/file.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            ("https://example.gov.my/file.ppt", "application/vnd.ms-powerpoint"),
            (
                "https://example.gov.my/file.pptx",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ),
            ("https://example.gov.my/file.zip", "application/zip"),
            ("https://example.gov.my/file.html", "text/html"),
            ("https://example.gov.my/file.htm", "text/html"),
        ],
    )
    def test_known_extensions(self, url: str, expected_mime: str) -> None:
        assert guess_content_type(url) == expected_mime

    def test_unknown_extension(self) -> None:
        assert guess_content_type("https://example.gov.my/file.xyz") == "application/octet-stream"

    def test_no_extension(self) -> None:
        assert guess_content_type("https://example.gov.my/file") == "application/octet-stream"


# ---------------------------------------------------------------------------
# is_document_url
# ---------------------------------------------------------------------------


class TestIsDocumentUrl:
    """is_document_url identifies downloadable document URLs."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.gov.my/report.pdf",
            "https://example.gov.my/report.doc",
            "https://example.gov.my/report.docx",
            "https://example.gov.my/data.xls",
            "https://example.gov.my/data.xlsx",
            "https://example.gov.my/slides.ppt",
            "https://example.gov.my/slides.pptx",
            "https://example.gov.my/archive.zip",
        ],
    )
    def test_document_extensions_return_true(self, url: str) -> None:
        assert is_document_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.gov.my/page.html",
            "https://example.gov.my/image.jpg",
            "https://example.gov.my/page",
            "https://example.gov.my/page.htm",
        ],
    )
    def test_non_document_extensions_return_false(self, url: str) -> None:
        assert is_document_url(url) is False
