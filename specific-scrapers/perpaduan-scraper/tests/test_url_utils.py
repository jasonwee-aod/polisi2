"""Tests for URL utilities."""
import pytest
from src.url_utils import canonicalize_url, is_same_domain, extract_absolute_url


class TestCanonicalizeUrl:
    def test_http_to_https(self):
        result = canonicalize_url(
            "http://www.perpaduan.gov.my/index.php/bm/",
            allowed_hosts=["www.perpaduan.gov.my"]
        )
        assert result == "https://www.perpaduan.gov.my/index.php/bm"

    def test_trailing_slash_removed(self):
        result = canonicalize_url(
            "https://perpaduan.gov.my/index.php/bm/",
            allowed_hosts=["perpaduan.gov.my"]
        )
        assert result == "https://perpaduan.gov.my/index.php/bm"

    def test_invalid_host(self):
        result = canonicalize_url(
            "https://evil.com/page",
            allowed_hosts=["www.perpaduan.gov.my"]
        )
        assert result is None

    def test_www_variance(self):
        # Both www and non-www variants allowed
        result = canonicalize_url(
            "https://perpaduan.gov.my/page",
            allowed_hosts=["www.perpaduan.gov.my", "perpaduan.gov.my"]
        )
        assert result == "https://perpaduan.gov.my/page"

    def test_invalid_url(self):
        result = canonicalize_url("not a url")
        assert result is None


class TestIsSameDomain:
    def test_same_domain(self):
        assert is_same_domain(
            "https://www.perpaduan.gov.my/page1",
            "https://www.perpaduan.gov.my/page2"
        )

    def test_different_domain(self):
        assert not is_same_domain(
            "https://www.perpaduan.gov.my/page",
            "https://evil.com/page"
        )

    def test_different_subdomains(self):
        assert not is_same_domain(
            "https://sub1.perpaduan.gov.my/page",
            "https://sub2.perpaduan.gov.my/page"
        )


class TestExtractAbsoluteUrl:
    def test_absolute_url(self):
        result = extract_absolute_url(
            "https://perpaduan.gov.my/page",
            "https://example.com/"
        )
        assert result == "https://perpaduan.gov.my/page"

    def test_absolute_path(self):
        result = extract_absolute_url(
            "/index.php/bm/page",
            "https://perpaduan.gov.my/some/path"
        )
        assert result == "https://perpaduan.gov.my/index.php/bm/page"

    def test_relative_path(self):
        result = extract_absolute_url(
            "page.html",
            "https://perpaduan.gov.my/section/"
        )
        assert "https://perpaduan.gov.my" in result
        assert "page.html" in result
