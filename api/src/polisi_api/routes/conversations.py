"""Conversation history routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from polisi_api.auth import AuthenticatedUser, get_current_user
from polisi_api.dependencies import get_repository
from polisi_api.models import ConversationDetail, ConversationSummary

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationSummary])
def list_conversations(
    user: AuthenticatedUser = Depends(get_current_user),
    repository=Depends(get_repository),
) -> list[ConversationSummary]:
    return repository.list_conversations(user_id=user.user_id)


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation_detail(
    conversation_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    repository=Depends(get_repository),
) -> ConversationDetail:
    detail = repository.get_conversation_detail(
        user_id=user.user_id,
        conversation_id=conversation_id,
    )
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return detail
