"""Tests for URL canonicalization, host allowlist, and absolute URL helpers."""
import pytest

from dewan_selangor_scraper.crawler import canonical_url, is_allowed_host, make_absolute


class TestCanonicalUrl:
    def test_forces_https(self):
        assert canonical_url("http://dewan.selangor.gov.my/foo/") == \
               "https://dewan.selangor.gov.my/foo/"

    def test_lowercases_host(self):
        assert canonical_url("https://DEWAN.SELANGOR.GOV.MY/bar/") == \
               "https://dewan.selangor.gov.my/bar/"

    def test_strips_fragment(self):
        result = canonical_url("https://dewan.selangor.gov.my/page/#section")
        assert "#section" not in result
        assert result == "https://dewan.selangor.gov.my/page/"

    def test_preserves_query_string(self):
        url = "https://dewan.selangor.gov.my/search/?q=banjir&page=2"
        result = canonical_url(url)
        assert "q=banjir" in result
        assert "page=2" in result

    def test_preserves_path(self):
        url = "https://dewan.selangor.gov.my/wp-content/uploads/2025/11/doc.pdf"
        assert canonical_url(url) == url

    def test_already_canonical_unchanged(self):
        url = "https://dewan.selangor.gov.my/berita-dewan/"
        assert canonical_url(url) == url


class TestIsAllowedHost:
    ALLOWED = frozenset({"dewan.selangor.gov.my"})

    def test_primary_host_allowed(self):
        assert is_allowed_host(
            "https://dewan.selangor.gov.my/foo/", self.ALLOWED
        )

    def test_external_host_blocked(self):
        assert not is_allowed_host(
            "https://example.com/doc.pdf", self.ALLOWED
        )

    def test_subdomain_blocked_by_default(self):
        assert not is_allowed_host(
            "https://assets.dewan.selangor.gov.my/doc.pdf", self.ALLOWED
        )

    def test_case_insensitive(self):
        assert is_allowed_host(
            "https://DEWAN.SELANGOR.GOV.MY/page/", self.ALLOWED
        )


class TestMakeAbsolute:
    BASE = "https://dewan.selangor.gov.my/berita-dewan/"

    def test_absolute_href_unchanged(self):
        href = "https://dewan.selangor.gov.my/some-post/"
        assert make_absolute(href, self.BASE) == href

    def test_relative_href_resolved(self):
        result = make_absolute("/wp-content/uploads/2025/01/doc.pdf", self.BASE)
        assert result == "https://dewan.selangor.gov.my/wp-content/uploads/2025/01/doc.pdf"

    def test_scheme_relative_href(self):
        result = make_absolute("//dewan.selangor.gov.my/page/", self.BASE)
        assert result.startswith("https://")
