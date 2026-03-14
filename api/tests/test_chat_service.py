from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os

from fastapi.testclient import TestClient

from polisi_api.auth import AuthenticatedUser, get_current_user
from polisi_api.chat.repository import InMemoryChatRepository
from polisi_api.chat.prompting import PromptPackage
from polisi_api.chat.retrieval import RetrievalFilters, RetrievedChunk, PostgresRetriever
from polisi_api.chat.service import ChatService, TextGenerator
from polisi_api.config import Settings
from polisi_api.dependencies import get_chat_service


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

    async def retrieve_multi(
        self,
        queries: list[str],
        *,
        limit: int,
        filters: RetrievalFilters | None = None,
    ) -> list[RetrievedChunk]:
        """Merge results from all queries, deduplicating by (doc_id, chunk_index)."""
        seen: set[tuple[str | None, int | None]] = set()
        result: list[RetrievedChunk] = []
        for q in queries:
            for c in self.responses.get(q, []):
                key = (c.document_id, c.chunk_index)
                if key not in seen:
                    seen.add(key)
                    result.append(c)
        return result[:limit]


@dataclass
class FakeGenerator(TextGenerator):
    replies: dict[str, str]

    async def generate(self, prompt: PromptPackage, *, max_tokens: int | None = None) -> str:
        # Match the question from the first line of the user prompt
        first_line = prompt.user.splitlines()[0]
        if first_line in self.replies:
            return self.replies[first_line]
        # Fallback: try second line (legacy "Question:\n{q}" format)
        if len(prompt.user.splitlines()) > 1:
            return self.replies[prompt.user.splitlines()[1]]
        raise KeyError(f"No reply for: {first_line!r}")


def build_settings() -> Settings:
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


def chunk(
    title: str,
    agency: str,
    question: str,
    similarity: float,
    *,
    fts_rank: float = 0.0,
    rrf_score: float = 0.0,
) -> RetrievedChunk:
    return RetrievedChunk(
        document_id="00000000-0000-0000-0000-000000000001",
        title=title,
        agency=agency,
        source_url="https://gov.example/policy",
        chunk_text=f"Evidence for {question}",
        similarity=similarity,
        chunk_index=0,
        fts_rank=fts_rank,
        rrf_score=rrf_score,
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
    assert "[1]" in weak_reply.response.answer


def test_fts_only_match_treated_as_weak_support() -> None:
    """A chunk found only via full-text search (cosine sim=0) should use
    the FTS similarity floor and land in limited-support, not be discarded."""
    asyncio.run(_run_fts_only())


async def _run_fts_only() -> None:
    question = "What is BR1M eligibility?"
    retriever = FakeRetriever(
        responses={
            question: [
                chunk("BR1M Guidelines", "MOF", question, similarity=0.0, fts_rank=0.12, rrf_score=0.015),
            ],
        }
    )
    generator = FakeGenerator(
        replies={question: "BR1M eligibility is determined by household income [1]."}
    )
    service = ChatService(settings=build_settings(), retriever=retriever, generator=generator)
    reply = await service.generate_reply(question=question)

    # FTS floor (0.50) > min_similarity (0.45) → not discarded
    # FTS floor (0.50) < weak_similarity (0.65) → weak/limited-support
    assert reply.response.kind == "limited-support"
    assert len(reply.response.citations) > 0


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


@dataclass
class EmptyEmbeddingClient:
    async def embed(self, text: str) -> list[float]:
        return []


def test_retrieve_returns_empty_list_when_embed_returns_empty() -> None:
    asyncio.run(_run_retrieve_empty_embedding())


async def _run_retrieve_empty_embedding() -> None:
    settings = build_settings()
    retriever = PostgresRetriever(
        settings, embedding_client=EmptyEmbeddingClient()
    )
    result = await retriever.retrieve("any question", limit=5)
    assert result == []


# --- Tests for RAG pipeline enhancements ---


def test_pipeline_with_reranker_and_skill() -> None:
    """Full pipeline with reranker and skill — verify reranker and adaptive cutoff run."""
    asyncio.run(_run_pipeline_skill())


async def _run_pipeline_skill() -> None:
    from polisi_api.chat.reranker import NoOpReranker

    question = "What childcare subsidies are available for working parents?"
    retriever = FakeRetriever(
        responses={
            question: [
                chunk("Childcare Support", "KPWKM", question, 0.79),
                chunk("Education Policy", "KPM", question, 0.60),
            ],
        }
    )
    generator = FakeGenerator(
        replies={question: "Childcare subsidies are available [1]."}
    )
    reranker = NoOpReranker()
    service = ChatService(
        settings=build_settings(),
        retriever=retriever,
        generator=generator,
        reranker=reranker,
    )
    reply = await service.generate_reply(question=question, skill="policy_brief")
    assert reply.response.kind == "answer"
    assert len(reply.response.citations) >= 1


def test_pipeline_deduplication_applied() -> None:
    """Adjacent same-doc chunks should be deduplicated before reaching the prompt."""
    asyncio.run(_run_dedup_pipeline())


async def _run_dedup_pipeline() -> None:
    question = "What is the education policy?"
    doc_uuid = "00000000-0000-0000-0000-000000000099"
    c1 = RetrievedChunk(
        document_id=doc_uuid, title="Edu Policy", agency="KPM",
        source_url="https://gov.example/policy", chunk_text=f"Evidence for {question}",
        similarity=0.85, chunk_index=0, rrf_score=0.01,
    )
    c2 = RetrievedChunk(
        document_id=doc_uuid, title="Edu Policy", agency="KPM",
        source_url="https://gov.example/policy", chunk_text=f"More evidence for {question}",
        similarity=0.80, chunk_index=1, rrf_score=0.009,
    )
    retriever = FakeRetriever(responses={question: [c1, c2]})
    generator = FakeGenerator(
        replies={question: "Education policy involves various initiatives [1]."}
    )
    service = ChatService(settings=build_settings(), retriever=retriever, generator=generator)
    reply = await service.generate_reply(question=question)

    # After dedup, only 1 chunk should survive (adjacent same doc)
    assert reply.response.kind == "answer"
    assert len(reply.response.citations) == 1


def test_pipeline_without_reranker_still_works() -> None:
    """When no reranker is provided, pipeline falls back to plain retrieval."""
    asyncio.run(_run_no_reranker())


async def _run_no_reranker() -> None:
    question = "What is BR1M eligibility?"
    retriever = FakeRetriever(
        responses={
            question: [
                chunk("BR1M Guidelines", "MOF", question, 0.75),
            ],
        }
    )
    generator = FakeGenerator(
        replies={question: "BR1M eligibility depends on income [1]."}
    )
    # No reranker, no anthropic_client — should work fine
    service = ChatService(settings=build_settings(), retriever=retriever, generator=generator)
    reply = await service.generate_reply(question=question)
    assert reply.response.kind == "answer"
    assert len(reply.response.citations) == 1


def test_conversation_aware_retrieval_with_history() -> None:
    """When conversation_history is provided with an anthropic client, reformulation runs."""
    asyncio.run(_run_conversation_aware())


async def _run_conversation_aware() -> None:
    from polisi_api.chat.reranker import NoOpReranker
    from tests.test_reranker import FakeAnthropicClient, FakeMessages, FakeTextBlock

    question = "What about the eligibility criteria?"
    # The reformulated query will be the original since our fake client returns a canned response
    reformulated = "What are the BR1M eligibility criteria?"

    fake_anthropic = FakeAnthropicClient(
        messages=FakeMessages(response_text=reformulated)
    )

    # Retriever responds to both original and reformulated queries
    retriever = FakeRetriever(
        responses={
            question: [chunk("General", "MOF", question, 0.5)],
            reformulated: [chunk("BR1M Guidelines", "MOF", reformulated, 0.82)],
        }
    )

    # The generator receives the ORIGINAL question in the prompt, not the reformulated one
    generator = FakeGenerator(
        replies={
            question: "The eligibility criteria include income thresholds [1].",
            reformulated: "BR1M eligibility is based on household income [1].",
        }
    )

    settings = build_settings()
    # Disable query expansion to isolate reformulation testing
    settings_env = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_DB_URL": "postgresql://postgres:postgres@localhost:5432/postgres",
        "SUPABASE_JWT_SECRET": "test-secret",
        "ANTHROPIC_API_KEY": "test-key",
        "OPENAI_API_KEY": "test-openai-key",
        "RETRIEVAL_MIN_SIMILARITY": "0.45",
        "RETRIEVAL_WEAK_SIMILARITY": "0.65",
        "ENABLE_QUERY_EXPANSION": "false",
        "ENABLE_RERANKING": "false",
    }
    settings = Settings.from_env(settings_env)

    service = ChatService(
        settings=settings,
        retriever=retriever,
        generator=generator,
        anthropic_client=fake_anthropic,  # type: ignore
    )

    history = [
        ("user", "Tell me about BR1M"),
        ("assistant", "BR1M is a cash aid programme for low-income households."),
    ]

    reply = await service.generate_reply(
        question=question,
        conversation_history=history,
    )

    # The retrieval used the reformulated query, but the prompt used the original question.
    # The reformulated query retrieves the BR1M Guidelines chunk with 0.82 similarity.
    assert reply.response.kind == "answer"
