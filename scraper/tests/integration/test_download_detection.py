"""Integration tests — "Muat Turun" regression suite.

Parametrized tests with inline HTML fixtures covering all 14 known download
patterns seen across Malaysian government sites.
"""

from __future__ import annotations

import pytest

from polisi_scraper.core.extractors import DownloadLink, extract_document_links

BASE = "https://www.example.gov.my/page"

# ---- Hex-encoded fixture for KPKT pattern 4 ----
# path = "pdf/garis_panduan/gp_sample.pdf"
# base64 -> hex: 6347526d4c326468636d6c7a58334268626d5231595734765a334266633246746347786c4c6e426b5a673d3d
KPKT_HEX = "6347526d4c326468636d6c7a58334268626d5231595734765a334266633246746347786c4c6e426b5a673d3d"
KPKT_BASE = "https://www.kpkt.gov.my/page"


# ---------------------------------------------------------------------------
# Pattern 1: Direct <a href="file.pdf"> link
# ---------------------------------------------------------------------------

HTML_PATTERN_1 = """
<html><body>
  <a href="/uploads/reports/annual_2024.pdf">Laporan Tahunan 2024</a>
</body></html>
"""


def test_pattern_01_direct_pdf_link() -> None:
    links = extract_document_links(HTML_PATTERN_1, BASE)
    assert len(links) == 1
    assert links[0].url == "https://www.example.gov.my/uploads/reports/annual_2024.pdf"


# ---------------------------------------------------------------------------
# Pattern 2: <a> with Malay label "Muat Turun"
# ---------------------------------------------------------------------------

HTML_PATTERN_2 = """
<html><body>
  <a href="/download/circular-123">Muat Turun</a>
</body></html>
"""


def test_pattern_02_muat_turun_label() -> None:
    links = extract_document_links(HTML_PATTERN_2, BASE)
    assert len(links) == 1
    assert links[0].label == "Muat Turun"
    assert "circular-123" in links[0].url


# ---------------------------------------------------------------------------
# Pattern 3: WPDM redirect token (?wpdmdl=N&ind=N)
# ---------------------------------------------------------------------------

HTML_PATTERN_3 = """
<html><body>
  <a href="/docs/report.pdf?wpdmdl=456&ind=1">Download PDF</a>
</body></html>
"""


def test_pattern_03_wpdm_redirect_token() -> None:
    links = extract_document_links(HTML_PATTERN_3, BASE)
    assert len(links) == 1
    assert "wpdmdl=456" in links[0].url
    assert links[0].url.endswith(".pdf?wpdmdl=456&ind=1")


# ---------------------------------------------------------------------------
# Pattern 4: Hex-obfuscated /index.php/dl/<HEX> (KPKT)
# Uses KPKT adapter's extract_downloads() rather than the generic extractor.
# ---------------------------------------------------------------------------

HTML_PATTERN_4 = f"""
<html><body>
  <a href="/index.php/dl/{KPKT_HEX}">Garis Panduan</a>
</body></html>
"""


def test_pattern_04_kpkt_hex_obfuscated() -> None:
    from polisi_scraper.adapters.kpkt import KpktAdapter

    adapter = KpktAdapter(config={})
    links = adapter.extract_downloads(HTML_PATTERN_4, KPKT_BASE)
    assert len(links) >= 1
    # The resolved URL should contain the decoded path
    resolved_urls = [dl.url for dl in links]
    assert any("gp_sample.pdf" in url for url in resolved_urls), (
        f"Expected decoded PDF path in {resolved_urls}"
    )


# ---------------------------------------------------------------------------
# Pattern 5: ASP.NET /getattachment/UUID/file.aspx redirect (MCMC)
# ---------------------------------------------------------------------------

HTML_PATTERN_5 = """
<html><body>
  <a href="/getattachment/a1b2c3d4-e5f6-7890-abcd-ef1234567890/guideline.aspx">
    MCMC Guideline
  </a>
</body></html>
"""


def test_pattern_05_getattachment_aspnet() -> None:
    links = extract_document_links(HTML_PATTERN_5, BASE)
    assert len(links) == 1
    assert "/getattachment/" in links[0].url


# ---------------------------------------------------------------------------
# Pattern 6: DOCman /file endpoint (MOHE)
# ---------------------------------------------------------------------------

HTML_PATTERN_6 = """
<html><body>
  <a href="/component/docman/file/42-annual-report-2024">Laporan Tahunan</a>
</body></html>
"""


def test_pattern_06_docman_file_endpoint() -> None:
    links = extract_document_links(HTML_PATTERN_6, BASE)
    assert len(links) == 1
    assert "/file" in links[0].url


# ---------------------------------------------------------------------------
# Pattern 7: pdfjs-viewer <iframe> with encoded PDF URL
# ---------------------------------------------------------------------------

HTML_PATTERN_7 = """
<html><body>
  <iframe src="/pdfjs/web/viewer.html?file=%2Fuploads%2Fpolicies%2Fpolicy_2024.pdf"></iframe>
</body></html>
"""


def test_pattern_07_pdfjs_viewer_iframe() -> None:
    links = extract_document_links(HTML_PATTERN_7, BASE)
    assert len(links) == 1
    assert links[0].url == "https://www.example.gov.my/uploads/policies/policy_2024.pdf"
    assert links[0].label == "pdfjs-viewer embed"


# ---------------------------------------------------------------------------
# Pattern 8: PDF link inside jQuery accordion
# ---------------------------------------------------------------------------

HTML_PATTERN_8 = """
<html><body>
  <div id="accordion">
    <h3>Siaran Media 2024</h3>
    <div>
      <p><a href="/media/press_release_jan.pdf">Siaran Media Januari 2024</a></p>
      <p><a href="/media/press_release_feb.pdf">Siaran Media Februari 2024</a></p>
    </div>
    <h3>Siaran Media 2023</h3>
    <div>
      <p><a href="/media/press_release_dec_2023.pdf">Siaran Media Disember 2023</a></p>
    </div>
  </div>
</body></html>
"""


def test_pattern_08_jquery_accordion() -> None:
    links = extract_document_links(HTML_PATTERN_8, BASE)
    assert len(links) == 3
    urls = {dl.url for dl in links}
    assert "https://www.example.gov.my/media/press_release_jan.pdf" in urls
    assert "https://www.example.gov.my/media/press_release_feb.pdf" in urls
    assert "https://www.example.gov.my/media/press_release_dec_2023.pdf" in urls


# ---------------------------------------------------------------------------
# Pattern 9: PDF link inside DataTables table
# ---------------------------------------------------------------------------

HTML_PATTERN_9 = """
<html><body>
  <table class="dataTable">
    <thead><tr><th>Tarikh</th><th>Tajuk</th><th>Muat Turun</th></tr></thead>
    <tbody>
      <tr>
        <td>2024-01-15</td>
        <td>Pekeliling Bil. 1</td>
        <td><a href="/circulars/pekeliling_1_2024.pdf">PDF</a></td>
      </tr>
      <tr>
        <td>2024-02-20</td>
        <td>Pekeliling Bil. 2</td>
        <td><a href="/circulars/pekeliling_2_2024.pdf">PDF</a></td>
      </tr>
    </tbody>
  </table>
</body></html>
"""


def test_pattern_09_datatable_pdf_links() -> None:
    links = extract_document_links(HTML_PATTERN_9, BASE)
    assert len(links) == 2
    urls = {dl.url for dl in links}
    assert "https://www.example.gov.my/circulars/pekeliling_1_2024.pdf" in urls
    assert "https://www.example.gov.my/circulars/pekeliling_2_2024.pdf" in urls


# ---------------------------------------------------------------------------
# Pattern 10: PDF link inside RadGrid table
# ---------------------------------------------------------------------------

HTML_PATTERN_10 = """
<html><body>
  <div class="RadGrid">
    <table>
      <tr class="rgRow">
        <td>Garis Panduan ICT</td>
        <td><a href="/guidelines/ict_guideline.pdf">Muat Turun</a></td>
      </tr>
      <tr class="rgAltRow">
        <td>Garis Panduan Keselamatan</td>
        <td><a href="/guidelines/security_guideline.pdf">Muat Turun</a></td>
      </tr>
    </table>
  </div>
</body></html>
"""


def test_pattern_10_radgrid_table() -> None:
    links = extract_document_links(HTML_PATTERN_10, BASE)
    assert len(links) == 2
    urls = {dl.url for dl in links}
    assert "https://www.example.gov.my/guidelines/ict_guideline.pdf" in urls
    assert "https://www.example.gov.my/guidelines/security_guideline.pdf" in urls


# ---------------------------------------------------------------------------
# Pattern 11: PDF link inside Divi accordion toggle
# ---------------------------------------------------------------------------

HTML_PATTERN_11 = """
<html><body>
  <div class="et_pb_accordion">
    <div class="et_pb_accordion_item">
      <div class="et_pb_toggle_title">Dasar Negara 2024</div>
      <div class="et_pb_toggle_content">
        <p><a href="/policies/dasar_negara_2024.pdf">Muat Turun PDF</a></p>
      </div>
    </div>
    <div class="et_pb_accordion_item">
      <div class="et_pb_toggle_title">Pelan Tindakan</div>
      <div class="et_pb_toggle_content">
        <p><a href="/policies/pelan_tindakan.pdf">Muat Turun PDF</a></p>
      </div>
    </div>
  </div>
</body></html>
"""


def test_pattern_11_divi_accordion() -> None:
    links = extract_document_links(HTML_PATTERN_11, BASE)
    assert len(links) == 2
    urls = {dl.url for dl in links}
    assert "https://www.example.gov.my/policies/dasar_negara_2024.pdf" in urls
    assert "https://www.example.gov.my/policies/pelan_tindakan.pdf" in urls


# ---------------------------------------------------------------------------
# Pattern 12: Link with "Download" text but href to HTML intermediary
# ---------------------------------------------------------------------------

HTML_PATTERN_12 = """
<html><body>
  <a href="/resources/intermediary-page.html">Download Laporan</a>
</body></html>
"""


def test_pattern_12_download_text_html_intermediary() -> None:
    links = extract_document_links(HTML_PATTERN_12, BASE)
    # The generic extractor captures links where text matches "download" keyword
    # even if the href points to HTML.  The .html link will be caught by
    # the keyword pattern, not the extension pattern.
    assert len(links) == 1
    assert links[0].url == "https://www.example.gov.my/resources/intermediary-page.html"
    assert "Download" in links[0].label


# ---------------------------------------------------------------------------
# Pattern 13: Multiple PDFs on single page
# ---------------------------------------------------------------------------

HTML_PATTERN_13 = """
<html><body>
  <ul>
    <li><a href="/docs/budget_2024.pdf">Bajet 2024</a></li>
    <li><a href="/docs/budget_2023.pdf">Bajet 2023</a></li>
    <li><a href="/docs/budget_2022.pdf">Bajet 2022</a></li>
    <li><a href="/docs/budget_2021.pdf">Bajet 2021</a></li>
    <li><a href="/docs/budget_2020.pdf">Bajet 2020</a></li>
  </ul>
</body></html>
"""


def test_pattern_13_multiple_pdfs_on_single_page() -> None:
    links = extract_document_links(HTML_PATTERN_13, BASE)
    assert len(links) == 5
    years = {"2024", "2023", "2022", "2021", "2020"}
    for dl in links:
        assert any(y in dl.url for y in years)


# ---------------------------------------------------------------------------
# Pattern 14: Zero-download page (should return empty)
# ---------------------------------------------------------------------------

HTML_PATTERN_14 = """
<html><body>
  <h1>Selamat Datang</h1>
  <p>Tiada dokumen untuk dimuat turun.</p>
  <a href="/about">Tentang Kami</a>
  <a href="/contact">Hubungi Kami</a>
  <a href="https://www.facebook.com/ministry">Facebook</a>
</body></html>
"""


def test_pattern_14_zero_download_page() -> None:
    links = extract_document_links(HTML_PATTERN_14, BASE)
    assert links == []


# ---------------------------------------------------------------------------
# Combined parametrized test for quick overview
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "html, base_url, min_count, description",
    [
        (HTML_PATTERN_1, BASE, 1, "direct PDF"),
        (HTML_PATTERN_2, BASE, 1, "Muat Turun keyword"),
        (HTML_PATTERN_3, BASE, 1, "WPDM redirect"),
        (HTML_PATTERN_5, BASE, 1, "getattachment ASP.NET"),
        (HTML_PATTERN_6, BASE, 1, "DOCman /file"),
        (HTML_PATTERN_7, BASE, 1, "pdfjs-viewer iframe"),
        (HTML_PATTERN_8, BASE, 3, "jQuery accordion"),
        (HTML_PATTERN_9, BASE, 2, "DataTables"),
        (HTML_PATTERN_10, BASE, 2, "RadGrid"),
        (HTML_PATTERN_11, BASE, 2, "Divi accordion"),
        (HTML_PATTERN_12, BASE, 1, "Download keyword HTML intermediary"),
        (HTML_PATTERN_13, BASE, 5, "multiple PDFs"),
        (HTML_PATTERN_14, BASE, 0, "zero-download page"),
    ],
    ids=[
        "P01-direct-pdf",
        "P02-muat-turun",
        "P03-wpdm",
        "P05-getattachment",
        "P06-docman",
        "P07-pdfjs",
        "P08-accordion",
        "P09-datatable",
        "P10-radgrid",
        "P11-divi",
        "P12-intermediary",
        "P13-multi-pdf",
        "P14-zero",
    ],
)
def test_generic_extractor_parametrized(
    html: str, base_url: str, min_count: int, description: str
) -> None:
    links = extract_document_links(html, base_url)
    assert len(links) >= min_count, (
        f"Pattern '{description}' expected >= {min_count} links, got {len(links)}"
    )
