"""Tests for the Downloads Hub and Container Attachments extractors."""
import binascii
import base64
from pathlib import Path

import pytest

from kpkt_scraper.extractor import (
    extract_container_attachments,
    extract_downloads_hub,
    is_dl_url,
    resolve_dl_url,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "https://www.kpkt.gov.my"
SOURCE_URL = "https://www.kpkt.gov.my/index.php/pages/view/88"


# ── resolve_dl_url ────────────────────────────────────────────────────────────


def _make_dl_href(path_suffix: str) -> str:
    """Helper: encode a path suffix the same way the KPKT site does."""
    b64 = base64.b64encode(path_suffix.encode("utf-8"))
    hex_str = binascii.hexlify(b64).decode("ascii")
    return f"/index.php/dl/{hex_str}"


def test_resolve_dl_url_known_act118():
    """Decode the Act 118 hex string confirmed from the live site."""
    href = "/index.php/dl/64584e6c636c38784c303146546b6446546b464a49457451533151765155745551533942613352684d544534655445354e6a5a69625335775a47593d"
    result = resolve_dl_url(href)
    # Should resolve to a kpkt.gov.my resource URL
    assert result.startswith("https://www.kpkt.gov.my/kpkt/resources/")
    assert result.endswith(".pdf")


def test_resolve_dl_url_roundtrip():
    """Encode a known path and verify decode inverts it."""
    path = "user_1/MENGENAI KPKT/AKTA/TestAkta.pdf"
    href = _make_dl_href(path)
    result = resolve_dl_url(href)
    assert result == f"https://www.kpkt.gov.my/kpkt/resources/{path}"


def test_resolve_dl_url_non_dl_href_unchanged():
    href = "/kpkt/resources/user_1/MENGENAI KPKT/AKTA/doc.pdf"
    assert resolve_dl_url(href) == href


def test_resolve_dl_url_invalid_hex_returns_original():
    href = "/index.php/dl/NOTVALIDHEX!!"
    assert resolve_dl_url(href) == href


# ── is_dl_url ─────────────────────────────────────────────────────────────────


def test_is_dl_url_true():
    assert is_dl_url("/index.php/dl/64584e6c")


def test_is_dl_url_false_direct():
    assert not is_dl_url("/kpkt/resources/user_1/doc.pdf")


def test_is_dl_url_false_pages():
    assert not is_dl_url("/index.php/pages/view/88")


# ── extract_downloads_hub ─────────────────────────────────────────────────────


def test_hub_returns_five_sub_pages():
    html = (FIXTURES / "downloads_hub.html").read_text(encoding="utf-8")
    urls = extract_downloads_hub(html, "https://www.kpkt.gov.my/index.php/pages/view/1026", BASE_URL)
    assert len(urls) == 5


def test_hub_urls_are_absolute():
    html = (FIXTURES / "downloads_hub.html").read_text(encoding="utf-8")
    urls = extract_downloads_hub(html, "https://www.kpkt.gov.my/index.php/pages/view/1026", BASE_URL)
    for url in urls:
        assert url.startswith("https://"), f"Expected absolute URL: {url}"


def test_hub_contains_expected_sub_pages():
    html = (FIXTURES / "downloads_hub.html").read_text(encoding="utf-8")
    urls = extract_downloads_hub(html, "https://www.kpkt.gov.my/index.php/pages/view/1026", BASE_URL)
    url_set = set(urls)
    assert "https://www.kpkt.gov.my/index.php/pages/view/88" in url_set
    assert "https://www.kpkt.gov.my/index.php/pages/view/326" in url_set
    assert "https://www.kpkt.gov.my/index.php/pages/view/425" in url_set


def test_hub_no_duplicate_urls():
    html = (FIXTURES / "downloads_hub.html").read_text(encoding="utf-8")
    urls = extract_downloads_hub(html, "https://www.kpkt.gov.my/index.php/pages/view/1026", BASE_URL)
    assert len(urls) == len(set(urls))


def test_hub_empty_accordion_returns_empty():
    html = "<html><body><p>No accordion</p></body></html>"
    urls = extract_downloads_hub(html, BASE_URL + "/test", BASE_URL)
    assert urls == []


# ── extract_container_attachments ─────────────────────────────────────────────


def test_attachments_item_count():
    html = (FIXTURES / "container_attachments.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_URL, BASE_URL, "legislation")
    assert len(items) == 3


def test_attachments_direct_link_preserved():
    html = (FIXTURES / "container_attachments.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_URL, BASE_URL, "legislation")
    direct_hrefs = [i["href"] for i in items if "CADANGAN_PINDAAN" in i["href"]]
    assert len(direct_hrefs) == 1
    assert direct_hrefs[0].startswith("https://www.kpkt.gov.my/kpkt/resources/")


def test_attachments_dl_link_resolved():
    html = (FIXTURES / "container_attachments.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_URL, BASE_URL, "legislation")
    # The obfuscated dl/ link should resolve to a full kpkt.gov.my resource URL
    resolved_hrefs = [
        i["href"] for i in items
        if i["href"].startswith("https://www.kpkt.gov.my/kpkt/resources/")
        and "Akta" in i["href"]
    ]
    assert len(resolved_hrefs) >= 1


def test_attachments_no_dl_hrefs_in_output():
    """No /index.php/dl/ links should appear in output — all must be resolved."""
    html = (FIXTURES / "container_attachments.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_URL, BASE_URL, "legislation")
    for item in items:
        assert "/index.php/dl/" not in item["href"], (
            f"Unresolved dl/ href found: {item['href']}"
        )


def test_attachments_doc_type_preserved():
    html = (FIXTURES / "container_attachments.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_URL, BASE_URL, "legislation")
    for item in items:
        assert item["doc_type"] == "legislation"


def test_attachments_source_url_preserved():
    html = (FIXTURES / "container_attachments.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_URL, BASE_URL, "form")
    for item in items:
        assert item["source_url"] == SOURCE_URL


def test_attachments_no_duplicate_hrefs():
    html = (FIXTURES / "container_attachments.html").read_text(encoding="utf-8")
    items = extract_container_attachments(html, SOURCE_URL, BASE_URL, "legislation")
    hrefs = [i["href"] for i in items]
    assert len(hrefs) == len(set(hrefs))
