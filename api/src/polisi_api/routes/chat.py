"""Streaming chat route."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from polisi_api.auth import AuthenticatedUser
from polisi_api.dependencies import get_chat_service
from polisi_api.models import ChatRequest, StreamingEventEnvelope
from polisi_api.ratelimit import check_rate_limit

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("")
async def create_chat_completion(
    request: ChatRequest,
    user: AuthenticatedUser = Depends(check_rate_limit),
    service=Depends(get_chat_service),
) -> StreamingResponse:
    generated = await service.handle_chat(user_id=user.user_id, request=request)
    events = list(_iter_stream_events(generated.response))
    return StreamingResponse(
        (event.model_dump_json() + "\n" for event in events),
        media_type="application/x-ndjson",
    )


def _iter_stream_events(response) -> Iterator[StreamingEventEnvelope]:
    yield StreamingEventEnvelope(
        event="conversation",
        conversation_id=response.conversation_id,
        message_id=response.message_id,
    )
    yield StreamingEventEnvelope(
        event="message-start",
        conversation_id=response.conversation_id,
        message_id=response.message_id,
    )
    for chunk in _chunk_answer(response.answer):
        yield StreamingEventEnvelope(
            event="message-delta",
            conversation_id=response.conversation_id,
            message_id=response.message_id,
            delta=chunk,
        )
    yield StreamingEventEnvelope(
        event="message-complete",
        conversation_id=response.conversation_id,
        message_id=response.message_id,
        response=response,
    )
    yield StreamingEventEnvelope(
        event="done",
        conversation_id=response.conversation_id,
        message_id=response.message_id,
    )


def _chunk_answer(answer: str) -> Iterator[str]:
    words = answer.split()
    for index in range(0, len(words), 8):
        yield " ".join(words[index : index + 8]) + (" " if index + 8 < len(words) else "")
