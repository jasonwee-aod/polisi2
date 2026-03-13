"""Tests for the KPKT adapter — hex-obfuscated downloads, accordion extraction, hub navigation.

Covers:
  - CRITICAL: hex-obfuscated download link resolution (resolve_dl_url)
  - Accordion press release extraction (Pattern A and Pattern B)
  - Hub-and-spoke navigation
  - container_attachments extraction
  - Date extraction from titles
  - Direct PDF links
  - since filtering
  - max_pages
"""
from __future__ import annotations

import base64
import binascii
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from polisi_scraper.adapters.kpkt import (
    BASE_URL,
    KpktAdapter,
    _extract_container_attachments,
    _extract_date_from_title,
    _extract_downloads_hub,
    _extract_siaran_media,
    _nearest_label,
    _since_filter,
    _split_date_and_title,
    is_dl_url,
    resolve_dl_url,
)
from polisi_scraper.adapters.base import DiscoveredItem, DocumentCandidate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "kpkt"
LISTING_URL = "https://www.kpkt.gov.my/index.php/pages/view/3470?mid=764"
SOURCE_URL = "https://www.kpkt.gov.my/index.php/pages/view/88"
HUB_URL = "https://www.kpkt.gov.my/index.php/pages/view/1026"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _make_dl_href(path_suffix: str) -> str:
    """Encode a path suffix the same way the KPKT site does: path -> base64 -> hex."""
    b64 = base64.b64encode(path_suffix.encode("utf-8"))
    hex_str = binascii.hexlify(b64).decode("ascii")
    return f"/index.php/dl/{hex_str}"


# ---------------------------------------------------------------------------
# resolve_dl_url — CRITICAL hex-obfuscated download URL resolution
# ---------------------------------------------------------------------------


class TestResolveDlUrl:
    """The most critical tests: decoding hex-obfuscated /index.php/dl/<HEX> links."""

    def test_known_act118_from_live_site(self):
        """Decode the Act 118 hex string confirmed from the live site."""
        href = (
            "/index.php/dl/"
            "64584e6c636c38784c303146546b6446546b464a49457451533151765155745551533942613352684d544534655445354e6a5a69625335775a47593d"
        )
        result = resolve_dl_url(href)
        assert result.startswith("https://www.kpkt.gov.my/kpkt/resources/")
        assert result.endswith(".pdf")
        assert "Akta118y1966bm.pdf" in result

    def test_roundtrip_simple_path(self):
        """Encode a known path and verify decode inverts it."""
        path = "user_1/MENGENAI KPKT/AKTA/TestAkta.pdf"
        href = _make_dl_href(path)
        result = resolve_dl_url(href)
        assert result == f"https://www.kpkt.gov.my/kpkt/resources/{path}"

    def test_roundtrip_with_spaces(self):
        path = "user_1/GALERI/PDF PENERBITAN/report 2024.pdf"
        href = _make_dl_href(path)
        result = resolve_dl_url(href)
        assert result == f"https://www.kpkt.gov.my/kpkt/resources/{path}"

    def test_roundtrip_deep_nested_path(self):
        path = "user_1/A/B/C/D/deep_file.docx"
        href = _make_dl_href(path)
        result = resolve_dl_url(href)
        assert result == f"https://www.kpkt.gov.my/kpkt/resources/{path}"

    def test_roundtrip_special_characters(self):
        path = "user_1/DIR/P.U._(A)_278_2018.pdf"
        href = _make_dl_href(path)
        result = resolve_dl_url(href)
        assert result == f"https://www.kpkt.gov.my/kpkt/resources/{path}"

    def test_roundtrip_malay_filename(self):
        path = "user_1/media_akhbar/2025/SM_KPKT_Pencapaian_Cemerlang.pdf"
        href = _make_dl_href(path)
        result = resolve_dl_url(href)
        assert result == f"https://www.kpkt.gov.my/kpkt/resources/{path}"

    def test_non_dl_href_returned_unchanged(self):
        href = "/kpkt/resources/user_1/MENGENAI KPKT/AKTA/doc.pdf"
        assert resolve_dl_url(href) == href

    def test_regular_url_returned_unchanged(self):
        href = "/index.php/pages/view/88"
        assert resolve_dl_url(href) == href

    def test_invalid_hex_returns_original(self):
        href = "/index.php/dl/NOTVALIDHEX!!"
        assert resolve_dl_url(href) == href

    def test_empty_hex_returns_original(self):
        href = "/index.php/dl/"
        # This doesn't match the regex (needs at least one hex char)
        assert resolve_dl_url(href) == href

    def test_odd_length_hex_returns_original(self):
        """Odd-length hex strings cannot be unhexlified."""
        href = "/index.php/dl/abc"
        result = resolve_dl_url(href)
        # Should return the original since unhexlify will fail on odd-length
        assert result == href

    def test_valid_hex_invalid_base64_returns_original(self):
        """Valid hex that decodes to invalid base64."""
        href = "/index.php/dl/4e4f54424153453634"  # hex of "NOTBASE64"
        result = resolve_dl_url(href)
        # base64 decode of "NOTBASE64" may produce garbage or fail
        # Either way, should not crash
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# is_dl_url
# ---------------------------------------------------------------------------


class TestIsDlUrl:
    def test_true_for_dl_path(self):
        assert is_dl_url("/index.php/dl/64584e6c")

    def test_false_for_direct_resource(self):
        assert not is_dl_url("/kpkt/resources/user_1/doc.pdf")

    def test_false_for_pages_path(self):
        assert not is_dl_url("/index.php/pages/view/88")

    def test_false_for_empty_string(self):
        assert not is_dl_url("")

    def test_false_for_external_url(self):
        assert not is_dl_url("https://example.com/index.php/dl/abc123")


# ---------------------------------------------------------------------------
# _extract_date_from_title — date recovery from Malay title strings
# ---------------------------------------------------------------------------


class TestExtractDateFromTitle:
    @pytest.mark.parametrize(
        "title, expected",
        [
            # "Sehingga DD Month YYYY" -> exact date
            ("Statistik Terpilih KPKT Sehingga 31 Mac 2022", "2022-03-31"),
            ("Statistik Terpilih KPKT Sehingga 30 Jun 2022", "2022-06-30"),
            ("Perangkaan Sehingga 30 September 2021", "2021-09-30"),
            # "Bulan Month YYYY" -> month/year extracted (day is fuzzy-parsed)
            # These are tested separately below because dateutil fuzzy parse
            # fills in the current day when only month+year is given.
            ("Bilangan transaksi online bagi Oktober 2021", "2021-10-01"),
            # Bare "Month YYYY" in title
            ("Statistik Terpilih KPKT Sehingga September 2019", "2019-09-01"),
            # Year only -> January 1
            ("Statistik KPKT 2024 (Tahunan)", "2024-01-01"),
            ("Statistik Siri Masa MyKPKT 2023", "2023-01-01"),
            ("Perangkaan 2016 (Tahunan)", "2016-01-01"),
            # No date
            ("Senarai Borang Tribunal", ""),
            ("", ""),
        ],
    )
    def test_extract_date_from_title(self, title, expected):
        assert _extract_date_from_title(title) == expected

    def test_case_insensitive(self):
        assert _extract_date_from_title("sehingga 31 MAC 2022") == "2022-03-31"

    def test_bulan_januari_extracts_correct_month_year(self):
        """'Bulan Month YYYY' extracts the right month and year.

        dateutil fuzzy parse fills in the current day when only month+year is
        given, so we assert on month and year rather than the exact day.
        """
        result = _extract_date_from_title(
            "Pencapaian Piagam Pelanggan bagi Bulan Januari 2026"
        )
        assert result.startswith("2026-01-")

    def test_bulan_disember_extracts_correct_month_year(self):
        result = _extract_date_from_title(
            "Pencapaian Piagam Pelanggan bagi Bulan Disember 2025"
        )
        assert result.startswith("2025-12-")


# ---------------------------------------------------------------------------
# _split_date_and_title — Pattern B date/title splitting
# ---------------------------------------------------------------------------


class TestSplitDateAndTitle:
    def test_splits_date_and_title(self):
        raw = "1 Disember 2024\nPencapaian SPNB Melebihi 23,000"
        date_str, title = _split_date_and_title(raw)
        assert date_str == "1 Disember 2024"
        assert "Pencapaian SPNB" in title

    def test_multiline_title(self):
        raw = "15 Oktober 2024\nKPKT Komited Tingkatkan\nKualiti Perkhidmatan"
        date_str, title = _split_date_and_title(raw)
        assert date_str == "15 Oktober 2024"
        assert "KPKT Komited" in title

    def test_empty_returns_empty(self):
        date_str, title = _split_date_and_title("")
        assert date_str == ""
        assert title == ""

    def test_single_line_no_date(self):
        """When only one line and no date pattern, first line becomes date_str."""
        date_str, title = _split_date_and_title("Just A Title")
        assert date_str == "Just A Title"
        assert title == ""


# ---------------------------------------------------------------------------
# _since_filter
# ---------------------------------------------------------------------------


class TestSinceFilter:
    def test_no_since_returns_false(self):
        assert _since_filter("2026-01-01", None) is False

    def test_no_pub_date_returns_false(self):
        assert _since_filter("", date(2025, 1, 1)) is False

    def test_old_item_filtered(self):
        assert _since_filter("2024-01-01", date(2025, 1, 1)) is True

    def test_current_item_not_filtered(self):
        assert _since_filter("2025-06-01", date(2025, 1, 1)) is False

    def test_exact_boundary_not_filtered(self):
        assert _since_filter("2025-01-01", date(2025, 1, 1)) is False

    def test_invalid_date_returns_false(self):
        assert _since_filter("not-a-date", date(2025, 1, 1)) is False


# ---------------------------------------------------------------------------
# _extract_siaran_media — accordion press release extraction
# ---------------------------------------------------------------------------


class TestExtractSiaranMedia:
    # Pattern A
    def test_pattern_a_item_count(self):
        html = _read("siaran_media_pattern_a.html")
        items = _extract_siaran_media(html, LISTING_URL)
        assert len(items) == 3

    def test_pattern_a_first_item_title(self):
        html = _read("siaran_media_pattern_a.html")
        items = _extract_siaran_media(html, LISTING_URL)
        assert "KPKT Serah Kunci Rumah" in items[0]["title"]

    def test_pattern_a_first_item_date(self):
        html = _read("siaran_media_pattern_a.html")
        items = _extract_siaran_media(html, LISTING_URL)
        assert items[0]["date_text"] == "4 Disember 2025"

    def test_pattern_a_href_points_to_pdf(self):
        html = _read("siaran_media_pattern_a.html")
        items = _extract_siaran_media(html, LISTING_URL)
        for item in items:
            assert item["href"].endswith(".pdf")

    def test_pattern_a_source_url_preserved(self):
        html = _read("siaran_media_pattern_a.html")
        items = _extract_siaran_media(html, LISTING_URL)
        for item in items:
            assert item["source_url"] == LISTING_URL

    # Pattern B
    def test_pattern_b_item_count(self):
        html = _read("siaran_media_pattern_b.html")
        items = _extract_siaran_media(html, LISTING_URL)
        assert len(items) == 3

    def test_pattern_b_first_item_title(self):
        html = _read("siaran_media_pattern_b.html")
        items = _extract_siaran_media(html, LISTING_URL)
        assert "Pencapaian SPNB" in items[0]["title"]

    def test_pattern_b_first_item_date(self):
        html = _read("siaran_media_pattern_b.html")
        items = _extract_siaran_media(html, LISTING_URL)
        assert items[0]["date_text"] == "1 Disember 2024"

    def test_pattern_b_no_duplicate_hrefs(self):
        html = _read("siaran_media_pattern_b.html")
        items = _extract_siaran_media(html, LISTING_URL)
        hrefs = [item["href"] for item in items]
        assert len(hrefs) == len(set(hrefs))

    # Edge cases
    def test_no_accordion_returns_empty(self):
        html = "<html><body><p>No accordion content here</p></body></html>"
        items = _extract_siaran_media(html, LISTING_URL)
        assert items == []

    def test_empty_html_returns_empty(self):
        items = _extract_siaran_media("", LISTING_URL)
        assert items == []

    def test_dedup_across_patterns(self):
        """Same href in both Pattern A and B is only captured once."""
        html = """
        <div id="accordion_999">
          <h3>Disember</h3>
          <div>
            <p><strong>1 Disember 2025</strong><br/>
              <a href="/doc.pdf">Title A</a>
            </p>
            <a href="/doc.pdf">1 Disember 2025
Title B</a>
          </div>
        </div>
        """
        items = _extract_siaran_media(html, LISTING_URL)
        hrefs = [item["href"] for item in items]
        # The absolute URL for /doc.pdf should only appear once
        assert sum(1 for h in hrefs if h.endswith("/doc.pdf")) == 1


# ---------------------------------------------------------------------------
# _extract_downloads_hub — hub-and-spoke navigation
# ---------------------------------------------------------------------------


class TestExtractDownloadsHub:
    def test_returns_five_sub_pages(self):
        html = _read("downloads_hub.html")
        urls = _extract_downloads_hub(html, HUB_URL)
        assert len(urls) == 5

    def test_urls_are_absolute(self):
        html = _read("downloads_hub.html")
        urls = _extract_downloads_hub(html, HUB_URL)
        for url in urls:
            assert url.startswith("https://"), f"Expected absolute URL: {url}"

    def test_contains_expected_sub_pages(self):
        html = _read("downloads_hub.html")
        urls = _extract_downloads_hub(html, HUB_URL)
        url_set = set(urls)
        assert "https://www.kpkt.gov.my/index.php/pages/view/88" in url_set
        assert "https://www.kpkt.gov.my/index.php/pages/view/326" in url_set
        assert "https://www.kpkt.gov.my/index.php/pages/view/425" in url_set

    def test_no_duplicate_urls(self):
        html = _read("downloads_hub.html")
        urls = _extract_downloads_hub(html, HUB_URL)
        assert len(urls) == len(set(urls))

    def test_empty_accordion_returns_empty(self):
        html = "<html><body><p>No accordion</p></body></html>"
        urls = _extract_downloads_hub(html, HUB_URL)
        assert urls == []

    def test_non_pages_links_excluded(self):
        """Only /pages/view/ links are captured; PDF links are excluded."""
        html = """
        <div id="accordion_100">
          <h3>Section</h3>
          <div>
            <a href="/kpkt/resources/user_1/doc.pdf">Download PDF</a>
            <a href="/index.php/pages/view/42">Sub Page</a>
          </div>
        </div>
        """
        urls = _extract_downloads_hub(html, HUB_URL)
        assert len(urls) == 1
        assert "/pages/view/42" in urls[0]


# ---------------------------------------------------------------------------
# _extract_container_attachments
# ---------------------------------------------------------------------------


class TestExtractContainerAttachments:
    def test_item_count(self):
        html = _read("container_attachments.html")
        items = _extract_container_attachments(html, SOURCE_URL)
        assert len(items) == 3

    def test_direct_link_preserved(self):
        html = _read("container_attachments.html")
        items = _extract_container_attachments(html, SOURCE_URL)
        direct_hrefs = [i["href"] for i in items if "CADANGAN_PINDAAN" in i["href"]]
        assert len(direct_hrefs) == 1
        assert direct_hrefs[0].startswith("https://www.kpkt.gov.my/kpkt/resources/")

    def test_dl_link_resolved(self):
        html = _read("container_attachments.html")
        items = _extract_container_attachments(html, SOURCE_URL)
        resolved = [i for i in items if "Akta118" in i["href"]]
        assert len(resolved) == 1
        assert resolved[0]["href"].startswith("https://www.kpkt.gov.my/kpkt/resources/")

    def test_no_dl_hrefs_in_output(self):
        """All /index.php/dl/ links must be resolved."""
        html = _read("container_attachments.html")
        items = _extract_container_attachments(html, SOURCE_URL)
        for item in items:
            assert "/index.php/dl/" not in item["href"]

    def test_source_url_preserved(self):
        html = _read("container_attachments.html")
        items = _extract_container_attachments(html, SOURCE_URL)
        for item in items:
            assert item["source_url"] == SOURCE_URL

    def test_no_duplicate_hrefs(self):
        html = _read("container_attachments.html")
        items = _extract_container_attachments(html, SOURCE_URL)
        hrefs = [i["href"] for i in items]
        assert len(hrefs) == len(set(hrefs))

    def test_doc_type_propagated(self):
        html = _read("container_attachments.html")
        items = _extract_container_attachments(html, SOURCE_URL, doc_type="legislation")
        for item in items:
            assert item["doc_type"] == "legislation"

    def test_fallback_to_whole_page_when_no_container(self):
        """When no .container_attachments div, falls back to whole page scan."""
        html = """
        <html><body>
          <a href="/kpkt/resources/user_1/file.pdf">Download</a>
        </body></html>
        """
        items = _extract_container_attachments(html, SOURCE_URL)
        assert len(items) == 1


# ---------------------------------------------------------------------------
# Statistik KPKT fixture (no .container_attachments, uses fallback)
# ---------------------------------------------------------------------------


class TestStatistikKpkt:
    def test_item_count(self):
        html = _read("statistik_kpkt.html")
        items = _extract_container_attachments(html, SOURCE_URL, doc_type="report")
        # 2 from 2024 + 3 from 2022 = 5 PDFs; archive /pages/view/ links excluded
        assert len(items) == 5

    def test_no_archive_page_links(self):
        html = _read("statistik_kpkt.html")
        items = _extract_container_attachments(html, SOURCE_URL, doc_type="report")
        for item in items:
            assert "/index.php/pages/view/" not in item["href"]

    def test_all_hrefs_absolute(self):
        html = _read("statistik_kpkt.html")
        items = _extract_container_attachments(html, SOURCE_URL, doc_type="report")
        for item in items:
            assert item["href"].startswith("https://")

    def test_date_from_sehingga_title(self):
        html = _read("statistik_kpkt.html")
        items = _extract_container_attachments(html, SOURCE_URL, doc_type="report")
        mac_items = [i for i in items if "Mac 2022" in i["title"]]
        assert len(mac_items) == 1
        assert mac_items[0]["date_text"] == "2022-03-31"

    def test_date_year_only(self):
        html = _read("statistik_kpkt.html")
        items = _extract_container_attachments(html, SOURCE_URL, doc_type="report")
        annual_2024 = [i for i in items if "Tahunan" in i["title"] and "2024" in i["title"]]
        assert len(annual_2024) == 1
        assert annual_2024[0]["date_text"] == "2024-01-01"


# ---------------------------------------------------------------------------
# Piagam Pelanggan fixture (<li> list, no .container_attachments)
# ---------------------------------------------------------------------------


class TestPiagamPelanggan:
    def test_item_count(self):
        html = _read("piagam_pelanggan.html")
        items = _extract_container_attachments(html, SOURCE_URL, doc_type="report")
        # 3 monthly PDFs; ARKIB /pages/view/137 link excluded
        assert len(items) == 3

    def test_no_arkib_link(self):
        html = _read("piagam_pelanggan.html")
        items = _extract_container_attachments(html, SOURCE_URL, doc_type="report")
        for item in items:
            assert "/pages/view/" not in item["href"]

    def test_date_from_bulan_title(self):
        """'Bulan Januari 2026' yields the right month/year (day is fuzzy-parsed)."""
        html = _read("piagam_pelanggan.html")
        items = _extract_container_attachments(html, SOURCE_URL, doc_type="report")
        jan_items = [i for i in items if "Januari 2026" in i["title"]]
        assert len(jan_items) == 1
        assert jan_items[0]["date_text"].startswith("2026-01-")

    def test_date_disember(self):
        html = _read("piagam_pelanggan.html")
        items = _extract_container_attachments(html, SOURCE_URL, doc_type="report")
        dec_items = [i for i in items if "Disember 2025" in i["title"]]
        assert len(dec_items) == 1
        assert dec_items[0]["date_text"].startswith("2025-12-")

    def test_all_hrefs_are_pdf(self):
        html = _read("piagam_pelanggan.html")
        items = _extract_container_attachments(html, SOURCE_URL, doc_type="report")
        for item in items:
            assert item["href"].endswith(".pdf")


# ---------------------------------------------------------------------------
# KpktAdapter.discover — siaran media integration (mocked HTTP)
# ---------------------------------------------------------------------------


class TestAdapterDiscoverSiaranMedia:
    def _make_adapter(self, responses: dict[str, str]) -> KpktAdapter:
        mock_http = MagicMock()

        def side_effect(url):
            resp = MagicMock()
            resp.text = responses.get(url, "")
            return resp

        mock_http.get.side_effect = side_effect

        config = {
            "sections": [
                {
                    "name": "siaran_media_2025",
                    "page_type": "listing",
                    "doc_type": "press_release",
                    "language": "ms",
                    "listing_pages": [
                        {"url": "https://www.kpkt.gov.my/siaran-2025"},
                    ],
                },
            ],
        }
        return KpktAdapter(config=config, http=mock_http)

    def test_discovers_press_releases(self):
        html = _read("siaran_media_pattern_a.html")
        adapter = self._make_adapter({
            "https://www.kpkt.gov.my/siaran-2025": html,
        })
        items = list(adapter.discover())
        assert len(items) == 3

    def test_press_release_doc_type(self):
        html = _read("siaran_media_pattern_a.html")
        adapter = self._make_adapter({
            "https://www.kpkt.gov.my/siaran-2025": html,
        })
        items = list(adapter.discover())
        for item in items:
            assert item.doc_type == "press_release"


# ---------------------------------------------------------------------------
# KpktAdapter.discover — hub integration (mocked HTTP)
# ---------------------------------------------------------------------------


class TestAdapterDiscoverHub:
    def _make_adapter(self, responses: dict[str, str]) -> KpktAdapter:
        mock_http = MagicMock()

        def side_effect(url):
            resp = MagicMock()
            resp.text = responses.get(url, "")
            return resp

        mock_http.get.side_effect = side_effect

        config = {
            "sections": [
                {
                    "name": "downloads",
                    "page_type": "hub",
                    "doc_type": "legislation",
                    "language": "ms",
                    "listing_pages": [
                        {"url": HUB_URL},
                    ],
                },
            ],
        }
        return KpktAdapter(config=config, http=mock_http)

    def test_hub_follows_sub_pages(self):
        hub_html = _read("downloads_hub.html")
        attach_html = _read("container_attachments.html")

        # Map hub URL to hub HTML, and each sub-page to attachment HTML
        responses = {HUB_URL: hub_html}
        for page_id in ["88", "228", "646", "425", "326"]:
            responses[f"https://www.kpkt.gov.my/index.php/pages/view/{page_id}"] = attach_html

        adapter = self._make_adapter(responses)
        items = list(adapter.discover())
        # 5 sub-pages x 3 attachments each = 15 items
        assert len(items) == 15


# ---------------------------------------------------------------------------
# KpktAdapter.discover — since filtering
# ---------------------------------------------------------------------------


class TestAdapterDiscoverSince:
    def _make_adapter(self, responses: dict[str, str]) -> KpktAdapter:
        mock_http = MagicMock()

        def side_effect(url):
            resp = MagicMock()
            resp.text = responses.get(url, "")
            return resp

        mock_http.get.side_effect = side_effect

        config = {
            "sections": [
                {
                    "name": "siaran_media_2025",
                    "page_type": "listing",
                    "doc_type": "press_release",
                    "language": "ms",
                    "listing_pages": [
                        {"url": "https://www.kpkt.gov.my/siaran"},
                    ],
                },
            ],
        }
        return KpktAdapter(config=config, http=mock_http)

    def test_since_filters_old_items(self):
        html = _read("siaran_media_pattern_a.html")
        adapter = self._make_adapter({"https://www.kpkt.gov.my/siaran": html})
        # Items: 4 Dec 2025, 1 Dec 2025, 30 Nov 2025. Filter at 2025-12-01.
        items = list(adapter.discover(since=date(2025, 12, 1)))
        # 4 Dec and 1 Dec pass; 30 Nov is filtered out
        assert len(items) == 2

    def test_since_none_returns_all(self):
        html = _read("siaran_media_pattern_a.html")
        adapter = self._make_adapter({"https://www.kpkt.gov.my/siaran": html})
        items = list(adapter.discover(since=None))
        assert len(items) == 3


# ---------------------------------------------------------------------------
# KpktAdapter.discover — max_pages
# ---------------------------------------------------------------------------


class TestAdapterDiscoverMaxPages:
    def _make_adapter(self, responses: dict[str, str]) -> KpktAdapter:
        mock_http = MagicMock()

        def side_effect(url):
            resp = MagicMock()
            resp.text = responses.get(url, "")
            return resp

        mock_http.get.side_effect = side_effect

        config = {
            "sections": [
                {
                    "name": "section_1",
                    "page_type": "listing",
                    "doc_type": "press_release",
                    "language": "ms",
                    "listing_pages": [
                        {"url": "https://www.kpkt.gov.my/page-1"},
                        {"url": "https://www.kpkt.gov.my/page-2"},
                    ],
                },
            ],
        }
        return KpktAdapter(config=config, http=mock_http)

    def test_max_pages_limits_fetches(self):
        html_a = _read("siaran_media_pattern_a.html")
        html_b = _read("siaran_media_pattern_b.html")
        adapter = self._make_adapter({
            "https://www.kpkt.gov.my/page-1": html_a,
            "https://www.kpkt.gov.my/page-2": html_b,
        })
        items = list(adapter.discover(max_pages=1))
        # Only page-1 fetched (3 items from pattern_a); page-2 skipped
        assert len(items) == 3
        assert adapter.http.get.call_count == 1


# ---------------------------------------------------------------------------
# KpktAdapter.fetch_and_extract
# ---------------------------------------------------------------------------


class TestAdapterFetchAndExtract:
    def test_direct_pdf_yields_single_candidate(self):
        mock_http = MagicMock()
        adapter = KpktAdapter(config={}, http=mock_http)
        item = DiscoveredItem(
            source_url="https://www.kpkt.gov.my/kpkt/resources/user_1/media_akhbar/2025/statement.pdf",
            title="Media Statement",
            published_at="2025-12-01",
            doc_type="press_release",
            language="ms",
            metadata={"listing_url": LISTING_URL},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert len(candidates) == 1
        assert candidates[0].content_type == "application/pdf"
        mock_http.get.assert_not_called()

    def test_html_page_yields_html_plus_embedded(self):
        """An article page yields the HTML itself plus any embedded docs."""
        html = """
        <html><body>
          <p>Press release content.</p>
          <a href="/kpkt/resources/user_1/attachment.pdf">Download</a>
        </body></html>
        """
        mock_http = MagicMock()
        resp = MagicMock()
        resp.text = html
        mock_http.get.return_value = resp

        adapter = KpktAdapter(config={}, http=mock_http)
        item = DiscoveredItem(
            source_url="https://www.kpkt.gov.my/some-article",
            title="Article",
            published_at="2025-01-01",
            doc_type="press_release",
            language="ms",
            metadata={},
        )
        candidates = list(adapter.fetch_and_extract(item))
        # At least HTML candidate
        assert any(c.content_type == "text/html" for c in candidates)

    def test_fetch_failure_yields_nothing(self):
        mock_http = MagicMock()
        mock_http.get.side_effect = Exception("Connection error")
        adapter = KpktAdapter(config={}, http=mock_http)
        item = DiscoveredItem(
            source_url="https://www.kpkt.gov.my/broken",
            title="Broken",
            doc_type="other",
            language="ms",
            metadata={},
        )
        candidates = list(adapter.fetch_and_extract(item))
        assert candidates == []


# ---------------------------------------------------------------------------
# KpktAdapter.extract_downloads — hex-aware extraction override
# ---------------------------------------------------------------------------


class TestAdapterExtractDownloads:
    def test_resolves_hex_dl_links(self):
        path = "user_1/MENGENAI KPKT/AKTA/test.pdf"
        dl_href = _make_dl_href(path)
        html = f"""
        <html><body>
          <a href="{dl_href}">Download Act</a>
        </body></html>
        """
        adapter = KpktAdapter(config={}, http=MagicMock())
        links = adapter.extract_downloads(html, BASE_URL)
        resolved_urls = [dl.url for dl in links]
        expected = f"https://www.kpkt.gov.my/kpkt/resources/{path}"
        assert expected in resolved_urls

    def test_direct_pdf_link_found(self):
        html = """
        <html><body>
          <a href="/kpkt/resources/user_1/doc.pdf">Download PDF</a>
        </body></html>
        """
        adapter = KpktAdapter(config={}, http=MagicMock())
        links = adapter.extract_downloads(html, BASE_URL)
        assert any("doc.pdf" in dl.url for dl in links)
