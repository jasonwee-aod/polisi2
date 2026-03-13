"""Tests for URL canonicalization and host allowlist."""
import pytest

from kpkt_scraper.crawler import canonical_url, is_allowed_host, make_absolute


# ── canonical_url ─────────────────────────────────────────────────────────────


def test_canonical_upgrades_http_to_https():
    assert canonical_url("http://www.kpkt.gov.my/page") == "https://www.kpkt.gov.my/page"


def test_canonical_lowercases_host():
    result = canonical_url("https://WWW.KPKT.GOV.MY/page")
    assert result.startswith("https://www.kpkt.gov.my")


def test_canonical_strips_fragment():
    result = canonical_url("https://www.kpkt.gov.my/page#section")
    assert "#" not in result


def test_canonical_preserves_query_string():
    url = "https://www.kpkt.gov.my/index.php/pages/view/3470?mid=764"
    result = canonical_url(url)
    assert "mid=764" in result


def test_canonical_preserves_path():
    result = canonical_url("https://www.kpkt.gov.my/kpkt/resources/doc.pdf")
    assert "/kpkt/resources/doc.pdf" in result


def test_canonical_idempotent():
    url = "https://www.kpkt.gov.my/index.php/pages/view/3470?mid=764"
    assert canonical_url(canonical_url(url)) == canonical_url(url)


# ── is_allowed_host ───────────────────────────────────────────────────────────


def test_allowed_host_with_www():
    assert is_allowed_host("https://www.kpkt.gov.my/page")


def test_allowed_host_without_www():
    assert is_allowed_host("https://kpkt.gov.my/page")


def test_disallowed_external_host():
    assert not is_allowed_host("https://example.com/page")


def test_disallowed_similar_domain():
    assert not is_allowed_host("https://fake-kpkt.gov.my/page")


def test_disallowed_subdomain():
    # Only the two explicitly listed hosts are allowed
    assert not is_allowed_host("https://portal.kpkt.gov.my/page")


def test_allowed_host_custom_allowlist():
    custom = {"portal.example.gov"}
    assert is_allowed_host("https://portal.example.gov/page", custom)
    assert not is_allowed_host("https://www.kpkt.gov.my/page", custom)


# ── make_absolute ─────────────────────────────────────────────────────────────


def test_make_absolute_relative_path():
    result = make_absolute(
        "/kpkt/resources/doc.pdf",
        "https://www.kpkt.gov.my",
    )
    assert result == "https://www.kpkt.gov.my/kpkt/resources/doc.pdf"


def test_make_absolute_already_absolute():
    url = "https://www.kpkt.gov.my/kpkt/resources/doc.pdf"
    assert make_absolute(url, "https://www.kpkt.gov.my") == url


def test_make_absolute_relative_no_leading_slash():
    result = make_absolute(
        "resources/doc.pdf",
        "https://www.kpkt.gov.my/base/",
    )
    assert result == "https://www.kpkt.gov.my/base/resources/doc.pdf"
