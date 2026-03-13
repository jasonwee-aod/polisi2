"""
Tests for URL helpers: canonical_url, make_absolute, is_allowed_host.
"""
import pytest

from rmp_scraper.crawler import canonical_url, is_allowed_host, make_absolute

ALLOWED = frozenset({"www.rmp.gov.my"})


class TestCanonicalUrl:
    def test_forces_https(self):
        assert canonical_url("http://www.rmp.gov.my/foo").startswith("https://")

    def test_lowercases_host(self):
        url = canonical_url("https://WWW.RMP.GOV.MY/foo")
        assert "WWW" not in url
        assert "www.rmp.gov.my" in url

    def test_strips_fragment(self):
        url = canonical_url("https://www.rmp.gov.my/foo#section")
        assert "#" not in url

    def test_preserves_query_string(self):
        url = canonical_url("https://www.rmp.gov.my/docs/file.pdf?sfvrsn=2")
        assert "sfvrsn=2" in url

    def test_preserves_path(self):
        url = canonical_url("https://www.rmp.gov.my/arkib-berita/berita/page/2")
        assert "/arkib-berita/berita/page/2" in url

    def test_idempotent(self):
        url = "https://www.rmp.gov.my/laman-utama/penerbitan"
        assert canonical_url(url) == canonical_url(canonical_url(url))


class TestMakeAbsolute:
    def test_relative_href(self):
        result = make_absolute("/arkib-berita/berita/2026/03/09/slug", "https://www.rmp.gov.my")
        assert result == "https://www.rmp.gov.my/arkib-berita/berita/2026/03/09/slug"

    def test_absolute_href_unchanged(self):
        href = "https://www.rmp.gov.my/docs/file.pdf"
        result = make_absolute(href, "https://www.rmp.gov.my")
        assert result == href

    def test_relative_with_base_path(self):
        result = make_absolute("page/2", "https://www.rmp.gov.my/arkib-berita/berita")
        assert "page/2" in result


class TestIsAllowedHost:
    def test_rmp_allowed(self):
        assert is_allowed_host("https://www.rmp.gov.my/foo", ALLOWED) is True

    def test_external_blocked(self):
        assert is_allowed_host("https://www.google.com/", ALLOWED) is False

    def test_http_rmp_allowed(self):
        # is_allowed_host checks netloc, not scheme
        assert is_allowed_host("http://www.rmp.gov.my/foo", ALLOWED) is True

    def test_subdomain_blocked(self):
        assert is_allowed_host("https://old.rmp.gov.my/foo", ALLOWED) is False

    def test_default_allowlist_used_when_none(self):
        # Default allowlist has www.rmp.gov.my
        assert is_allowed_host("https://www.rmp.gov.my/foo") is True
