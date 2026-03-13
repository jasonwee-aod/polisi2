"""Prompt builders for grounded government-policy answers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from polisi_api.models import LanguageCode

from .retrieval import RetrievedChunk

SupportMode = Literal["strong", "weak", "none"]


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

    if support_mode == "none":
        # No DB context — answer entirely from Claude's training knowledge
        system = (
            "You are Polisi, a Malaysian government policy assistant. "
            f"Respond in {language_name} using a formal government-brief tone. "
            "No relevant documents were found in the indexed government database for this question. "
            "Answer using your training knowledge. "
            "Cite every factual claim inline with [General knowledge]. "
            "Open your answer by noting that no indexed policy documents were found and this draws on general knowledge."
        )
        user = f"Question:\n{question}"
    else:
        context_block = "\n\n".join(
            f"[{index}] {chunk.title} | {chunk.agency}\n{chunk.chunk_text}"
            for index, chunk in enumerate(contexts, start=1)
        )
        if support_mode == "weak":
            support_note = (
                "The retrieved document support is partial. "
                "Prioritise the provided excerpts and cite every claim drawn from them with the matching [n] marker. "
                "Where the documents are insufficient, supplement with your training knowledge and cite those claims with [General knowledge]. "
                "Note clearly in your answer that the indexed document support is limited."
            )
        else:  # strong
            support_note = (
                "Prioritise the provided government documents as your primary source. "
                "Cite every claim drawn from them inline with the matching [n] marker. "
                "You may supplement with your training knowledge where it adds useful context — "
                "cite those claims explicitly with [General knowledge]. "
                "Every factual claim must be attributed to either [n] or [General knowledge]."
            )
        system = (
            "You are Polisi, a Malaysian government policy assistant. "
            f"Respond in {language_name} using a formal government-brief tone. "
            "You have two knowledge sources: "
            "(1) retrieved government documents provided below — always prioritise these; "
            "(2) your training knowledge — use this to supplement or add context. "
            f"{support_note}"
        )
        user = (
            f"Question:\n{question}\n\n"
            "Retrieved government-document excerpts:\n"
            f"{context_block}"
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


def build_general_knowledge_prefix(language: LanguageCode) -> str:
    if language == "ms":
        return (
            "Tiada dokumen dasar kerajaan yang diindeks ditemui untuk soalan ini. "
            "Jawapan ini berdasarkan pengetahuan latihan umum:"
        )
    return (
        "No indexed government policy documents were found for this question. "
        "This answer draws on general training knowledge:"
    )


def build_weak_support_prefix(language: LanguageCode) -> str:
    if language == "ms":
        return "Sokongan dokumen yang ditemui terhad, jadi jawapan ini bergantung pada petikan yang tersedia:"
    return "The retrieved document support is limited, so this answer relies on the available excerpts:"
