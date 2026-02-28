from __future__ import annotations

import asyncio
from dataclasses import dataclass

from polisi_api.chat.prompting import PromptPackage
from polisi_api.chat.retrieval import RetrievedChunk
from polisi_api.chat.service import ChatService, TextGenerator
from polisi_api.config import Settings


@dataclass
class FakeRetriever:
    responses: dict[str, list[RetrievedChunk]]

    async def retrieve(self, question: str, *, limit: int) -> list[RetrievedChunk]:
        return self.responses.get(question, [])[:limit]


@dataclass
class FakeGenerator(TextGenerator):
    replies: dict[str, str]

    async def generate(self, prompt: PromptPackage) -> str:
        return self.replies[prompt.user.splitlines()[1]]


def build_settings() -> Settings:
    return Settings.from_env(
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_DB_URL": "postgresql://postgres:postgres@localhost:5432/postgres",
            "SUPABASE_JWT_SECRET": "test-secret",
            "ANTHROPIC_API_KEY": "test-key",
            "OPENAI_API_KEY": "test-openai-key",
        }
    )


def chunk(title: str, agency: str, question: str, similarity: float) -> RetrievedChunk:
    return RetrievedChunk(
        document_id="00000000-0000-0000-0000-000000000001",
        title=title,
        agency=agency,
        source_url="https://gov.example/policy",
        chunk_text=f"Evidence for {question}",
        similarity=similarity,
        chunk_index=0,
    )


def test_chat_service_handles_ms_en_clarify_and_weak_retrieval_paths() -> None:
    asyncio.run(run_chat_service_paths())


async def run_chat_service_paths() -> None:
    question_ms = "Apakah bantuan pendidikan untuk pelajar IPT?"
    question_en = "What childcare subsidies are available for working parents?"
    question_broad = "Tell me about education policy"
    question_weak = "What grants help single mothers?"
    retriever = FakeRetriever(
        responses={
            question_ms: [chunk("Bantuan Pendidikan", "KPM", question_ms, 0.82)],
            question_en: [chunk("Childcare Support", "KPWKM", question_en, 0.79)],
            question_weak: [chunk("Family Assistance", "KPWKM", question_weak, 0.58)],
        }
    )
    generator = FakeGenerator(
        replies={
            question_ms: "Bantuan pendidikan IPT disediakan melalui skim bantuan pelajar [1].",
            question_en: "Working parents may qualify for childcare subsidies through the ministry programme [1].",
            question_weak: "Available excerpts point to grant support administered through family-assistance channels [1].",
        }
    )
    service = ChatService(settings=build_settings(), retriever=retriever, generator=generator)

    ms_reply = await service.generate_reply(question=question_ms)
    en_reply = await service.generate_reply(question=question_en)
    clarify_reply = await service.generate_reply(question=question_broad)
    weak_reply = await service.generate_reply(question=question_weak)

    assert ms_reply.response.language == "ms"
    assert ms_reply.response.kind == "answer"
    assert ms_reply.response.citations[0].title == "Bantuan Pendidikan"
    assert "[1]" in ms_reply.response.answer

    assert en_reply.response.language == "en"
    assert en_reply.response.kind == "answer"
    assert en_reply.response.citations[0].agency == "KPWKM"

    assert clarify_reply.response.kind == "clarification"
    assert clarify_reply.response.citations == []
    assert "specific policy" in clarify_reply.response.answer.lower()

    assert weak_reply.response.kind == "limited-support"
    assert weak_reply.response.language == "en"
    assert weak_reply.response.answer.startswith("The retrieved document support is limited")
