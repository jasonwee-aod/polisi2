from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os

from fastapi.testclient import TestClient

from polisi_api.auth import AuthenticatedUser, get_current_user
from polisi_api.chat.repository import InMemoryChatRepository
from polisi_api.chat.prompting import PromptPackage
from polisi_api.chat.retrieval import RetrievedChunk
from polisi_api.chat.service import ChatService, TextGenerator
from polisi_api.config import Settings
from polisi_api.dependencies import get_chat_service


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


def test_streaming_chat_persists_messages_and_citations() -> None:
    asyncio.run(run_streaming_chat_persistence())


async def run_streaming_chat_persistence() -> None:
    os.environ["SUPABASE_URL"] = "https://example.supabase.co"
    os.environ["SUPABASE_DB_URL"] = "postgresql://postgres:postgres@localhost:5432/postgres"
    from polisi_api.main import create_app

    question = "Apakah bantuan pendidikan untuk pelajar IPT?"
    repository = InMemoryChatRepository()
    service = ChatService(
        settings=build_settings(),
        retriever=FakeRetriever(
            responses={question: [chunk("Bantuan Pendidikan", "KPM", question, 0.8)]}
        ),
        generator=FakeGenerator(
            replies={question: "Bantuan pendidikan IPT disediakan melalui skim bantuan pelajar [1]."}
        ),
        repository=repository,
    )
    app = create_app(build_settings())
    app.dependency_overrides[get_chat_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id="8bd9d241-8380-4dd7-a1a8-a664e1d74c8f",
        email="citizen@example.com",
        role="authenticated",
        claims={"sub": "8bd9d241-8380-4dd7-a1a8-a664e1d74c8f"},
    )
    client = TestClient(app)

    with client.stream(
        "POST",
        "/api/chat",
        json={"question": question, "create_conversation": True},
    ) as response:
        payload_lines = [line for line in response.iter_lines() if line]

    assert response.status_code == 200
    assert len(payload_lines) >= 4
    assert any('"event":"message-delta"' in line for line in payload_lines)
    detail = repository.list_conversations(
        user_id="8bd9d241-8380-4dd7-a1a8-a664e1d74c8f"
    )[0]
    conversation = repository.get_conversation_detail(
        user_id="8bd9d241-8380-4dd7-a1a8-a664e1d74c8f",
        conversation_id=str(detail.id),
    )

    assert detail.message_count == 2
    assert conversation is not None
    assert [message.role for message in conversation.messages] == ["user", "assistant"]
    assert conversation.messages[1].citations[0].title == "Bantuan Pendidikan"
