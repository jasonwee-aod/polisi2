"""Core chat behavior for retrieval-grounded answers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from anthropic import AsyncAnthropic

from polisi_api.config import Settings
from polisi_api.models import AssistantResponse, CitationRecord, LanguageCode

from .detector import detect_language, needs_clarification
from .prompting import (
    PromptPackage,
    build_clarification_text,
    build_no_information_text,
    build_prompt,
    build_weak_support_prefix,
)
from .retrieval import RetrievedChunk, Retriever


class TextGenerator(Protocol):
    async def generate(self, prompt: PromptPackage) -> str: ...


@dataclass(frozen=True)
class GeneratedReply:
    response: AssistantResponse
    kind: str
    retrieved_chunks: list[RetrievedChunk]


class AnthropicTextGenerator:
    def __init__(self, settings: Settings) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key or "")
        self._model = settings.anthropic_model

    async def generate(self, prompt: PromptPackage) -> str:
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


class ChatService:
    def __init__(
        self,
        *,
        settings: Settings,
        retriever: Retriever,
        generator: TextGenerator,
    ) -> None:
        self._settings = settings
        self._retriever = retriever
        self._generator = generator

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
            response = AssistantResponse(
                conversation_id=conversation_value,
                message_id=uuid4(),
                language=language,
                answer=build_no_information_text(language),
                citations=[],
                kind="no-information",
            )
            return GeneratedReply(response=response, kind="no-information", retrieved_chunks=[])

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
