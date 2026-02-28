from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from polisi_api.auth import AuthenticatedUser, get_current_user
from polisi_api.chat.repository import InMemoryChatRepository
from polisi_api.dependencies import get_repository


def test_conversation_routes() -> None:
    os.environ["SUPABASE_URL"] = "https://example.supabase.co"
    os.environ["SUPABASE_DB_URL"] = "postgresql://postgres:postgres@localhost:5432/postgres"

    from polisi_api.main import create_app
    from polisi_api.config import Settings

    repository = InMemoryChatRepository()
    user_id = "8bd9d241-8380-4dd7-a1a8-a664e1d74c8f"
    older_id = repository.ensure_conversation(
        user_id=user_id,
        language="ms",
        title_seed="Bantuan pendidikan",
        conversation_id=None,
        create_new=True,
    )
    newer_id = repository.ensure_conversation(
        user_id=user_id,
        language="en",
        title_seed="Childcare subsidies",
        conversation_id=None,
        create_new=True,
    )
    repository.conversations[older_id]["updated_at"] = datetime.now(UTC) - timedelta(days=1)
    repository.conversations[newer_id]["updated_at"] = datetime.now(UTC)
    repository.add_message(
        conversation_id=newer_id,
        role="user",
        content="What childcare subsidies are available?",
        language="en",
    )
    assistant_message_id = repository.add_message(
        conversation_id=newer_id,
        role="assistant",
        content="Working parents may qualify for childcare subsidies [1].",
        language="en",
    )
    repository.add_citations(
        message_id=assistant_message_id,
        citations=[],
    )

    app = create_app(
        Settings.from_env(
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_DB_URL": "postgresql://postgres:postgres@localhost:5432/postgres",
                "SUPABASE_JWT_SECRET": "test-secret",
            }
        )
    )
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=user_id,
        email="citizen@example.com",
        role="authenticated",
        claims={"sub": user_id},
    )
    client = TestClient(app)

    listing = client.get("/api/conversations")
    detail = client.get(f"/api/conversations/{newer_id}")

    assert listing.status_code == 200
    listing_body = listing.json()
    assert [item["id"] for item in listing_body] == [str(newer_id), str(older_id)]
    assert listing_body[0]["message_count"] == 2

    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["id"] == str(newer_id)
    assert [message["role"] for message in detail_body["messages"]] == ["user", "assistant"]
