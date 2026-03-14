"""Prompt builders for grounded government-policy answers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from polisi_api.models import LanguageCode

from .retrieval import RetrievedChunk
from .skills import SkillDefinition

SupportMode = Literal["strong", "weak", "none"]


@dataclass(frozen=True)
class PromptPackage:
    language: LanguageCode
    support_mode: SupportMode
    system: str
    user: str
    contexts: list[RetrievedChunk]


def reorder_for_attention(
    contexts: list[RetrievedChunk],
) -> list[tuple[int, RetrievedChunk]]:
    """Reorder chunks so rank-1 is first, rank-2 is last, worst in middle.

    Returns (original_1_based_index, chunk) pairs.  Citation indices remain
    stable to the *original* position so [n] markers stay consistent.

    Lost-in-the-middle pattern: best, worst…, second-best
    For 1 chunk  → [1]
    For 2 chunks → [1, 2]
    For 3 chunks → [1, 3, 2]
    For 4 chunks → [1, 4, 3, 2]
    For 5 chunks → [1, 5, 4, 3, 2]
    """
    if len(contexts) <= 2:
        return [(i + 1, c) for i, c in enumerate(contexts)]

    indexed = [(i + 1, c) for i, c in enumerate(contexts)]
    first = indexed[0]
    rest = indexed[1:]
    # Reverse the rest so second-best ends up last
    rest_reversed = list(reversed(rest))
    return [first] + rest_reversed


def _format_context_block(
    contexts: list[RetrievedChunk],
    *,
    reordered: list[tuple[int, RetrievedChunk]] | None = None,
) -> str:
    if reordered is not None:
        if not reordered:
            return ""
        return "\n\n".join(
            f"[{idx}] {chunk.title} | {chunk.agency}\n{chunk.chunk_text}"
            for idx, chunk in reordered
        )
    if not contexts:
        return ""
    return "\n\n".join(
        f"[{index}] {chunk.title} | {chunk.agency}\n{chunk.chunk_text}"
        for index, chunk in enumerate(contexts, start=1)
    )


def _format_live_data_section(live_data_blocks: list[str] | None) -> str:
    if not live_data_blocks:
        return ""
    return (
        "\n\nLive government data (fetched from data.gov.my in real time):\n"
        + "\n\n".join(live_data_blocks)
    )


def build_prompt(
    *,
    question: str,
    language: LanguageCode,
    contexts: list[RetrievedChunk],
    support_mode: SupportMode,
    live_data_blocks: list[str] | None = None,
) -> PromptPackage:
    language_name = "Bahasa Malaysia" if language == "ms" else "English"
    live_data_section = _format_live_data_section(live_data_blocks)

    if support_mode == "none" and not live_data_blocks:
        # No DB context and no live data — answer from training knowledge + tools
        system = (
            "You are Polisi, a Malaysian government policy assistant. "
            f"Respond in {language_name} using a formal yet conversational tone. "
            "Answer the question directly and confidently. "
            "You have access to tools that can fetch live government data — use them when relevant. "
            "Cite factual claims: use [data.gov.my] for live data and [General knowledge] for your training knowledge."
        )
        user = f"Question:\n{question}"
    elif support_mode == "none" and live_data_blocks:
        # No document context, but we have live data from data.gov.my
        system = (
            "You are Polisi, a Malaysian government policy assistant. "
            f"Respond in {language_name} using a formal government-brief tone. "
            "No indexed policy documents were found, but live government data from data.gov.my "
            "is provided below. Use this data as your primary source. "
            "Cite data from data.gov.my with [data.gov.my]. "
            "You may supplement with your training knowledge — cite those claims with [General knowledge]."
        )
        user = f"Question:\n{question}{live_data_section}"
    else:
        reordered = reorder_for_attention(contexts)
        context_block = _format_context_block(contexts, reordered=reordered)
        if support_mode == "weak":
            support_note = (
                "The retrieved documents provide partial coverage. "
                "Cite claims from them with the matching [n] marker. "
                "Supplement freely with your training knowledge and tools where the documents are insufficient — "
                "cite those claims with [General knowledge] or [data.gov.my]."
            )
        else:  # strong
            support_note = (
                "Prioritise the provided government documents as your primary source. "
                "Cite every claim drawn from them inline with the matching [n] marker. "
                "You may supplement with your training knowledge where it adds useful context — "
                "cite those claims explicitly with [General knowledge]. "
                "Every factual claim must be attributed to either [n] or [General knowledge]."
            )

        live_note = ""
        if live_data_blocks:
            live_note = (
                " Additionally, live data from data.gov.my is provided. "
                "Cite claims from this live data with [data.gov.my]."
            )

        system = (
            "You are Polisi, a Malaysian government policy assistant. "
            f"Respond in {language_name} using a formal government-brief tone. "
            "You have two knowledge sources: "
            "(1) retrieved government documents provided below — always prioritise these; "
            "(2) your training knowledge — use this to supplement or add context. "
            f"{support_note}{live_note}"
        )
        user = (
            f"Question:\n{question}\n\n"
            "Retrieved government-document excerpts:\n"
            f"{context_block}"
            f"{live_data_section}"
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


def build_skill_prompt(
    *,
    question: str,
    language: LanguageCode,
    contexts: list[RetrievedChunk],
    skill: SkillDefinition,
    live_data_blocks: list[str] | None = None,
) -> PromptPackage:
    """Build a prompt using a skill-specific system prompt."""
    system = skill.system_prompt_ms if language == "ms" else skill.system_prompt_en

    reordered = reorder_for_attention(contexts)
    context_block = _format_context_block(contexts, reordered=reordered)
    context_section = (
        f"\n\nRetrieved government-document excerpts:\n{context_block}"
        if context_block else ""
    )
    live_data_section = _format_live_data_section(live_data_blocks)

    user = f"Question:\n{question}{context_section}{live_data_section}"

    support_mode: SupportMode = "strong" if contexts else "none"
    return PromptPackage(
        language=language,
        support_mode=support_mode,
        system=system,
        user=user,
        contexts=contexts,
    )
