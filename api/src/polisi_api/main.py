"""FastAPI application entrypoint for PolisiGPT."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from polisi_api.auth import AuthenticatedUser, get_current_user
from polisi_api.config import Settings, get_settings
from polisi_api.models import (
    AssistantResponse,
    ChatRequest,
    CitationRecord,
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
    StreamingEventEnvelope,
)
from polisi_api.routes.chat import router as chat_router


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()

    app = FastAPI(
        title=runtime_settings.api_title,
        version=runtime_settings.api_version,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.api_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: runtime_settings

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        return {
            "status": "ok",
            "environment": runtime_settings.api_env,
            "service": "polisi-api",
        }

    app.include_router(chat_router)

    @app.get(
        "/api/contracts/chat-stream",
        response_model=StreamingEventEnvelope,
        summary="Reserved chat stream event contract",
    )
    async def chat_stream_contract() -> StreamingEventEnvelope:
        return StreamingEventEnvelope(event="done")

    @app.get(
        "/api/conversations",
        response_model=list[ConversationSummary],
        summary="Reserved conversation list endpoint",
    )
    async def conversations_contract(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> list[ConversationSummary]:
        now = datetime.now(UTC)
        return [
            ConversationSummary(
                id=uuid4(),
                title=f"Conversation for {user.user_id[:8]}",
                language="en",
                created_at=now,
                updated_at=now,
                message_count=0,
            )
        ]

    @app.get(
        "/api/conversations/{conversation_id}",
        response_model=ConversationDetail,
        summary="Reserved conversation detail endpoint",
    )
    async def conversation_detail_contract(
        conversation_id: UUID,
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> ConversationDetail:
        now = datetime.now(UTC)
        return ConversationDetail(
            id=conversation_id,
            title=f"Conversation for {user.user_id[:8]}",
            language="en",
            created_at=now,
            updated_at=now,
            messages=[
                ConversationMessage(
                    id=uuid4(),
                    role="assistant",
                    content="Reserved history contract.[1]",
                    language="en",
                    created_at=now,
                    citations=[
                        CitationRecord(
                            index=1,
                            title="Contract Placeholder",
                            agency="PolisiGPT",
                            source_url=f"{runtime_settings.supabase_url}/contract-placeholder",
                            excerpt="Conversation history shape placeholder.",
                        )
                    ],
                )
            ],
        )

    return app


app = create_app()
