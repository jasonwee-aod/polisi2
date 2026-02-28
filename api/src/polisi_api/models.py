"""Typed request and response contracts for the Polisi API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

LanguageCode = Literal["ms", "en"]
ConversationRole = Literal["system", "user", "assistant"]
AssistantResponseKind = Literal["answer", "clarification", "limited-support", "no-information"]
StreamEventType = Literal["conversation", "message-start", "message-delta", "message-complete", "done"]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    conversation_id: UUID | None = None
    create_conversation: bool = False
    language_hint: LanguageCode | None = None


class CitationRecord(BaseModel):
    index: int = Field(ge=1)
    document_id: UUID | None = None
    title: str
    agency: str
    source_url: str | None = None
    excerpt: str
    published_at: date | None = None
    chunk_index: int | None = None


class AssistantResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    language: LanguageCode
    answer: str
    citations: list[CitationRecord]
    kind: AssistantResponseKind = "answer"


class StreamingEventEnvelope(BaseModel):
    event: StreamEventType
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    delta: str | None = None
    response: AssistantResponse | None = None


class ConversationMessage(BaseModel):
    id: UUID
    role: ConversationRole
    content: str
    language: LanguageCode | None = None
    created_at: datetime
    citations: list[CitationRecord] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    id: UUID
    title: str | None = None
    language: LanguageCode | None = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ConversationDetail(BaseModel):
    id: UUID
    title: str | None = None
    language: LanguageCode | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessage]
