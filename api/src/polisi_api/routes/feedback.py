"""Feedback routes for iterative learning."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from polisi_api.auth import AuthenticatedUser, get_current_user
from polisi_api.chat.feedback import FeedbackRepository
from polisi_api.config import Settings, get_settings

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    message_id: UUID
    rating: int = Field(ge=-1, le=1)


class FeedbackResponse(BaseModel):
    message_id: UUID
    rating: int


class ConversationFeedbackResponse(BaseModel):
    ratings: dict[str, int]


def _get_feedback_repo(settings: Settings = Depends(get_settings)) -> FeedbackRepository:
    return FeedbackRepository(settings.supabase_db_url)


@router.post("", response_model=FeedbackResponse)
def submit_feedback(
    request: FeedbackRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    repo: FeedbackRepository = Depends(_get_feedback_repo),
) -> FeedbackResponse:
    if request.rating == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rating must be 1 (positive) or -1 (negative)",
        )
    repo.submit_feedback(
        user_id=user.user_id,
        message_id=request.message_id,
        rating=request.rating,
    )
    return FeedbackResponse(message_id=request.message_id, rating=request.rating)


@router.get(
    "/conversation/{conversation_id}",
    response_model=ConversationFeedbackResponse,
)
def get_conversation_feedback(
    conversation_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    repo: FeedbackRepository = Depends(_get_feedback_repo),
) -> ConversationFeedbackResponse:
    ratings = repo.get_feedback_for_conversation(
        user_id=user.user_id,
        conversation_id=conversation_id,
    )
    return ConversationFeedbackResponse(ratings=ratings)
