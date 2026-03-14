"""Feedback persistence and knowledge gap tracking."""

from __future__ import annotations

from uuid import UUID

import psycopg


class FeedbackRepository:
    def __init__(self, db_url: str) -> None:
        self._db_url = db_url

    def submit_feedback(self, *, user_id: str, message_id: UUID, rating: int) -> None:
        """Store or update a user's thumbs-up (+1) / thumbs-down (-1) on a message."""
        with psycopg.connect(self._db_url) as conn:
            conn.execute(
                """
                insert into public.feedback (message_id, user_id, rating)
                values (%s, %s, %s)
                on conflict (message_id, user_id)
                do update set rating = excluded.rating
                """,
                (str(message_id), user_id, rating),
            )
            conn.commit()

    def get_feedback(self, *, user_id: str, message_id: UUID) -> int | None:
        """Return the user's rating for a message, or None if not rated."""
        with psycopg.connect(self._db_url) as conn:
            row = conn.execute(
                "select rating from public.feedback where message_id = %s and user_id = %s",
                (str(message_id), user_id),
            ).fetchone()
        return row[0] if row else None

    def get_feedback_for_conversation(
        self, *, user_id: str, conversation_id: UUID
    ) -> dict[str, int]:
        """Return {message_id: rating} for all rated messages in a conversation."""
        with psycopg.connect(self._db_url) as conn:
            rows = conn.execute(
                """
                select f.message_id, f.rating
                from public.feedback f
                join public.messages m on m.id = f.message_id
                where m.conversation_id = %s and f.user_id = %s
                """,
                (str(conversation_id), user_id),
            ).fetchall()
        return {str(row[0]): row[1] for row in rows}

    def log_knowledge_gap(
        self,
        *,
        question: str,
        language: str,
        conversation_id: str | None,
        gap_type: str,
        top_similarity: float,
        metadata: dict | None = None,
    ) -> None:
        """Record a question the bot couldn't answer from indexed documents."""
        with psycopg.connect(self._db_url) as conn:
            conn.execute(
                """
                insert into public.knowledge_gaps
                  (question, language, conversation_id, gap_type, top_similarity, metadata)
                values (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    question,
                    language,
                    conversation_id,
                    gap_type,
                    top_similarity,
                    psycopg.types.json.Json(metadata or {}),
                ),
            )
            conn.commit()
