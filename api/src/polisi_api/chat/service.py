"""Core chat behavior for retrieval-grounded answers."""

from __future__ import annotations

import asyncio
import logging
import time
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
    build_skill_prompt,
    build_weak_support_prefix,
)
from .feedback import FeedbackRepository
from .query_expansion import expand_query
from .reranker import Reranker
from .reformulation import reformulate_with_history
from .skills import SKILL_BY_ID
from .repository import ChatRepository
from .retrieval import (
    RetrievalFilters,
    RetrievedChunk,
    Retriever,
    apply_adaptive_cutoff,
    apply_metadata_boost,
    deduplicate_chunks,
)


logger = logging.getLogger("polisi.pipeline")


class TextGenerator(Protocol):
    async def generate(self, prompt: PromptPackage, *, max_tokens: int | None = None) -> str: ...


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

    async def generate(self, prompt: PromptPackage, *, max_tokens: int | None = None) -> str:
        tools = [self._tool_def] if self._tool_def else []
        messages: list[dict] = [{"role": "user", "content": prompt.user}]

        try:
            for _round in range(self._MAX_TOOL_ROUNDS + 1):
                kwargs: dict = dict(
                    model=self._model,
                    max_tokens=max_tokens or 1200,
                    system=prompt.system,
                    messages=messages,
                )
                if tools:
                    kwargs["tools"] = tools

                t0 = time.monotonic()
                logger.info("    LLM CALL round=%d model=%s max_tokens=%d tools=%d", _round, self._model, kwargs["max_tokens"], len(tools))
                response = await self._client.messages.create(**kwargs)
                logger.info(
                    "    LLM RESP round=%d: %.1fs stop=%s usage=%s",
                    _round, time.monotonic() - t0, response.stop_reason,
                    getattr(response, "usage", "n/a"),
                )

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
                        t_tool = time.monotonic()
                        logger.info("    TOOL CALL round=%d name=%s input=%r", _round, block.name, block.input)
                        result_text = await self._handle_tool_call(
                            block.name, block.input
                        )
                        logger.info("    TOOL DONE round=%d: %.1fs result_len=%d", _round, time.monotonic() - t_tool, len(result_text))
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_text,
                        })

                # Append assistant response + tool results for next round
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

            # Exhausted tool rounds — force a final call WITHOUT tools so the
            # model synthesises an answer from the data it already collected.
            logger.warning("    LLM exhausted %d tool rounds — forcing final answer", self._MAX_TOOL_ROUNDS)
            t0 = time.monotonic()
            final = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens or 1200,
                system=prompt.system,
                messages=messages,  # includes all prior tool results
            )
            logger.info("    LLM FINAL (no tools): %.1fs stop=%s", time.monotonic() - t0, final.stop_reason)
            text_parts: list[str] = []
            for block in final.content:
                if getattr(block, "type", None) == "text":
                    text_parts.append(block.text)
            return "".join(text_parts).strip() or "[Unable to generate a response — please try again.]"

        except RateLimitError:
            logger.warning("    LLM rate limited")
            return "[Rate limit reached — please try again in a moment.]"
        except Exception as exc:
            logger.exception("    LLM ERROR: %s", exc)
            raise

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
        feedback_repo: FeedbackRepository | None = None,
        reranker: Reranker | None = None,
        anthropic_client: AsyncAnthropic | None = None,
    ) -> None:
        self._settings = settings
        self._retriever = retriever
        self._generator = generator
        self._repository = repository
        self._datagov = datagov_client or DataGovMyClient(api_token=settings.datagov_api_token)
        self._feedback = feedback_repo
        self._reranker = reranker
        self._anthropic = anthropic_client

    async def generate_reply(
        self,
        *,
        question: str,
        conversation_id: str | None = None,
        skill: str | None = None,
        conversation_history: list[tuple[str, str]] | None = None,
    ) -> GeneratedReply:
        t_start = time.monotonic()
        language = detect_language(question)
        conversation_value = conversation_id or str(uuid4())
        skill_def = SKILL_BY_ID.get(skill) if skill else None

        logger.info(
            "PIPELINE START question=%r skill=%s language=%s",
            question[:80], skill, language,
        )

        # Skip clarification check when a skill is active — the user has a clear intent
        if not skill_def and needs_clarification(question):
            return self._make_reply(
                conversation_value=conversation_value, language=language,
                answer=build_clarification_text(language),
                citations=[], kind="clarification", chunks=[],
            )

        # --- [1.3] Conversation-aware reformulation ---
        retrieval_query = question
        if (
            conversation_history
            and self._anthropic
        ):
            t0 = time.monotonic()
            retrieval_query = await reformulate_with_history(
                question,
                conversation_history,
                self._anthropic,
                self._settings.query_expansion_model,
            )
            logger.info("  [1.3] reformulate: %.1fs query=%r", time.monotonic() - t0, retrieval_query[:80])

        # Extract agency filter from the question when possible
        agency_filter = extract_agency(question)
        filters = RetrievalFilters(agency=agency_filter) if agency_filter else None

        # --- [1.2] Query expansion with bilingual translation ---
        retrieval_limit = (
            self._settings.retrieval_prefetch_limit
            if self._reranker
            else self._settings.retrieval_limit
        )

        if (
            self._settings.enable_query_expansion
            and self._anthropic
            and hasattr(self._retriever, "retrieve_multi")
        ):
            t0 = time.monotonic()
            expanded_queries = await expand_query(
                retrieval_query,
                language,
                self._anthropic,
                self._settings.query_expansion_model,
            )
            logger.info("  [1.2] expand_query: %.1fs queries=%r", time.monotonic() - t0, expanded_queries)
            t0 = time.monotonic()
            retrieved = await self._retriever.retrieve_multi(
                expanded_queries, limit=retrieval_limit, filters=filters,
            )
            logger.info("  [1.2] retrieve_multi: %.1fs chunks=%d", time.monotonic() - t0, len(retrieved))
        else:
            t0 = time.monotonic()
            retrieved = await self._retriever.retrieve(
                retrieval_query, limit=retrieval_limit, filters=filters,
            )
            logger.info("  retrieve: %.1fs chunks=%d", time.monotonic() - t0, len(retrieved))

        # --- [3.2] Deduplicate chunks ---
        before_dedup = len(retrieved)
        retrieved = deduplicate_chunks(retrieved)
        logger.info("  [3.2] dedup: %d -> %d chunks", before_dedup, len(retrieved))

        # --- [1.1] Cross-encoder reranking ---
        if self._reranker and retrieved:
            t0 = time.monotonic()
            retrieved = await self._reranker.rerank(
                retrieval_query,
                retrieved,
                top_n=self._settings.reranker_top_n,
            )
            logger.info("  [1.1] rerank: %.1fs chunks=%d", time.monotonic() - t0, len(retrieved))

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

        # Fetch live data for matched datasets (concurrently)
        if datagov_entries:
            t0 = time.monotonic()
            fetch_results = await asyncio.gather(
                *(self._datagov.fetch_dataset(entry) for entry in datagov_entries)
            )
            for entry, rows in zip(datagov_entries, fetch_results):
                live_data_blocks.append(self._datagov.format_rows_for_context(entry, rows))
            logger.info("  datagov fetch: %.1fs datasets=%d", time.monotonic() - t0, len(datagov_entries))

        # --- [1.5] Metadata-boosted ranking ---
        retrieved = apply_metadata_boost(retrieved)

        # Filter out FTS-only results that are just keyword noise.
        # A real vector match has similarity > 0; FTS-only results have similarity=0
        # and only the fts_rank to go on.  Low fts_rank means shallow keyword overlap.
        has_vector_match = any(c.similarity > 0 for c in retrieved)
        if not has_vector_match:
            # FTS-only mode: only keep chunks with meaningful fts_rank
            before = len(retrieved)
            retrieved = [c for c in retrieved if c.fts_rank >= 0.1]
            if before != len(retrieved):
                logger.info("  FTS quality filter: %d -> %d chunks (dropped fts_rank < 0.1)", before, len(retrieved))

        top_similarity = retrieved[0].effective_similarity if retrieved else 0.0
        logger.info(
            "  top_similarity=%.3f chunks=%d has_vector=%s elapsed=%.1fs",
            top_similarity, len(retrieved), has_vector_match, time.monotonic() - t_start,
        )

        # --- Skill path: use the skill-specific prompt regardless of similarity tier ---
        if skill_def:
            cited_chunks = apply_adaptive_cutoff(
                retrieved,
                self._settings.retrieval_similarity_dropoff,
                max_chunks=self._settings.reranker_top_n,
            )
            prompt = build_skill_prompt(
                question=question, language=language,
                contexts=cited_chunks, skill=skill_def,
                live_data_blocks=live_data_blocks,
            )
            t0 = time.monotonic()
            logger.info("  GENERATE START skill=%s max_tokens=%d", skill, skill_def.max_tokens)
            answer = await self._generator.generate(prompt, max_tokens=skill_def.max_tokens)
            logger.info("  GENERATE DONE: %.1fs total_elapsed=%.1fs", time.monotonic() - t0, time.monotonic() - t_start)
            return self._make_reply(
                conversation_value=conversation_value, language=language, answer=answer,
                citations=self._build_all_citations(cited_chunks, datagov_entries),
                kind="answer", chunks=cited_chunks,
            )

        # --- Standard path (no skill selected) ---
        if not retrieved or top_similarity < self._settings.retrieval_min_similarity:
            # Log knowledge gap — the bot couldn't find indexed docs for this query
            self._log_knowledge_gap(
                question=question, language=language,
                conversation_id=conversation_value,
                gap_type="no_match" if not retrieved else "low_similarity",
                top_similarity=top_similarity,
            )

            if live_data_blocks:
                prompt = build_prompt(
                    question=question, language=language,
                    contexts=[], support_mode="none", live_data_blocks=live_data_blocks,
                )
                t0 = time.monotonic()
                logger.info("  GENERATE START mode=none+live_data")
                answer = await self._generator.generate(prompt)
                logger.info("  GENERATE DONE: %.1fs total_elapsed=%.1fs", time.monotonic() - t0, time.monotonic() - t_start)
                return self._make_reply(
                    conversation_value=conversation_value, language=language, answer=answer,
                    citations=self._build_datagov_citations(datagov_entries),
                    kind="answer", chunks=[],
                )

            prompt = build_prompt(
                question=question, language=language, contexts=[], support_mode="none",
            )
            t0 = time.monotonic()
            logger.info("  GENERATE START mode=general_knowledge")
            answer = await self._generator.generate(prompt)
            logger.info("  GENERATE DONE: %.1fs total_elapsed=%.1fs", time.monotonic() - t0, time.monotonic() - t_start)
            return self._make_reply(
                conversation_value=conversation_value, language=language, answer=answer,
                citations=[], kind="general-knowledge", chunks=[],
            )

        support_mode = (
            "weak" if top_similarity < self._settings.retrieval_weak_similarity else "strong"
        )
        # --- [3.3] Adaptive context window ---
        cited_chunks = apply_adaptive_cutoff(
            retrieved,
            self._settings.retrieval_similarity_dropoff,
            max_chunks=self._settings.reranker_top_n,
        )
        prompt = build_prompt(
            question=question, language=language,
            contexts=cited_chunks, support_mode=support_mode,
            live_data_blocks=live_data_blocks,
        )
        t0 = time.monotonic()
        logger.info("  GENERATE START mode=%s cited_chunks=%d", support_mode, len(cited_chunks))
        answer = await self._generator.generate(prompt)
        logger.info("  GENERATE DONE: %.1fs total_elapsed=%.1fs", time.monotonic() - t0, time.monotonic() - t_start)
        kind = "limited-support" if support_mode == "weak" else "answer"

        return self._make_reply(
            conversation_value=conversation_value, language=language, answer=answer,
            citations=self._build_all_citations(cited_chunks, datagov_entries),
            kind=kind, chunks=cited_chunks,
        )

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

        # Load conversation history for context-aware retrieval
        conversation_history: list[tuple[str, str]] | None = None
        if hasattr(self._repository, "get_recent_messages"):
            turns_limit = self._settings.conversation_context_turns * 2
            conversation_history = self._repository.get_recent_messages(
                conversation_id=str(conversation_id),
                limit=turns_limit,
            )

        generated = await self.generate_reply(
            question=request.question,
            conversation_id=str(conversation_id),
            skill=request.skill,
            conversation_history=conversation_history,
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

    def _make_reply(
        self,
        *,
        conversation_value: str,
        language: str,
        answer: str,
        citations: list[CitationRecord],
        kind: str,
        chunks: list[RetrievedChunk],
    ) -> GeneratedReply:
        response = AssistantResponse(
            conversation_id=conversation_value,
            message_id=uuid4(),
            language=language,
            answer=answer,
            citations=citations,
            kind=kind,
        )
        return GeneratedReply(response=response, kind=kind, retrieved_chunks=chunks)

    def _log_knowledge_gap(
        self,
        *,
        question: str,
        language: str,
        conversation_id: str | None,
        gap_type: str,
        top_similarity: float,
    ) -> None:
        if not self._feedback:
            return
        try:
            self._feedback.log_knowledge_gap(
                question=question,
                language=language,
                conversation_id=conversation_id,
                gap_type=gap_type,
                top_similarity=top_similarity,
            )
        except Exception:
            pass  # Non-critical — don't fail the chat response

    def _build_all_citations(
        self,
        chunks: list[RetrievedChunk],
        datagov_entries: list[CatalogEntry],
    ) -> list[CitationRecord]:
        citations = self._build_citations(chunks)
        if datagov_entries:
            citations.extend(self._build_datagov_citations(datagov_entries, start_index=len(citations) + 1))
        return citations

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
