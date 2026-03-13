"""Core chat behavior for retrieval-grounded answers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from anthropic import AsyncAnthropic, RateLimitError

from polisi_api.config import Settings
from polisi_api.models import AssistantResponse, ChatRequest, CitationRecord

from .detector import detect_language, needs_clarification
from .prompting import (
    PromptPackage,
    build_clarification_text,
    build_general_knowledge_prefix,
    build_prompt,
    build_weak_support_prefix,
)
from .repository import ChatRepository
from .retrieval import RetrievedChunk, Retriever


class TextGenerator(Protocol):
    async def generate(self, prompt: PromptPackage) -> str: ...


@dataclass
class GeneratedReply:
    response: AssistantResponse
    kind: str
    retrieved_chunks: list[RetrievedChunk]


class AnthropicTextGenerator:
    def __init__(self, settings: Settings) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key or "")
        self._model = settings.anthropic_model

    async def generate(self, prompt: PromptPackage) -> str:
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1200,
                system=prompt.system,
                messages=[{"role": "user", "content": prompt.user}],
            )
            text_parts: list[str] = []
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    text_parts.append(block.text)
            return "".join(text_parts).strip()
        except RateLimitError:
            return "[Rate limit reached — please try again in a moment.]"


class ChatService:
    def __init__(
        self,
        *,
        settings: Settings,
        retriever: Retriever,
        generator: TextGenerator,
        repository: ChatRepository | None = None,
    ) -> None:
        self._settings = settings
        self._retriever = retriever
        self._generator = generator
        self._repository = repository

    async def generate_reply(self, *, question: str, conversation_id: str | None = None) -> GeneratedReply:
        language = detect_language(question)
        conversation_value = conversation_id or str(uuid4())

        if needs_clarification(question):
            response = AssistantResponse(
                conversation_id=conversation_value,
                message_id=uuid4(),
                language=language,
                answer=build_clarification_text(language),
                citations=[],
                kind="clarification",
            )
            return GeneratedReply(response=response, kind="clarification", retrieved_chunks=[])

        retrieved = await self._retriever.retrieve(question, limit=self._settings.retrieval_limit)
        if not retrieved or retrieved[0].similarity < self._settings.retrieval_min_similarity:
            # No DB match — answer from Claude's general knowledge
            prompt = build_prompt(
                question=question,
                language=language,
                contexts=[],
                support_mode="none",
            )
            answer = await self._generator.generate(prompt)
            answer = f"{build_general_knowledge_prefix(language)}\n\n{answer}".strip()
            response = AssistantResponse(
                conversation_id=conversation_value,
                message_id=uuid4(),
                language=language,
                answer=answer,
                citations=[],
                kind="general-knowledge",
            )
            return GeneratedReply(response=response, kind="general-knowledge", retrieved_chunks=[])

        support_mode = (
            "weak"
            if retrieved[0].similarity < self._settings.retrieval_weak_similarity
            else "strong"
        )
        cited_chunks = retrieved[: min(3, len(retrieved))]
        prompt = build_prompt(
            question=question,
            language=language,
            contexts=cited_chunks,
            support_mode=support_mode,
        )
        answer = await self._generator.generate(prompt)
        if support_mode == "weak":
            answer = f"{build_weak_support_prefix(language)}\n\n{answer}".strip()
            kind = "limited-support"
        else:
            kind = "answer"

        response = AssistantResponse(
            conversation_id=conversation_value,
            message_id=uuid4(),
            language=language,
            answer=answer,
            citations=self._build_citations(cited_chunks),
            kind=kind,
        )
        return GeneratedReply(response=response, kind=kind, retrieved_chunks=cited_chunks)

    async def handle_chat(self, *, user_id: str, request: ChatRequest) -> GeneratedReply:
        if self._repository is None:
            raise RuntimeError("Chat repository is required for persisted chat handling")

        provisional_language = detect_language(request.question)
        conversation_id = self._repository.ensure_conversation(
            user_id=user_id,
            language=provisional_language,
            title_seed=request.question,
            conversation_id=str(request.conversation_id) if request.conversation_id else None,
            create_new=request.create_conversation,
        )
        self._repository.add_message(
            conversation_id=conversation_id,
            role="user",
            content=request.question,
            language=provisional_language,
        )

        generated = await self.generate_reply(
            question=request.question,
            conversation_id=str(conversation_id),
        )
        assistant_message_id = self._repository.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=generated.response.answer,
            language=generated.response.language,
        )
        self._repository.add_citations(
            message_id=assistant_message_id,
            citations=generated.response.citations,
        )
        generated.response = generated.response.model_copy(
            update={
                "conversation_id": conversation_id,
                "message_id": assistant_message_id,
            }
        )
        return generated

    def _build_citations(self, chunks: list[RetrievedChunk]) -> list[CitationRecord]:
        citations: list[CitationRecord] = []
        for index, chunk in enumerate(chunks, start=1):
            citations.append(
                CitationRecord(
                    index=index,
                    document_id=chunk.document_id,
                    title=chunk.title,
                    agency=chunk.agency,
                    source_url=chunk.source_url,
                    excerpt=chunk.chunk_text,
                    chunk_index=chunk.chunk_index,
                )
            )
        return citations
