"""Dependency helpers for API routers."""

from __future__ import annotations

from functools import lru_cache

from anthropic import AsyncAnthropic
from fastapi import Depends

from polisi_api.chat.datagov import DataGovMyClient
from polisi_api.chat.feedback import FeedbackRepository
from polisi_api.chat.reranker import ClaudeReranker, NoOpReranker, Reranker
from polisi_api.chat.repository import PostgresChatRepository
from polisi_api.chat.retrieval import HybridPostgresRetriever
from polisi_api.chat.service import AnthropicTextGenerator, ChatService
from polisi_api.config import Settings, get_settings


@lru_cache(maxsize=4)
def get_chat_repository(db_url: str) -> PostgresChatRepository:
    return PostgresChatRepository(db_url)


def get_repository(settings: Settings = Depends(get_settings)) -> PostgresChatRepository:
    return get_chat_repository(settings.supabase_db_url)


@lru_cache(maxsize=4)
def get_retriever(settings_key: tuple[str, str | None, int, float, float]) -> HybridPostgresRetriever:
    db_url, openai_key, limit, min_similarity, weak_similarity = settings_key
    settings = Settings.from_env(
        {
            "SUPABASE_URL": "https://dependency.local",
            "SUPABASE_DB_URL": db_url,
            "OPENAI_API_KEY": openai_key or "",
            "RETRIEVAL_LIMIT": str(limit),
            "RETRIEVAL_MIN_SIMILARITY": str(min_similarity),
            "RETRIEVAL_WEAK_SIMILARITY": str(weak_similarity),
        }
    )
    return HybridPostgresRetriever(settings)


def get_chat_service(settings: Settings = Depends(get_settings)) -> ChatService:
    retriever = get_retriever(
        (
            settings.supabase_db_url,
            settings.openai_api_key,
            settings.retrieval_limit,
            settings.retrieval_min_similarity,
            settings.retrieval_weak_similarity,
        )
    )
    repository = get_repository(settings)
    datagov_client = DataGovMyClient(api_token=settings.datagov_api_token)
    generator = AnthropicTextGenerator(settings, datagov_client=datagov_client)
    feedback_repo = FeedbackRepository(settings.supabase_db_url)

    # Build shared Anthropic client for reranking, query expansion, reformulation
    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key or "")

    reranker: Reranker
    if settings.enable_reranking:
        reranker = ClaudeReranker(anthropic_client, model=settings.reranker_model)
    else:
        reranker = NoOpReranker()

    return ChatService(
        settings=settings,
        retriever=retriever,
        generator=generator,
        repository=repository,
        datagov_client=datagov_client,
        feedback_repo=feedback_repo,
        reranker=reranker,
        anthropic_client=anthropic_client,
    )
