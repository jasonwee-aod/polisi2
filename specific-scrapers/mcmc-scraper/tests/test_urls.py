"""
Tests for URL canonicalization and host allowlist enforcement.
"""
import pytest

from mcmc_scraper.crawler import canonical_url, is_allowed_host, make_absolute


class TestCanonicalUrl:
    def test_forces_https(self):
        assert canonical_url("http://mcmc.gov.my/en/home").startswith("https://")

    def test_lowercases_host(self):
        result = canonical_url("https://MCMC.GOV.MY/en/home")
        assert "mcmc.gov.my" in result

    def test_strips_fragment(self):
        result = canonical_url("https://mcmc.gov.my/en/home#section")
        assert "#" not in result

    def test_preserves_path(self):
        result = canonical_url("https://mcmc.gov.my/en/media/press-releases")
        assert "/en/media/press-releases" in result

    def test_preserves_query_string(self):
        result = canonical_url("https://mcmc.gov.my/en/media/press-releases?page=2")
        assert "page=2" in result

    def test_already_canonical(self):
        url = "https://mcmc.gov.my/en/home"
        assert canonical_url(url) == url

    def test_www_variant(self):
        result = canonical_url("https://www.mcmc.gov.my/skmmgovmy/media/file.pdf")
        assert "www.mcmc.gov.my" in result


class TestIsAllowedHost:
    allowed = frozenset({"mcmc.gov.my", "www.mcmc.gov.my"})

    def test_primary_host_allowed(self):
        assert is_allowed_host("https://mcmc.gov.my/page", self.allowed)

    def test_www_host_allowed(self):
        assert is_allowed_host("https://www.mcmc.gov.my/media/file.pdf", self.allowed)

    def test_external_host_rejected(self):
        assert not is_allowed_host("https://example.com/page", self.allowed)

    def test_similar_host_rejected(self):
        assert not is_allowed_host("https://mcmc.gov.my.evil.com/page", self.allowed)

    def test_subdomain_rejected(self):
        assert not is_allowed_host("https://sub.mcmc.gov.my/page", self.allowed)

    def test_http_primary_host_allowed(self):
        # host check is independent of scheme
        assert is_allowed_host("http://mcmc.gov.my/page", self.allowed)


class TestMakeAbsolute:
    def test_relative_path(self):
        result = make_absolute("/en/media/press-releases", "https://mcmc.gov.my")
        assert result == "https://mcmc.gov.my/en/media/press-releases"

    def test_relative_path_with_base_path(self):
        result = make_absolute(
            "press-releases",
            "https://mcmc.gov.my/en/media/",
        )
        assert result == "https://mcmc.gov.my/en/media/press-releases"

    def test_absolute_url_unchanged(self):
        abs_url = "https://www.mcmc.gov.my/skmmgovmy/media/file.pdf"
        result = make_absolute(abs_url, "https://mcmc.gov.my")
        assert result == abs_url

    def test_query_param_url(self):
        result = make_absolute(
            "/en/media/press-releases?page=2", "https://mcmc.gov.my"
        )
        assert result == "https://mcmc.gov.my/en/media/press-releases?page=2"
