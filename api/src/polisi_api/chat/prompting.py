"""Prompt builders for grounded government-policy answers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from polisi_api.models import LanguageCode

from .retrieval import RetrievedChunk

SupportMode = Literal["strong", "weak"]


@dataclass(frozen=True)
class PromptPackage:
    language: LanguageCode
    support_mode: SupportMode
    system: str
    user: str
    contexts: list[RetrievedChunk]


def build_prompt(
    *,
    question: str,
    language: LanguageCode,
    contexts: list[RetrievedChunk],
    support_mode: SupportMode,
) -> PromptPackage:
    language_name = "Bahasa Malaysia" if language == "ms" else "English"
    support_note = (
        "Use only the provided sources. Support is limited, so be explicit when evidence is partial."
        if support_mode == "weak"
        else "Use only the provided sources and cite every supported claim inline with [n] markers."
    )
    context_block = "\n\n".join(
        f"[{index}] {chunk.title} | {chunk.agency}\n{chunk.chunk_text}"
        for index, chunk in enumerate(contexts, start=1)
    )
    system = (
        "You are Polisi, a Malaysian government policy assistant. "
        f"Respond in {language_name} using a formal government-brief tone. "
        "Never use open-web information or unsupported claims. "
        f"{support_note}"
    )
    user = (
        f"Question:\n{question}\n\n"
        "Retrieved government-document excerpts:\n"
        f"{context_block}\n\n"
        "If the retrieved support is weak, say so briefly while still answering only from the excerpts."
    )
    return PromptPackage(
        language=language,
        support_mode=support_mode,
        system=system,
        user=user,
        contexts=contexts,
    )


def build_clarification_text(language: LanguageCode) -> str:
    if language == "ms":
        return "Boleh anda jelaskan dasar, bantuan, atau agensi yang anda mahu saya semak dahulu?"
    return "Could you narrow this to a specific policy, benefit, or government agency first?"


def build_no_information_text(language: LanguageCode) -> str:
    if language == "ms":
        return (
            "Saya tidak menemui maklumat yang mencukupi dalam dokumen kerajaan yang diindeks "
            "untuk menjawab soalan ini dengan selamat."
        )
    return (
        "I could not find enough support in the indexed government documents to answer this safely."
    )


def build_weak_support_prefix(language: LanguageCode) -> str:
    if language == "ms":
        return "Sokongan dokumen yang ditemui terhad, jadi jawapan ini bergantung pada petikan yang tersedia:"
    return "The retrieved document support is limited, so this answer relies on the available excerpts:"
