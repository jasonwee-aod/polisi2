"""Tests for language detection, clarification check, and agency extraction."""

from polisi_api.chat.detector import detect_language, extract_agency, needs_clarification


def test_detect_language_ms() -> None:
    assert detect_language("Apakah bantuan pendidikan untuk pelajar IPT?") == "ms"


def test_detect_language_en() -> None:
    assert detect_language("What childcare subsidies are available?") == "en"


def test_needs_clarification_broad() -> None:
    assert needs_clarification("Tell me about education policy") is True


def test_needs_clarification_specific() -> None:
    assert needs_clarification("What is BR1M eligibility criteria?") is False


def test_needs_clarification_single_word() -> None:
    assert needs_clarification("policy") is True


# --- Agency extraction tests ---

def test_extract_agency_abbreviation() -> None:
    assert extract_agency("What policies does KPM have?") == "KPM"


def test_extract_agency_english_name() -> None:
    assert extract_agency("Ministry of Education subsidies") == "KPM"


def test_extract_agency_malay_name() -> None:
    assert extract_agency("Dasar Kementerian Pendidikan Malaysia") == "KPM"


def test_extract_agency_mof() -> None:
    assert extract_agency("What is MOF budget allocation?") == "MOF"


def test_extract_agency_kwsp() -> None:
    assert extract_agency("EPF withdrawal rules 2025") == "KWSP"


def test_extract_agency_socso() -> None:
    assert extract_agency("PERKESO employment injury claim") == "PERKESO"


def test_extract_agency_none() -> None:
    assert extract_agency("What education grants are available?") is None


def test_extract_agency_case_insensitive() -> None:
    assert extract_agency("kpm policy on schooling") == "KPM"


def test_extract_agency_longest_match_wins() -> None:
    # "kementerian pendidikan" (longer) should match before "kementerian"
    assert extract_agency("dasar kementerian pendidikan") == "KPM"
