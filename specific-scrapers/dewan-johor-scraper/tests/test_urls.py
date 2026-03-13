"""Tests for URL canonicalization, host allowlist, and absolute URL helpers."""
import pytest

from dewan_johor_scraper.crawler import canonical_url, is_allowed_host, make_absolute

BASE_HOST = "dewannegeri.johor.gov.my"
ALLOWED = frozenset({BASE_HOST})


class TestCanonicalUrl:
    def test_forces_https(self):
        assert canonical_url("http://dewannegeri.johor.gov.my/foo/") == \
               "https://dewannegeri.johor.gov.my/foo/"

    def test_lowercases_host(self):
        assert canonical_url("https://DEWANNEGERI.JOHOR.GOV.MY/bar/") == \
               "https://dewannegeri.johor.gov.my/bar/"

    def test_strips_fragment(self):
        result = canonical_url("https://dewannegeri.johor.gov.my/page/#section")
        assert "#section" not in result
        assert result == "https://dewannegeri.johor.gov.my/page/"

    def test_preserves_query_string(self):
        url = "https://dewannegeri.johor.gov.my/download/28-jun-2018/?wpdmdl=3910&ind=123"
        result = canonical_url(url)
        assert "wpdmdl=3910" in result
        assert "ind=123" in result

    def test_preserves_path(self):
        url = "https://dewannegeri.johor.gov.my/wp-content/uploads/2019/07/doc.pdf"
        assert canonical_url(url) == url

    def test_already_canonical_unchanged(self):
        url = "https://dewannegeri.johor.gov.my/download/28-jun-2018/"
        assert canonical_url(url) == url


class TestIsAllowedHost:
    def test_primary_host_allowed(self):
        assert is_allowed_host(
            "https://dewannegeri.johor.gov.my/foo/", ALLOWED
        )

    def test_external_host_blocked(self):
        assert not is_allowed_host(
            "https://example.com/doc.pdf", ALLOWED
        )

    def test_subdomain_blocked_by_default(self):
        assert not is_allowed_host(
            "https://assets.dewannegeri.johor.gov.my/doc.pdf", ALLOWED
        )

    def test_case_insensitive(self):
        assert is_allowed_host(
            "https://DEWANNEGERI.JOHOR.GOV.MY/page/", ALLOWED
        )

    def test_http_scheme_with_correct_host_allowed(self):
        # Scheme is irrelevant for host check; only netloc matters
        assert is_allowed_host(
            "http://dewannegeri.johor.gov.my/page/", ALLOWED
        )


class TestMakeAbsolute:
    BASE = "https://dewannegeri.johor.gov.my/category/pengumuman/"

    def test_absolute_href_unchanged(self):
        href = "https://dewannegeri.johor.gov.my/2019/07/27/some-post/"
        assert make_absolute(href, self.BASE) == href

    def test_relative_href_resolved(self):
        result = make_absolute("/wp-content/uploads/2019/07/doc.pdf", self.BASE)
        assert result == "https://dewannegeri.johor.gov.my/wp-content/uploads/2019/07/doc.pdf"

    def test_scheme_relative_href(self):
        result = make_absolute("//dewannegeri.johor.gov.my/page/", self.BASE)
        assert result.startswith("https://")
