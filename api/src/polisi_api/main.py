"""FastAPI application entrypoint for PolisiGPT."""

from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from polisi_api.config import Settings, get_settings


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

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        return {
            "status": "ok",
            "environment": runtime_settings.api_env,
            "service": "polisi-api",
        }

    @app.post("/api/chat", summary="Reserved chat contract endpoint")
    async def chat_contract() -> dict[str, str]:
        return {"status": "not-implemented"}

    @app.get("/api/conversations", summary="Reserved conversation list endpoint")
    async def conversations_contract() -> list[dict[str, str]]:
        return []

    @app.get("/api/conversations/{conversation_id}", summary="Reserved conversation detail endpoint")
    async def conversation_detail_contract(conversation_id: UUID) -> dict[str, str]:
        return {"conversation_id": str(conversation_id), "status": "not-implemented"}

    return app


app = create_app()
