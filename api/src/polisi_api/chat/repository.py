"""Conversation persistence for chat sessions and citations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

import psycopg

from polisi_api.models import CitationRecord, ConversationDetail, ConversationMessage, ConversationSummary


@dataclass(frozen=True)
class PersistedAssistantTurn:
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID


class ChatRepository(Protocol):
    def ensure_conversation(
        self,
        *,
        user_id: str,
        language: str,
        title_seed: str,
        conversation_id: str | None,
        create_new: bool,
    ) -> UUID: ...

    def add_message(self, *, conversation_id: UUID, role: str, content: str, language: str) -> UUID: ...

    def add_citations(self, *, message_id: UUID, citations: list[CitationRecord]) -> None: ...

    def list_conversations(self, *, user_id: str) -> list[ConversationSummary]: ...

    def get_conversation_detail(self, *, user_id: str, conversation_id: str) -> ConversationDetail | None: ...

    def get_recent_messages(self, *, conversation_id: str, limit: int = 6) -> list[tuple[str, str]]: ...

    def update_conversation(
        self,
        *,
        conversation_id: str,
        user_id: str,
        title: str | None = None,
        pinned: bool | None = None,
    ) -> bool: ...

    def delete_conversation(self, *, conversation_id: str, user_id: str) -> bool: ...


class PostgresChatRepository:
    def __init__(self, db_url: str) -> None:
        self._db_url = db_url

    def ensure_conversation(
        self,
        *,
        user_id: str,
        language: str,
        title_seed: str,
        conversation_id: str | None,
        create_new: bool,
    ) -> UUID:
        with psycopg.connect(self._db_url) as conn:
            if conversation_id:
                row = conn.execute(
                    """
                    select id
                    from public.conversations
                    where id = %s and user_id = %s
                    """,
                    (conversation_id, user_id),
                ).fetchone()
                if row is None:
                    raise ValueError("Conversation not found for current user")
                return row[0]
            if not create_new:
                raise ValueError("conversation_id or create_conversation=true is required")
            row = conn.execute(
                """
                insert into public.conversations (user_id, title, language)
                values (%s, %s, %s)
                returning id
                """,
                (user_id, _title_from_seed(title_seed), language),
            ).fetchone()
            conn.commit()
            return row[0]

    def add_message(self, *, conversation_id: UUID, role: str, content: str, language: str) -> UUID:
        with psycopg.connect(self._db_url) as conn:
            row = conn.execute(
                """
                insert into public.messages (conversation_id, role, content, language)
                values (%s, %s, %s, %s)
                returning id
                """,
                (conversation_id, role, content, language),
            ).fetchone()
            conn.execute(
                """
                update public.conversations
                set language = coalesce(language, %s), updated_at = timezone('utc', now())
                where id = %s
                """,
                (language, conversation_id),
            )
            conn.commit()
            return row[0]

    def add_citations(self, *, message_id: UUID, citations: list[CitationRecord]) -> None:
        with psycopg.connect(self._db_url) as conn:
            for citation in citations:
                conn.execute(
                    """
                    insert into public.citations (
                      message_id, document_id, citation_index, source_url, title, agency, excerpt, published_at
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        message_id,
                        citation.document_id,
                        citation.index,
                        citation.source_url,
                        citation.title,
                        citation.agency,
                        citation.excerpt,
                        citation.published_at,
                    ),
                )
            conn.commit()

    def list_conversations(self, *, user_id: str) -> list[ConversationSummary]:
        with psycopg.connect(self._db_url) as conn:
            # Try query with pinned column; fall back if it doesn't exist yet.
            try:
                rows = conn.execute(
                    """
                    select c.id, c.title, c.language, c.created_at, c.updated_at,
                           count(m.id) as message_count, coalesce(c.pinned, false) as pinned
                    from public.conversations c
                    left join public.messages m on m.conversation_id = c.id
                    where c.user_id = %s
                    group by c.id
                    order by c.pinned desc nulls last, c.updated_at desc, c.created_at desc
                    """,
                    (user_id,),
                ).fetchall()
                return [
                    ConversationSummary(
                        id=row[0],
                        title=row[1],
                        language=row[2],
                        created_at=row[3],
                        updated_at=row[4],
                        message_count=int(row[5]),
                        pinned=bool(row[6]),
                    )
                    for row in rows
                ]
            except psycopg.errors.UndefinedColumn:
                conn.rollback()
                rows = conn.execute(
                    """
                    select c.id, c.title, c.language, c.created_at, c.updated_at, count(m.id) as message_count
                    from public.conversations c
                    left join public.messages m on m.conversation_id = c.id
                    where c.user_id = %s
                    group by c.id
                    order by c.updated_at desc, c.created_at desc
                    """,
                    (user_id,),
                ).fetchall()
                return [
                    ConversationSummary(
                        id=row[0],
                        title=row[1],
                        language=row[2],
                        created_at=row[3],
                        updated_at=row[4],
                        message_count=int(row[5]),
                        pinned=False,
                    )
                    for row in rows
                ]

    def get_recent_messages(self, *, conversation_id: str, limit: int = 6) -> list[tuple[str, str]]:
        with psycopg.connect(self._db_url) as conn:
            rows = conn.execute(
                """
                select role, content
                from public.messages
                where conversation_id = %s
                order by created_at desc
                limit %s
                """,
                (conversation_id, limit),
            ).fetchall()
        # Reverse so oldest first
        rows.reverse()
        return [(row[0], row[1]) for row in rows]

    def get_conversation_detail(self, *, user_id: str, conversation_id: str) -> ConversationDetail | None:
        with psycopg.connect(self._db_url) as conn:
            conversation = conn.execute(
                """
                select id, title, language, created_at, updated_at
                from public.conversations
                where id = %s and user_id = %s
                """,
                (conversation_id, user_id),
            ).fetchone()
            if conversation is None:
                return None
            message_rows = conn.execute(
                """
                select m.id, m.role, m.content, m.language, m.created_at,
                  c.document_id, c.citation_index, c.title, c.agency, c.source_url, c.excerpt, c.published_at
                from public.messages m
                left join public.citations c on c.message_id = m.id
                where m.conversation_id = %s
                order by m.created_at asc, c.citation_index asc
                """,
                (conversation_id,),
            ).fetchall()
        return _conversation_detail_from_rows(conversation, message_rows)

    def update_conversation(
        self,
        *,
        conversation_id: str,
        user_id: str,
        title: str | None = None,
        pinned: bool | None = None,
    ) -> bool:
        with psycopg.connect(self._db_url) as conn:
            # Verify ownership
            row = conn.execute(
                "select id from public.conversations where id = %s and user_id = %s",
                (conversation_id, user_id),
            ).fetchone()
            if row is None:
                return False

            if title is not None:
                conn.execute(
                    "update public.conversations set title = %s, updated_at = timezone('utc', now()) where id = %s",
                    (title, conversation_id),
                )
            if pinned is not None:
                try:
                    conn.execute(
                        "update public.conversations set pinned = %s, updated_at = timezone('utc', now()) where id = %s",
                        (pinned, conversation_id),
                    )
                except psycopg.errors.UndefinedColumn:
                    # pinned column doesn't exist yet — silently skip
                    conn.rollback()
            conn.commit()
            return True

    def delete_conversation(self, *, conversation_id: str, user_id: str) -> bool:
        with psycopg.connect(self._db_url) as conn:
            row = conn.execute(
                "select id from public.conversations where id = %s and user_id = %s",
                (conversation_id, user_id),
            ).fetchone()
            if row is None:
                return False
            # Delete citations first (FK: citations -> messages -> conversations)
            conn.execute(
                """
                delete from public.citations
                where message_id in (
                    select id from public.messages where conversation_id = %s
                )
                """,
                (conversation_id,),
            )
            conn.execute(
                "delete from public.messages where conversation_id = %s",
                (conversation_id,),
            )
            conn.execute(
                "delete from public.conversations where id = %s",
                (conversation_id,),
            )
            conn.commit()
            return True

    def _try_read_pinned(self, conn: psycopg.Connection, conversation_id: object) -> bool:
        """Try to read the pinned column; return False if it doesn't exist."""
        try:
            row = conn.execute(
                "select pinned from public.conversations where id = %s",
                (conversation_id,),
            ).fetchone()
            return bool(row[0]) if row else False
        except psycopg.errors.UndefinedColumn:
            conn.rollback()
            return False


class InMemoryChatRepository:
    def __init__(self) -> None:
        self.conversations: dict[UUID, dict[str, object]] = {}
        self.messages: list[dict[str, object]] = []
        self.citations: list[dict[str, object]] = []

    def ensure_conversation(
        self,
        *,
        user_id: str,
        language: str,
        title_seed: str,
        conversation_id: str | None,
        create_new: bool,
    ) -> UUID:
        if conversation_id:
            conversation_uuid = UUID(conversation_id)
            conversation = self.conversations.get(conversation_uuid)
            if conversation is None or conversation["user_id"] != user_id:
                raise ValueError("Conversation not found for current user")
            return conversation_uuid
        if not create_new:
            raise ValueError("conversation_id or create_conversation=true is required")
        conversation_uuid = uuid4()
        now = datetime.now(UTC)
        self.conversations[conversation_uuid] = {
            "id": conversation_uuid,
            "user_id": user_id,
            "title": _title_from_seed(title_seed),
            "language": language,
            "created_at": now,
            "updated_at": now,
        }
        return conversation_uuid

    def add_message(self, *, conversation_id: UUID, role: str, content: str, language: str) -> UUID:
        message_id = uuid4()
        now = datetime.now(UTC)
        self.messages.append(
            {
                "id": message_id,
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "language": language,
                "created_at": now,
            }
        )
        conversation = self.conversations[conversation_id]
        conversation["updated_at"] = now
        conversation["language"] = conversation.get("language") or language
        return message_id

    def add_citations(self, *, message_id: UUID, citations: list[CitationRecord]) -> None:
        for citation in citations:
            self.citations.append(
                {
                    "message_id": message_id,
                    "document_id": citation.document_id,
                    "citation_index": citation.index,
                    "title": citation.title,
                    "agency": citation.agency,
                    "source_url": citation.source_url,
                    "excerpt": citation.excerpt,
                    "published_at": citation.published_at,
                }
            )

    def list_conversations(self, *, user_id: str) -> list[ConversationSummary]:
        matches = [
            conversation
            for conversation in self.conversations.values()
            if conversation["user_id"] == user_id
        ]
        # Sort pinned first, then by updated_at descending
        matches.sort(
            key=lambda item: (
                not item.get("pinned", False),
                item["updated_at"],
            ),
            reverse=False,
        )
        # Secondary sort: within each pinned group, newest first
        matches.sort(
            key=lambda item: (not item.get("pinned", False), item["updated_at"]),
        )
        # Simpler approach: pinned first (desc=True), then updated_at desc
        matches.sort(key=lambda item: item["updated_at"], reverse=True)
        matches.sort(key=lambda item: item.get("pinned", False), reverse=True)
        summaries: list[ConversationSummary] = []
        for conversation in matches:
            message_count = sum(
                1 for message in self.messages if message["conversation_id"] == conversation["id"]
            )
            summaries.append(
                ConversationSummary(
                    id=conversation["id"],
                    title=conversation["title"],
                    language=conversation["language"],
                    created_at=conversation["created_at"],
                    updated_at=conversation["updated_at"],
                    message_count=message_count,
                    pinned=bool(conversation.get("pinned", False)),
                )
            )
        return summaries

    def update_conversation(
        self,
        *,
        conversation_id: str,
        user_id: str,
        title: str | None = None,
        pinned: bool | None = None,
    ) -> bool:
        conversation_uuid = UUID(conversation_id)
        conversation = self.conversations.get(conversation_uuid)
        if conversation is None or conversation["user_id"] != user_id:
            return False
        if title is not None:
            conversation["title"] = title
            conversation["updated_at"] = datetime.now(UTC)
        if pinned is not None:
            conversation["pinned"] = pinned
            conversation["updated_at"] = datetime.now(UTC)
        return True

    def delete_conversation(self, *, conversation_id: str, user_id: str) -> bool:
        conversation_uuid = UUID(conversation_id)
        conversation = self.conversations.get(conversation_uuid)
        if conversation is None or conversation["user_id"] != user_id:
            return False
        # Remove citations for messages in this conversation
        message_ids = {
            msg["id"] for msg in self.messages if msg["conversation_id"] == conversation_uuid
        }
        self.citations = [c for c in self.citations if c["message_id"] not in message_ids]
        self.messages = [m for m in self.messages if m["conversation_id"] != conversation_uuid]
        del self.conversations[conversation_uuid]
        return True

    def get_recent_messages(self, *, conversation_id: str, limit: int = 6) -> list[tuple[str, str]]:
        conversation_uuid = UUID(conversation_id)
        convo_messages = [
            msg for msg in self.messages
            if msg["conversation_id"] == conversation_uuid
        ]
        # Sort by created_at ascending, then take last `limit`
        convo_messages.sort(key=lambda m: m["created_at"])
        recent = convo_messages[-limit:]
        return [(str(msg["role"]), str(msg["content"])) for msg in recent]

    def get_conversation_detail(self, *, user_id: str, conversation_id: str) -> ConversationDetail | None:
        conversation_uuid = UUID(conversation_id)
        conversation = self.conversations.get(conversation_uuid)
        if conversation is None or conversation["user_id"] != user_id:
            return None
        message_rows = []
        for message in self.messages:
            if message["conversation_id"] != conversation_uuid:
                continue
            citation_rows = [
                citation for citation in self.citations if citation["message_id"] == message["id"]
            ] or [None]
            for citation in citation_rows:
                message_rows.append(
                    (
                        message["id"],
                        message["role"],
                        message["content"],
                        message["language"],
                        message["created_at"],
                        citation["document_id"] if citation else None,
                        citation["citation_index"] if citation else None,
                        citation["title"] if citation else None,
                        citation["agency"] if citation else None,
                        citation["source_url"] if citation else None,
                        citation["excerpt"] if citation else None,
                        citation["published_at"] if citation else None,
                    )
                )
        return _conversation_detail_from_rows(
            (
                conversation["id"],
                conversation["title"],
                conversation["language"],
                conversation["created_at"],
                conversation["updated_at"],
            ),
            message_rows,
        )


def _conversation_detail_from_rows(
    conversation: tuple[object, ...], message_rows: list[tuple[object, ...]]
) -> ConversationDetail:
    messages: dict[UUID, ConversationMessage] = {}
    for row in message_rows:
        message_id = row[0]
        if message_id not in messages:
            messages[message_id] = ConversationMessage(
                id=message_id,
                role=row[1],
                content=row[2],
                language=row[3],
                created_at=row[4],
                citations=[],
            )
        if row[6] is not None:
            messages[message_id].citations.append(
                CitationRecord(
                    index=int(row[6]),
                    document_id=row[5],
                    title=row[7],
                    agency=row[8],
                    source_url=row[9],
                    excerpt=row[10],
                    published_at=row[11],
                )
            )
    return ConversationDetail(
        id=conversation[0],
        title=conversation[1],
        language=conversation[2],
        created_at=conversation[3],
        updated_at=conversation[4],
        messages=list(messages.values()),
    )


def _title_from_seed(seed: str) -> str:
    normalized = " ".join(seed.split())
    return normalized[:80]
