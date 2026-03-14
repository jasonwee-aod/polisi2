"""FastAPI application entrypoint for PolisiGPT."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from polisi_api.config import Settings, get_settings
from polisi_api.models import StreamingEventEnvelope
from polisi_api.routes.chat import router as chat_router
from polisi_api.routes.conversations import router as conversations_router
from polisi_api.routes.feedback import router as feedback_router
from polisi_api.routes.skills import router as skills_router
from polisi_api.routes.usage import router as usage_router


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
    app.include_router(conversations_router)
    app.include_router(feedback_router)
    app.include_router(skills_router)
    app.include_router(usage_router)

    @app.get(
        "/api/contracts/chat-stream",
        response_model=StreamingEventEnvelope,
        summary="Reserved chat stream event contract",
    )
    async def chat_stream_contract() -> StreamingEventEnvelope:
        return StreamingEventEnvelope(event="done")

    return app


app = create_app()
