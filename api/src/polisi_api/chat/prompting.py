"""Prompt builders for grounded government-policy answers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from polisi_api.models import LanguageCode

from .retrieval import RetrievedChunk
from .skills import SkillDefinition

SupportMode = Literal["strong", "weak", "none"]

# One system prompt. No modes, no tiers, no mechanical citation rules.
# Just tell Claude who it is and let it be Claude.

_SYSTEM_EN = (
    "You are Polisi, a Malaysian government policy expert. "
    "You speak with authority on Malaysian policy, law, economics, and government operations. "
    "You have access to a database of Malaysian government documents and live data from data.gov.my. "
    "Answer in English unless the user writes in Bahasa Malaysia."
)

_SYSTEM_MS = (
    "Anda adalah Polisi, pakar dasar kerajaan Malaysia. "
    "Anda berautoriti dalam dasar, undang-undang, ekonomi, dan operasi kerajaan Malaysia. "
    "Anda mempunyai akses kepada pangkalan data dokumen kerajaan dan data langsung daripada data.gov.my. "
    "Jawab dalam Bahasa Malaysia."
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
    """Reorder chunks: best first, second-best last, worst in middle."""
    if len(contexts) <= 2:
        return [(i + 1, c) for i, c in enumerate(contexts)]
    indexed = [(i + 1, c) for i, c in enumerate(contexts)]
    return [indexed[0]] + list(reversed(indexed[1:]))


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
    system = _SYSTEM_MS if language == "ms" else _SYSTEM_EN
    live_data_section = _format_live_data_section(live_data_blocks)

    if not contexts:
        user = f"{question}{live_data_section}"
    else:
        system += " Cite sources inline with [n] when referencing specific document content."
        reordered = reorder_for_attention(contexts)
        context_block = _format_context_block(contexts, reordered=reordered)
        user = f"{question}\n\n---\n\n{context_block}{live_data_section}"

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


# Keep these for backward compat but they're no longer used in the service
def build_general_knowledge_prefix(language: LanguageCode) -> str:
    return ""

def build_weak_support_prefix(language: LanguageCode) -> str:
    return ""


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
    if contexts:
        system += " Cite sources inline with [n] when referencing specific document content."

    reordered = reorder_for_attention(contexts)
    context_block = _format_context_block(contexts, reordered=reordered)
    context_section = f"\n\n---\n\n{context_block}" if context_block else ""
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
