"""Typed request and response contracts for the Polisi API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

LanguageCode = Literal["ms", "en"]
ConversationRole = Literal["system", "user", "assistant"]
AssistantResponseKind = Literal["answer", "clarification", "limited-support", "no-information", "general-knowledge"]
StreamEventType = Literal["conversation", "message-start", "message-delta", "message-complete", "done"]

# Maximum base64 size per attachment (~10 MB base64 ≈ 7.5 MB file).
MAX_ATTACHMENT_BASE64_SIZE = 10 * 1024 * 1024


class FileAttachment(BaseModel):
    """A file uploaded alongside a chat message."""

    filename: str
    content_type: str  # e.g. "application/pdf", "image/png", "text/plain"
    data: str  # base64-encoded file content

    @model_validator(mode="after")
    def _check_size(self) -> FileAttachment:
        if len(self.data) > MAX_ATTACHMENT_BASE64_SIZE:
            raise ValueError(
                f"Attachment '{self.filename}' exceeds the 10 MB limit "
                f"({len(self.data)} bytes base64)."
            )
        return self


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    conversation_id: UUID | None = None
    create_conversation: bool = False
    language_hint: LanguageCode | None = None
    skill: str | None = None
    attachments: list[FileAttachment] = Field(default_factory=list)


class SkillInfo(BaseModel):
    id: str
    name: str
    name_ms: str
    description: str
    description_ms: str
    icon: str


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
    pinned: bool = False


class ConversationDetail(BaseModel):
    id: UUID
    title: str | None = None
    language: LanguageCode | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessage]


class ConversationUpdate(BaseModel):
    title: str | None = None
    pinned: bool | None = None
