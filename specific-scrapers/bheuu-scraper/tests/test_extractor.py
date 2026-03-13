"""
Tests for Strapi record extraction functions.

Uses fixture JSON files (saved from live API responses) to verify that
all field extraction paths work correctly for each section type.
"""
import json
from pathlib import Path

import pytest

from bheuu_scraper.extractor import (
    extract_date,
    extract_file_url,
    extract_record_id,
    extract_title,
    guess_content_type,
    resolve_file_url,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


# ── media-statements ──────────────────────────────────────────────────────────


class TestMediaStatement:
    def setup_method(self):
        self.rec = _load("media_statement.json")

    def test_title(self):
        title = extract_title(self.rec, "title")
        assert "EKSPLOITASI" in title

    def test_date(self):
        date = extract_date(self.rec, "publishDate")
        assert date == "2024-01-08"

    def test_file_url_relative_resolved(self):
        raw = extract_file_url(self.rec, "fileName.url")
        url = resolve_file_url(raw)
        assert url.startswith("https://strapi.bheuu.gov.my/uploads/")
        assert url.endswith(".pdf")

    def test_record_id(self):
        assert extract_record_id(self.rec) == "66bc14de7a0fc311fd365271"


# ── annual-reports ────────────────────────────────────────────────────────────


class TestAnnualReport:
    def setup_method(self):
        self.rec = _load("annual_report.json")

    def test_title(self):
        assert "Laporan Tahunan" in extract_title(self.rec, "title")

    def test_date_falls_back_to_createdAt(self):
        # date_field "createdAt" → ISO datetime → date
        date = extract_date(self.rec, "createdAt")
        assert date == "2024-07-19"

    def test_file_url_absolute_preserved(self):
        raw = extract_file_url(self.rec, "url")
        url = resolve_file_url(raw)
        assert url == "https://strapi.bheuu.gov.my/uploads/LAPORAN_TAHUNAN_2022_abc123.pdf"

    def test_record_id(self):
        assert extract_record_id(self.rec) == "6699d5d120e8ca067240bd63"


# ── act-protection-newspaper-clip (single-type, no title) ────────────────────


class TestNewspaperClip:
    def setup_method(self):
        self.rec = _load("newspaper_clip.json")

    def test_pdfFile_url_resolved(self):
        raw = extract_file_url(self.rec, "pdfFile.url")
        url = resolve_file_url(raw)
        assert url.startswith("https://strapi.bheuu.gov.my/uploads/")

    def test_date_falls_back_to_createdAt(self):
        date = extract_date(self.rec, "createdAt")
        assert date == "2024-07-26"

    def test_title_empty_field(self):
        # no title field in fixture → returns ""
        title = extract_title(self.rec, "title")
        assert isinstance(title, str)


# ── act-protection-archives (year as title + date) ────────────────────────────


class TestActArchive:
    def setup_method(self):
        self.rec = _load("act_archive.json")

    def test_year_as_title(self):
        title = extract_title(self.rec, "year")
        assert title == "2010"

    def test_year_as_date(self):
        date = extract_date(self.rec, "year")
        assert date == "2010-01-01"

    def test_pdfFile_url(self):
        raw = extract_file_url(self.rec, "pdfFile.url")
        url = resolve_file_url(raw)
        assert url.endswith(".pdf")


# ── guess_content_type ────────────────────────────────────────────────────────


class TestGuessContentType:
    def test_pdf(self):
        assert guess_content_type("/uploads/report.pdf") == "application/pdf"

    def test_docx(self):
        assert (
            guess_content_type("/uploads/form.docx")
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    def test_xlsx(self):
        assert (
            guess_content_type("/uploads/data.xlsx")
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    def test_unknown_defaults_to_pdf(self):
        assert guess_content_type("https://example.com/file") == "application/pdf"

    def test_case_insensitive(self):
        assert guess_content_type("/uploads/REPORT.PDF") == "application/pdf"


# ── resolve_file_url ──────────────────────────────────────────────────────────


class TestResolveFileUrl:
    def test_relative_gets_strapi_base(self):
        result = resolve_file_url("/uploads/file.pdf")
        assert result == "https://strapi.bheuu.gov.my/uploads/file.pdf"

    def test_absolute_unchanged(self):
        url = "https://strapi.bheuu.gov.my/uploads/file.pdf"
        assert resolve_file_url(url) == url

    def test_empty_returns_empty(self):
        assert resolve_file_url("") == ""

    def test_none_returns_empty(self):
        assert resolve_file_url(None) == ""

    def test_url_with_spaces_resolved(self):
        """Strapi sometimes stores URLs with spaces (URL-encode issue)."""
        raw = "/uploads/LAPORAN TAHUNAN 2022.pdf"
        result = resolve_file_url(raw)
        assert result.startswith("https://strapi.bheuu.gov.my/uploads/")


# ── act-laws (titleEN/titleBM, optional pdf.url) ──────────────────────────────


class TestActLaw:
    def test_title_from_titleEN(self):
        rec = {
            "titleEN": "Trustees (Incorporation) Act 1952 [Act 258]",
            "titleBM": "Akta Pemegang Amanah (Pemerbadanan) 1952 [Akta 258]",
        }
        assert extract_title(rec, "titleEN") == "Trustees (Incorporation) Act 1952 [Act 258]"

    def test_file_url_nested_pdf(self):
        import json
        from pathlib import Path
        rec = json.loads((Path(__file__).parent / "fixtures" / "act_law_with_pdf.json").read_text())
        raw = extract_file_url(rec, "pdf.url")
        assert raw.startswith("https://strapi.bheuu.gov.my/uploads/")
        assert raw.endswith(".pdf")

    def test_no_pdf_field_returns_empty(self):
        import json
        from pathlib import Path
        rec = json.loads((Path(__file__).parent / "fixtures" / "act_law_nav_only.json").read_text())
        raw = extract_file_url(rec, "pdf.url")
        assert raw == ""

    def test_date_from_createdAt(self):
        rec = {"createdAt": "2024-08-05T03:58:48.468Z"}
        assert extract_date(rec, "createdAt") == "2024-08-05"
