"""Tests for URL normalization and canonicalization."""

import pytest
from mohe_scraper.url_utils import URLNormalizer, URLExtractor


class TestURLNormalizer:
    """Test URL normalization."""

    @pytest.fixture
    def normalizer(self):
        return URLNormalizer(["www.mohe.gov.my", "mohe.gov.my"])

    def test_canonicalize_basic(self, normalizer):
        """Test basic URL canonicalization."""
        url = "https://www.mohe.gov.my/en/broadcast/announcements"
        canonical = normalizer.canonicalize(url)
        assert canonical == "https://mohe.gov.my/en/broadcast/announcements"

    def test_canonicalize_removes_www(self, normalizer):
        """Test that www prefix is removed."""
        url = "https://www.mohe.gov.my/en/test"
        canonical = normalizer.canonicalize(url)
        assert "www." not in canonical

    def test_canonicalize_https_enforcement(self, normalizer):
        """Test that HTTP is converted to HTTPS."""
        url = "http://mohe.gov.my/en/test"
        canonical = normalizer.canonicalize(url)
        assert canonical.startswith("https://")

    def test_canonicalize_removes_fragment(self, normalizer):
        """Test that URL fragments are removed."""
        url = "https://www.mohe.gov.my/en/test#section"
        canonical = normalizer.canonicalize(url)
        assert "#" not in canonical

    def test_canonicalize_removes_tracking_params(self, normalizer):
        """Test that tracking parameters are removed."""
        url = "https://www.mohe.gov.my/en/test?utm_source=facebook&id=123"
        canonical = normalizer.canonicalize(url)
        assert "utm_source" not in canonical
        assert "id=123" in canonical

    def test_canonicalize_sorts_params(self, normalizer):
        """Test that query parameters are sorted."""
        url1 = "https://www.mohe.gov.my/en/test?z=1&a=2&m=3"
        url2 = "https://www.mohe.gov.my/en/test?a=2&m=3&z=1"
        canonical1 = normalizer.canonicalize(url1)
        canonical2 = normalizer.canonicalize(url2)
        assert canonical1 == canonical2

    def test_is_allowed_host_true(self, normalizer):
        """Test allowed host detection."""
        assert normalizer.is_allowed_host("https://www.mohe.gov.my/en/test")
        assert normalizer.is_allowed_host("https://mohe.gov.my/en/test")

    def test_is_allowed_host_false(self, normalizer):
        """Test rejection of disallowed hosts."""
        assert not normalizer.is_allowed_host("https://example.com/en/test")
        assert not normalizer.is_allowed_host("https://mohe.gov/en/test")

    def test_canonicalize_disallowed_host(self, normalizer):
        """Test that disallowed hosts return None."""
        url = "https://example.com/en/test"
        canonical = normalizer.canonicalize(url)
        assert canonical is None

    def test_canonicalize_trailing_slash(self, normalizer):
        """Test that trailing slashes are removed (except root)."""
        url = "https://www.mohe.gov.my/en/broadcast/announcements/"
        canonical = normalizer.canonicalize(url)
        assert canonical.endswith("announcements")
        assert not canonical.endswith("/")

    def test_canonicalize_case_insensitive(self, normalizer):
        """Test that URLs are lowercased."""
        url = "https://WWW.MOHE.GOV.MY/EN/TEST"
        canonical = normalizer.canonicalize(url)
        assert canonical == canonical.lower()


class TestURLExtractor:
    """Test URL extraction utilities."""

    def test_extract_filename_from_url(self):
        """Test filename extraction."""
        url = "https://mohe.gov.my/documents/2026/report.pdf"
        filename = URLExtractor.extract_filename_from_url(url)
        assert filename == "report.pdf"

    def test_extract_filename_no_extension(self):
        """Test filename extraction without extension."""
        url = "https://mohe.gov.my/documents/2026/document"
        filename = URLExtractor.extract_filename_from_url(url)
        assert filename == "document"

    def test_get_content_type_pdf(self):
        """Test content type detection for PDF."""
        content_type = URLExtractor.get_content_type_from_url("file.pdf")
        assert content_type == "application/pdf"

    def test_get_content_type_docx(self):
        """Test content type detection for DOCX."""
        content_type = URLExtractor.get_content_type_from_url("document.docx")
        assert content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def test_get_content_type_default(self):
        """Test default content type."""
        content_type = URLExtractor.get_content_type_from_url("page.html")
        assert content_type == "text/html"

    def test_extract_absolute_url_absolute(self):
        """Test absolute URL remains unchanged."""
        base = "https://mohe.gov.my/"
        url = "https://mohe.gov.my/en/test"
        result = URLExtractor.extract_absolute_url(url, base)
        assert result == url

    def test_extract_absolute_url_relative(self):
        """Test relative URL is resolved."""
        base = "https://mohe.gov.my/en/"
        url = "test"
        result = URLExtractor.extract_absolute_url(url, base)
        assert result == "https://mohe.gov.my/en/test"
