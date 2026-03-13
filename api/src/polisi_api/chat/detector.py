"""Language and prompt-shape detection helpers."""

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
