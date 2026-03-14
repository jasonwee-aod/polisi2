"""Language, agency detection, and prompt-shape helpers."""

from __future__ import annotations

from polisi_api.models import LanguageCode

_MALAY_HINTS = {
    "apa",
    "apakah",
    "bagaimana",
    "bantuan",
    "dasar",
    "kerajaan",
    "pelajar",
    "untuk",
    "boleh",
    "adakah",
    "syarat",
    "permohonan",
    "keluarga",
    "pekerja",
}
_BROAD_PREFIXES = (
    "tell me about",
    "overview of",
    "explain policy",
    "ceritakan tentang",
)

# Maps common names / abbreviations → canonical agency value stored in the DB.
# Keys must be lowercase.  Add entries as new scrapers are onboarded.
_AGENCY_ALIASES: dict[str, str] = {
    # Education
    "kpm": "KPM",
    "moe": "KPM",
    "kementerian pendidikan": "KPM",
    "ministry of education": "KPM",
    # Women, Family & Community
    "kpwkm": "KPWKM",
    "kementerian pembangunan wanita": "KPWKM",
    "ministry of women": "KPWKM",
    # Finance
    "mof": "MOF",
    "kementerian kewangan": "MOF",
    "ministry of finance": "MOF",
    # Human Resources
    "ksm": "KSM",
    "mohr": "KSM",
    "kementerian sumber manusia": "KSM",
    "ministry of human resources": "KSM",
    # Health
    "kkm": "KKM",
    "moh": "KKM",
    "kementerian kesihatan": "KKM",
    "ministry of health": "KKM",
    # Home Affairs
    "kdn": "KDN",
    "moha": "KDN",
    "kementerian dalam negeri": "KDN",
    "ministry of home affairs": "KDN",
    # EPF / KWSP
    "kwsp": "KWSP",
    "epf": "KWSP",
    # SOCSO / PERKESO
    "perkeso": "PERKESO",
    "socso": "PERKESO",
    # LHDN / IRB
    "lhdn": "LHDN",
    "irb": "LHDN",
    "inland revenue": "LHDN",
    # JPM / Prime Minister
    "jpm": "JPM",
    "jabatan perdana menteri": "JPM",
    "prime minister": "JPM",
    # Economy
    "kementerian ekonomi": "KE",
    "ministry of economy": "KE",
    # data.gov.my
    "data.gov.my": "data.gov.my",
}


def detect_language(text: str) -> LanguageCode:
    normalized = text.lower()
    malay_score = sum(1 for token in normalized.replace("?", " ").split() if token in _MALAY_HINTS)
    return "ms" if malay_score >= 2 else "en"


def needs_clarification(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    tokens = normalized.split()
    if len(tokens) <= 1:
        return True
    return any(normalized.startswith(prefix) for prefix in _BROAD_PREFIXES)


def extract_agency(text: str) -> str | None:
    """Return the canonical agency code if the question mentions one, else None."""
    lowered = text.lower()
    # Longest-match-first so "kementerian pendidikan" beats "kementerian"
    for alias in sorted(_AGENCY_ALIASES, key=len, reverse=True):
        if alias in lowered:
            return _AGENCY_ALIASES[alias]
    return None
