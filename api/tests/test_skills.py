"""Tests for the skills system — definitions, prompt building, and API route."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from polisi_api.chat.prompting import build_skill_prompt
from polisi_api.chat.retrieval import RetrievalFilters, RetrievedChunk
from polisi_api.chat.service import ChatService
from polisi_api.chat.skills import SKILL_BY_ID, SKILLS
from polisi_api.config import Settings
from polisi_api.models import SkillInfo


def _build_settings() -> Settings:
    return Settings.from_env(
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_DB_URL": "postgresql://postgres:postgres@localhost:5432/postgres",
            "SUPABASE_JWT_SECRET": "test-secret",
            "ANTHROPIC_API_KEY": "test-key",
            "OPENAI_API_KEY": "test-openai-key",
            "RETRIEVAL_MIN_SIMILARITY": "0.45",
            "RETRIEVAL_WEAK_SIMILARITY": "0.65",
        }
    )


def _chunk(title: str, agency: str, similarity: float = 0.80) -> RetrievedChunk:
    return RetrievedChunk(
        document_id="00000000-0000-0000-0000-000000000001",
        title=title,
        agency=agency,
        source_url="https://gov.example/doc",
        chunk_text="Relevant policy content here.",
        similarity=similarity,
        chunk_index=0,
    )


# --- Skill registry tests ---

def test_all_8_skills_registered() -> None:
    assert len(SKILLS) == 8


def test_skill_ids_are_unique() -> None:
    ids = [s.id for s in SKILLS]
    assert len(ids) == len(set(ids))


def test_skill_by_id_lookup() -> None:
    assert "parliament_question" in SKILL_BY_ID
    assert "parliament_speech" in SKILL_BY_ID
    assert "policy_brief" in SKILL_BY_ID
    assert "pekeliling_explainer" in SKILL_BY_ID
    assert "budget_analyst" in SKILL_BY_ID
    assert "law_explainer" in SKILL_BY_ID
    assert "data_dashboard" in SKILL_BY_ID
    assert "memo_drafter" in SKILL_BY_ID


def test_all_skills_have_bilingual_prompts() -> None:
    for skill in SKILLS:
        assert skill.system_prompt_en, f"{skill.id} missing EN prompt"
        assert skill.system_prompt_ms, f"{skill.id} missing MS prompt"
        assert skill.name_ms, f"{skill.id} missing MS name"
        assert skill.description_ms, f"{skill.id} missing MS description"


def test_skill_max_tokens_reasonable() -> None:
    for skill in SKILLS:
        assert 1000 <= skill.max_tokens <= 5000, f"{skill.id} max_tokens={skill.max_tokens}"


# --- Prompt building tests ---

def test_build_skill_prompt_uses_skill_system_prompt() -> None:
    skill = SKILL_BY_ID["parliament_question"]
    prompt = build_skill_prompt(
        question="Draft a question about education spending",
        language="en",
        contexts=[_chunk("Education Budget", "KPM")],
        skill=skill,
    )
    assert "Pardocs" in prompt.system
    assert "PEMBERITAHUAN PERTANYAAN" in prompt.system
    assert "Education Budget" in prompt.user
    assert prompt.support_mode == "strong"


def test_build_skill_prompt_ms_uses_malay_prompt() -> None:
    skill = SKILL_BY_ID["parliament_question"]
    prompt = build_skill_prompt(
        question="Gubal soalan tentang perbelanjaan pendidikan",
        language="ms",
        contexts=[],
        skill=skill,
    )
    assert "Peraturan Mesyuarat" in prompt.system
    assert prompt.support_mode == "none"


def test_build_skill_prompt_includes_live_data() -> None:
    skill = SKILL_BY_ID["budget_analyst"]
    prompt = build_skill_prompt(
        question="Analyse education budget 2025",
        language="en",
        contexts=[_chunk("Budget 2025", "MOF")],
        skill=skill,
        live_data_blocks=["GDP: 5.1% (2024 Q4)"],
    )
    assert "GDP: 5.1%" in prompt.user
    assert "Budget 2025" in prompt.user


# --- Service skill routing test ---


@dataclass
class FakeRetriever:
    responses: dict[str, list[RetrievedChunk]]

    async def retrieve(
        self,
        question: str,
        *,
        limit: int,
        filters: RetrievalFilters | None = None,
    ) -> list[RetrievedChunk]:
        return self.responses.get(question, [])[:limit]


@dataclass
class FakeGenerator:
    last_max_tokens: int | None = None

    async def generate(self, prompt, *, max_tokens=None):
        self.last_max_tokens = max_tokens
        return "Generated skill output [1]."


def test_service_routes_through_skill_prompt() -> None:
    asyncio.run(_run_skill_routing())


async def _run_skill_routing() -> None:
    question = "Draft a question about EPF withdrawal rules"
    retriever = FakeRetriever(
        responses={question: [_chunk("EPF Guidelines", "KWSP", 0.85)]}
    )
    generator = FakeGenerator()
    service = ChatService(
        settings=_build_settings(),
        retriever=retriever,
        generator=generator,
    )

    reply = await service.generate_reply(
        question=question, skill="parliament_question",
    )

    assert reply.kind == "answer"
    assert reply.response.citations[0].title == "EPF Guidelines"
    # Skill should use the skill's max_tokens, not the default 1200
    assert generator.last_max_tokens == SKILL_BY_ID["parliament_question"].max_tokens


def test_service_skips_clarification_when_skill_set() -> None:
    """Broad questions should NOT be rejected when a skill is selected."""
    asyncio.run(_run_skill_no_clarification())


async def _run_skill_no_clarification() -> None:
    question = "Tell me about education policy"  # would normally trigger clarification
    retriever = FakeRetriever(
        responses={question: [_chunk("Education Policy", "KPM", 0.70)]}
    )
    generator = FakeGenerator()
    service = ChatService(
        settings=_build_settings(),
        retriever=retriever,
        generator=generator,
    )

    reply = await service.generate_reply(
        question=question, skill="policy_brief",
    )

    # Should NOT be "clarification" — skill overrides the clarification check
    assert reply.kind == "answer"
    assert generator.last_max_tokens == SKILL_BY_ID["policy_brief"].max_tokens


# --- API route test ---

def test_skills_api_route() -> None:
    import os
    os.environ["SUPABASE_URL"] = "https://example.supabase.co"
    os.environ["SUPABASE_DB_URL"] = "postgresql://postgres:postgres@localhost:5432/postgres"
    from fastapi.testclient import TestClient
    from polisi_api.main import create_app

    app = create_app(_build_settings())
    client = TestClient(app)
    response = client.get("/api/skills")

    assert response.status_code == 200
    skills = response.json()
    assert len(skills) == 8
    assert skills[0]["id"] == "parliament_question"
    assert "name" in skills[0]
    assert "name_ms" in skills[0]
    assert "description" in skills[0]
    assert "icon" in skills[0]
