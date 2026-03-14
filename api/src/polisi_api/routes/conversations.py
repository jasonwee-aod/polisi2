"""Conversation history routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from polisi_api.auth import AuthenticatedUser, get_current_user
from polisi_api.dependencies import get_repository
from polisi_api.models import ConversationDetail, ConversationSummary, ConversationUpdate

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


@router.patch("/{conversation_id}", response_model=None)
def update_conversation(
    conversation_id: str,
    body: ConversationUpdate,
    user: AuthenticatedUser = Depends(get_current_user),
    repository=Depends(get_repository),
) -> Response:
    found = repository.update_conversation(
        conversation_id=conversation_id,
        user_id=user.user_id,
        title=body.title,
        pinned=body.pinned,
    )
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{conversation_id}", response_model=None)
def delete_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    repository=Depends(get_repository),
) -> Response:
    found = repository.delete_conversation(
        conversation_id=conversation_id,
        user_id=user.user_id,
    )
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
