"""Tests for URL canonicalization and host allowlist enforcement."""
import pytest

from idfr_scraper.crawler import canonical_url, is_allowed_host, make_absolute

BASE = "https://www.idfr.gov.my"
_IDFR_HOSTS = frozenset({"www.idfr.gov.my", "idfr.gov.my"})


class TestCanonicalUrl:
    def test_forces_https(self):
        url = canonical_url("http://www.idfr.gov.my/my/media-1/press")
        assert url.startswith("https://")

    def test_strips_fragment(self):
        url = canonical_url("https://www.idfr.gov.my/my/publications#section")
        assert "#" not in url

    def test_lowercases_host(self):
        url = canonical_url("https://WWW.IDFR.GOV.MY/my/media-1/press")
        assert "www.idfr.gov.my" in url

    def test_preserves_path(self):
        url = canonical_url("https://www.idfr.gov.my/my/images/stories/press/test.pdf")
        assert "/my/images/stories/press/test.pdf" in url

    def test_preserves_query_string(self):
        url = canonical_url("https://www.idfr.gov.my/my/media-1/speeches?year=2024")
        assert "year=2024" in url

    def test_idempotent(self):
        url = "https://www.idfr.gov.my/my/media-1/press"
        assert canonical_url(url) == canonical_url(canonical_url(url))


class TestIsAllowedHost:
    def test_www_idfr_gov_my_allowed(self):
        assert is_allowed_host("https://www.idfr.gov.my/my/publications", _IDFR_HOSTS)

    def test_idfr_gov_my_without_www_allowed(self):
        assert is_allowed_host("https://idfr.gov.my/my/publications", _IDFR_HOSTS)

    def test_external_host_rejected(self):
        assert not is_allowed_host("https://example.com/document.pdf", _IDFR_HOSTS)

    def test_subdomain_rejected(self):
        assert not is_allowed_host("https://cas.idfr.gov.my/login", _IDFR_HOSTS)

    def test_case_insensitive_host(self):
        assert is_allowed_host("https://WWW.IDFR.GOV.MY/test", _IDFR_HOSTS)


class TestMakeAbsolute:
    def test_absolute_url_unchanged(self):
        href = "https://www.idfr.gov.my/my/images/test.pdf"
        result = make_absolute(href, BASE)
        assert result == href

    def test_root_relative_url(self):
        href = "/my/images/stories/press/test.pdf"
        result = make_absolute(href, BASE)
        assert result == f"{BASE}/my/images/stories/press/test.pdf"

    def test_relative_url_resolved(self):
        base = "https://www.idfr.gov.my/my/media-1/press"
        href = "../images/stories/press/test.pdf"
        result = make_absolute(href, base)
        assert result == "https://www.idfr.gov.my/my/images/stories/press/test.pdf"

    def test_protocol_relative_url(self):
        href = "//www.idfr.gov.my/my/images/test.pdf"
        result = make_absolute(href, BASE)
        assert "idfr.gov.my" in result
