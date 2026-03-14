"""Core chat behavior for retrieval-grounded answers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from anthropic import AsyncAnthropic, RateLimitError

from polisi_api.config import Settings
from polisi_api.models import AssistantResponse, ChatRequest, CitationRecord

from .datagov import (
    CATALOG_BY_ID,
    CatalogEntry,
    DataGovMyClient,
    build_tool_definition,
    execute_tool_call,
    find_catalog_match,
)
from .detector import detect_language, extract_agency, needs_clarification
from .prompting import (
    PromptPackage,
    build_clarification_text,
    build_general_knowledge_prefix,
    build_prompt,
    build_weak_support_prefix,
)
from .repository import ChatRepository
from .retrieval import RetrievalFilters, RetrievedChunk, Retriever


class TextGenerator(Protocol):
    async def generate(self, prompt: PromptPackage) -> str: ...


@dataclass
class GeneratedReply:
    response: AssistantResponse
    kind: str
    retrieved_chunks: list[RetrievedChunk]


class AnthropicTextGenerator:
    """LLM generator with optional data.gov.my tool use.

    When *datagov_client* is provided, Claude receives a
    ``query_government_data`` tool and can call it mid-generation to
    fetch live Malaysian government statistics.  The tool-use loop runs
    at most ``_MAX_TOOL_ROUNDS`` times to prevent run-away calls.
    """

    _MAX_TOOL_ROUNDS = 3

    def __init__(
        self,
        settings: Settings,
        *,
        datagov_client: DataGovMyClient | None = None,
    ) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key or "")
        self._model = settings.anthropic_model
        self._datagov = datagov_client
        self._tool_def = build_tool_definition() if datagov_client else None

    async def generate(self, prompt: PromptPackage) -> str:
        tools = [self._tool_def] if self._tool_def else []
        messages: list[dict] = [{"role": "user", "content": prompt.user}]

        try:
            for _round in range(self._MAX_TOOL_ROUNDS + 1):
                kwargs: dict = dict(
                    model=self._model,
                    max_tokens=1200,
                    system=prompt.system,
                    messages=messages,
                )
                if tools:
                    kwargs["tools"] = tools

                response = await self._client.messages.create(**kwargs)

                # If no tool use requested, extract text and return
                if response.stop_reason != "tool_use":
                    text_parts: list[str] = []
                    for block in response.content:
                        if getattr(block, "type", None) == "text":
                            text_parts.append(block.text)
                    return "".join(text_parts).strip()

                # Process tool calls
                tool_results: list[dict] = []
                for block in response.content:
                    if getattr(block, "type", None) == "tool_use":
                        result_text = await self._handle_tool_call(
                            block.name, block.input
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_text,
                        })

                # Append assistant response + tool results for next round
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

            # Exhausted rounds — extract whatever text we have
            return "[Data retrieval completed — see above results.]"

        except RateLimitError:
            return "[Rate limit reached — please try again in a moment.]"

    async def _handle_tool_call(self, name: str, tool_input: dict) -> str:
        if name == "query_government_data" and self._datagov:
            return await execute_tool_call(self._datagov, tool_input)
        return f"Unknown tool: {name}"


class ChatService:
    def __init__(
        self,
        *,
        settings: Settings,
        retriever: Retriever,
        generator: TextGenerator,
        repository: ChatRepository | None = None,
        datagov_client: DataGovMyClient | None = None,
    ) -> None:
        self._settings = settings
        self._retriever = retriever
        self._generator = generator
        self._repository = repository
        self._datagov = datagov_client or DataGovMyClient(api_token=settings.datagov_api_token)

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

        # Extract agency filter from the question when possible
        agency_filter = extract_agency(question)
        filters = RetrievalFilters(agency=agency_filter) if agency_filter else None

        retrieved = await self._retriever.retrieve(
            question, limit=self._settings.retrieval_limit, filters=filters,
        )

        # Check if any retrieved chunks match a data.gov.my catalog entry
        live_data_blocks: list[str] = []
        datagov_entries: list[CatalogEntry] = []
        seen_ids: set[str] = set()
        for chunk in retrieved:
            if chunk.metadata:
                entry = find_catalog_match(chunk.metadata)
                if entry and entry.dataset_id not in seen_ids:
                    seen_ids.add(entry.dataset_id)
                    datagov_entries.append(entry)

        # Fetch live data for matched datasets
        for entry in datagov_entries:
            rows = await self._datagov.fetch_dataset(entry)
            block = self._datagov.format_rows_for_context(entry, rows)
            live_data_blocks.append(block)

        top_similarity = retrieved[0].effective_similarity if retrieved else 0.0
        if not retrieved or top_similarity < self._settings.retrieval_min_similarity:
            if live_data_blocks:
                # No strong document match, but we have live data
                prompt = build_prompt(
                    question=question,
                    language=language,
                    contexts=[],
                    support_mode="none",
                    live_data_blocks=live_data_blocks,
                )
                answer = await self._generator.generate(prompt)
                response = AssistantResponse(
                    conversation_id=conversation_value,
                    message_id=uuid4(),
                    language=language,
                    answer=answer,
                    citations=self._build_datagov_citations(datagov_entries),
                    kind="answer",
                )
                return GeneratedReply(response=response, kind="answer", retrieved_chunks=[])

            # No DB match and no live data — answer from Claude's general knowledge
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
            if top_similarity < self._settings.retrieval_weak_similarity
            else "strong"
        )
        cited_chunks = retrieved[: min(3, len(retrieved))]
        prompt = build_prompt(
            question=question,
            language=language,
            contexts=cited_chunks,
            support_mode=support_mode,
            live_data_blocks=live_data_blocks,
        )
        answer = await self._generator.generate(prompt)
        if support_mode == "weak":
            answer = f"{build_weak_support_prefix(language)}\n\n{answer}".strip()
            kind = "limited-support"
        else:
            kind = "answer"

        citations = self._build_citations(cited_chunks)
        if datagov_entries:
            citations.extend(self._build_datagov_citations(datagov_entries, start_index=len(citations) + 1))

        response = AssistantResponse(
            conversation_id=conversation_value,
            message_id=uuid4(),
            language=language,
            answer=answer,
            citations=citations,
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

    def _build_datagov_citations(
        self,
        entries: list[CatalogEntry],
        start_index: int = 1,
    ) -> list[CitationRecord]:
        citations: list[CitationRecord] = []
        for offset, entry in enumerate(entries):
            citations.append(
                CitationRecord(
                    index=start_index + offset,
                    title=entry.title_en,
                    agency="data.gov.my",
                    source_url=f"https://data.gov.my/data-catalogue/{entry.dataset_id}",
                    excerpt=f"Live data from {entry.endpoint} (id={entry.dataset_id})",
                )
            )
        return citations
