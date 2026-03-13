"""
Tests for URL canonicalization, host allowlist, and make_absolute.
"""
import pytest

from moh_scraper.crawler import canonical_url, is_allowed_host, make_absolute


MOH_HOSTS = frozenset({"www.moh.gov.my"})


class TestCanonicalUrl:
    def test_forces_https(self):
        assert canonical_url("http://www.moh.gov.my/en/foo") == "https://www.moh.gov.my/en/foo"

    def test_lowercases_host(self):
        assert canonical_url("https://WWW.MOH.GOV.MY/en/foo") == "https://www.moh.gov.my/en/foo"

    def test_strips_fragment(self):
        assert canonical_url("https://www.moh.gov.my/en/foo#section") == "https://www.moh.gov.my/en/foo"

    def test_preserves_path(self):
        url = "https://www.moh.gov.my/en/media-kkm/media-statement/2026/test"
        assert canonical_url(url) == url

    def test_preserves_query_string(self):
        url = "https://www.moh.gov.my/en/media-kkm/media-statement/2026?start=10"
        assert canonical_url(url) == url

    def test_strips_fragment_with_query(self):
        result = canonical_url("https://www.moh.gov.my/en/foo?start=10#section")
        assert result == "https://www.moh.gov.my/en/foo?start=10"

    def test_already_canonical_unchanged(self):
        url = "https://www.moh.gov.my/images/doc.pdf"
        assert canonical_url(url) == url


class TestIsAllowedHost:
    def test_moh_allowed(self):
        assert is_allowed_host("https://www.moh.gov.my/en/foo", MOH_HOSTS)

    def test_external_blocked(self):
        assert not is_allowed_host("https://evil.com/doc.pdf", MOH_HOSTS)

    def test_subdomain_blocked(self):
        # Only www.moh.gov.my is in allowlist, not bare moh.gov.my
        assert not is_allowed_host("https://moh.gov.my/en/foo", MOH_HOSTS)

    def test_case_insensitive_host(self):
        assert is_allowed_host("https://WWW.MOH.GOV.MY/en/foo", MOH_HOSTS)


class TestMakeAbsolute:
    def test_relative_path(self):
        result = make_absolute("/en/media-kkm/media-statement/2026/slug", "https://www.moh.gov.my")
        assert result == "https://www.moh.gov.my/en/media-kkm/media-statement/2026/slug"

    def test_relative_pdf(self):
        result = make_absolute(
            "/images/kenyataan-media/2026/FEB/doc.pdf",
            "https://www.moh.gov.my"
        )
        assert result == "https://www.moh.gov.my/images/kenyataan-media/2026/FEB/doc.pdf"

    def test_absolute_url_unchanged(self):
        url = "https://www.moh.gov.my/images/doc.pdf"
        assert make_absolute(url, "https://www.moh.gov.my") == url

    def test_base_with_path(self):
        result = make_absolute(
            "sibling",
            "https://www.moh.gov.my/en/media-kkm/media-statement/2026"
        )
        # urljoin replaces last path segment
        assert "moh.gov.my" in result
