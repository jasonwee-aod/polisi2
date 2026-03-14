"""Prompt builders for grounded government-policy answers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from polisi_api.models import LanguageCode

from .retrieval import RetrievedChunk
from .skills import SkillDefinition

SupportMode = Literal["strong", "weak", "none"]

# ---------------------------------------------------------------------------
# Core system identity — shared across all modes
# ---------------------------------------------------------------------------

_IDENTITY_EN = (
    "You are Polisi, a knowledgeable Malaysian government policy assistant. "
    "You have deep expertise in Malaysian government policy, legislation, "
    "economics, and public administration. "
    "Respond in English. Be direct, confident, and thorough — like a senior "
    "policy analyst briefing a minister. Never hedge unnecessarily."
)

_IDENTITY_MS = (
    "Anda adalah Polisi, pembantu dasar kerajaan Malaysia yang berpengetahuan. "
    "Anda mempunyai kepakaran mendalam dalam dasar kerajaan, perundangan, "
    "ekonomi, dan pentadbiran awam Malaysia. "
    "Jawab dalam Bahasa Malaysia. Bersikap tegas, yakin, dan menyeluruh — "
    "seperti penganalisis dasar kanan yang memberi taklimat kepada menteri."
)

_CITATION_RULES = (
    "\n\nCitation rules:\n"
    "- When you use information from the provided documents, cite with [n] "
    "matching the document number.\n"
    "- Weave citations naturally into your answer (e.g., '...as outlined in "
    "the 2025 Budget Speech [1]').\n"
    "- You do NOT need to label every sentence with a source tag. "
    "Only cite when referencing specific facts, figures, or policy details.\n"
    "- If you use your own knowledge to provide context, analysis, or "
    "widely-known facts, just state them naturally without any tag.\n"
    "- If you fetch live data via tools, mention the source naturally "
    "(e.g., 'According to data.gov.my, ...')."
)


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
    """
    if len(contexts) <= 2:
        return [(i + 1, c) for i, c in enumerate(contexts)]

    indexed = [(i + 1, c) for i, c in enumerate(contexts)]
    first = indexed[0]
    rest = indexed[1:]
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
    identity = _IDENTITY_MS if language == "ms" else _IDENTITY_EN
    live_data_section = _format_live_data_section(live_data_blocks)

    if support_mode == "none":
        # No indexed documents — answer from knowledge + tools
        system = (
            f"{identity}\n\n"
            "Answer the question using your knowledge and any tools available to you. "
            "If you can fetch relevant live data, do so and integrate it into your answer."
            f"{_CITATION_RULES}"
        )
        user = f"{question}{live_data_section}"
    else:
        reordered = reorder_for_attention(contexts)
        context_block = _format_context_block(contexts, reordered=reordered)

        if support_mode == "weak":
            guidance = (
                "The following government documents provide some relevant context. "
                "Use them where helpful, but don't hesitate to draw on your broader "
                "knowledge to give a complete answer."
            )
        else:  # strong
            guidance = (
                "The following government documents are directly relevant. "
                "Ground your answer primarily in these documents, and supplement "
                "with your knowledge where it adds useful context."
            )

        live_note = ""
        if live_data_blocks:
            live_note = (
                " Live data from data.gov.my is also provided — "
                "integrate it naturally into your answer."
            )

        system = (
            f"{identity}\n\n"
            f"{guidance}{live_note}"
            f"{_CITATION_RULES}"
        )
        user = (
            f"{question}\n\n"
            "Government documents:\n"
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
        f"\n\nGovernment documents:\n{context_block}"
        if context_block else ""
    )
    live_data_section = _format_live_data_section(live_data_blocks)

    user = f"{question}{context_section}{live_data_section}"

    support_mode: SupportMode = "strong" if contexts else "none"
    return PromptPackage(
        language=language,
        support_mode=support_mode,
        system=system,
        user=user,
        contexts=contexts,
    )
