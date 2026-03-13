"""
Tests for URL canonicalization, host allowlist, and URL helper functions.
"""
import pytest

from bheuu_scraper.crawler import (
    canonical_url,
    get_nested,
    is_allowed_host,
    is_document_url,
    make_absolute,
    resolve_file_url,
)


class TestCanonicalUrl:
    def test_forces_https(self):
        assert canonical_url("http://strapi.bheuu.gov.my/uploads/file.pdf").startswith(
            "https://"
        )

    def test_lowercases_host(self):
        result = canonical_url("https://STRAPI.BHEUU.GOV.MY/uploads/file.pdf")
        assert "strapi.bheuu.gov.my" in result

    def test_strips_fragment(self):
        result = canonical_url("https://strapi.bheuu.gov.my/uploads/file.pdf#page=1")
        assert "#" not in result

    def test_preserves_path(self):
        result = canonical_url("https://strapi.bheuu.gov.my/uploads/my_report.pdf")
        assert "/uploads/my_report.pdf" in result

    def test_preserves_query_string(self):
        result = canonical_url("https://strapi.bheuu.gov.my/media-statements?_limit=10")
        assert "_limit=10" in result

    def test_already_canonical(self):
        url = "https://strapi.bheuu.gov.my/uploads/report.pdf"
        assert canonical_url(url) == url

    def test_www_variant(self):
        result = canonical_url("https://www.bheuu.gov.my/en")
        assert "www.bheuu.gov.my" in result


class TestIsAllowedHost:
    allowed = frozenset({"www.bheuu.gov.my", "strapi.bheuu.gov.my"})

    def test_www_host_allowed(self):
        assert is_allowed_host("https://www.bheuu.gov.my/en", self.allowed)

    def test_strapi_host_allowed(self):
        assert is_allowed_host(
            "https://strapi.bheuu.gov.my/uploads/file.pdf", self.allowed
        )

    def test_external_host_rejected(self):
        assert not is_allowed_host("https://example.com/page", self.allowed)

    def test_similar_host_rejected(self):
        assert not is_allowed_host("https://bheuu.gov.my.evil.com/page", self.allowed)

    def test_subdomain_rejected(self):
        assert not is_allowed_host("https://sub.bheuu.gov.my/page", self.allowed)

    def test_http_strapi_allowed(self):
        # host check is scheme-independent
        assert is_allowed_host("http://strapi.bheuu.gov.my/uploads/f.pdf", self.allowed)


class TestMakeAbsolute:
    def test_relative_path(self):
        result = make_absolute("/uploads/file.pdf", "https://strapi.bheuu.gov.my")
        assert result == "https://strapi.bheuu.gov.my/uploads/file.pdf"

    def test_absolute_url_unchanged(self):
        abs_url = "https://strapi.bheuu.gov.my/uploads/LAPORAN_2022.pdf"
        result = make_absolute(abs_url, "https://strapi.bheuu.gov.my")
        assert result == abs_url

    def test_http_absolute_unchanged(self):
        abs_url = "http://strapi.bheuu.gov.my/uploads/file.pdf"
        assert make_absolute(abs_url, "https://strapi.bheuu.gov.my") == abs_url


class TestResolveFileUrl:
    def test_relative_resolved(self):
        result = resolve_file_url("/uploads/file.pdf", "https://strapi.bheuu.gov.my")
        assert result == "https://strapi.bheuu.gov.my/uploads/file.pdf"

    def test_absolute_unchanged(self):
        url = "https://strapi.bheuu.gov.my/uploads/file.pdf"
        assert resolve_file_url(url, "https://strapi.bheuu.gov.my") == url

    def test_empty_returns_empty(self):
        assert resolve_file_url("", "https://strapi.bheuu.gov.my") == ""

    def test_none_returns_empty(self):
        assert resolve_file_url(None, "https://strapi.bheuu.gov.my") == ""


class TestIsDocumentUrl:
    def test_pdf_is_doc(self):
        assert is_document_url("https://strapi.bheuu.gov.my/uploads/report.pdf")

    def test_docx_is_doc(self):
        assert is_document_url("https://strapi.bheuu.gov.my/uploads/form.docx")

    def test_xlsx_is_doc(self):
        assert is_document_url("https://strapi.bheuu.gov.my/uploads/data.xlsx")

    def test_html_is_not_doc(self):
        assert not is_document_url("https://www.bheuu.gov.my/en/media-statements")


class TestGetNested:
    def test_single_key(self):
        assert get_nested({"url": "https://example.com/file.pdf"}, "url") == \
            "https://example.com/file.pdf"

    def test_dotted_key(self):
        data = {"fileName": {"url": "/uploads/file.pdf"}}
        assert get_nested(data, "fileName.url") == "/uploads/file.pdf"

    def test_deeply_nested(self):
        data = {"a": {"b": {"c": "value"}}}
        assert get_nested(data, "a.b.c") == "value"

    def test_missing_key_returns_none(self):
        assert get_nested({"title": "test"}, "fileName.url") is None

    def test_non_dict_intermediate_returns_none(self):
        assert get_nested({"fileName": "not-a-dict"}, "fileName.url") is None

    def test_none_leaf_returns_none(self):
        assert get_nested({"url": None}, "url") is None
