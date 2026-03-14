"""Per-user daily rate limiting backed by the daily_usage table."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from fastapi import Depends, HTTPException, status

from polisi_api.auth import AuthenticatedUser, get_current_user
from polisi_api.chat.file_processor import TOKENS_PER_ATTACHMENT
from polisi_api.chat.skills import SKILL_BY_ID
from polisi_api.config import Settings, get_settings
from polisi_api.models import ChatRequest


@dataclass(frozen=True)
class UsageSnapshot:
    request_count: int
    tokens_budgeted: int


def check_rate_limit(
    request: ChatRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    """FastAPI dependency that atomically increments usage and rejects if over budget.

    The increment happens BEFORE the LLM call.  We budget the *max_tokens*
    the call will consume (worst-case) rather than actual usage — this is
    conservative but guarantees we never overshoot.
    """
    # Estimate token cost for this request
    skill_def = SKILL_BY_ID.get(request.skill) if request.skill else None
    tokens_cost = skill_def.max_tokens if skill_def else 1200  # default chat max_tokens

    # Attachments (images, PDFs) are expensive — add extra budget per file.
    if request.attachments:
        tokens_cost += len(request.attachments) * TOKENS_PER_ATTACHMENT

    try:
        with psycopg.connect(settings.supabase_db_url) as conn:
            row = conn.execute(
                "select request_count, tokens_budgeted from public.increment_daily_usage(%s, %s)",
                (user.user_id, tokens_cost),
            ).fetchone()
    except Exception:
        # If the tracking table doesn't exist yet (pre-migration) or DB is
        # unreachable, fail-open so the service stays available.
        return user

    if row is None:
        return user

    new_requests, new_tokens = int(row[0]), int(row[1])

    if new_requests > settings.rate_limit_daily_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "daily_request_limit",
                "message": "You have reached your daily request limit. Please try again tomorrow.",
                "limit": settings.rate_limit_daily_requests,
                "used": new_requests,
            },
        )

    if new_tokens > settings.rate_limit_daily_tokens:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "daily_token_limit",
                "message": "You have used your daily token budget. Please try again tomorrow.",
                "limit": settings.rate_limit_daily_tokens,
                "used": new_tokens,
            },
        )

    return user


def get_usage(
    user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> UsageSnapshot:
    """Read current usage without incrementing.  Used by the /api/usage endpoint."""
    try:
        with psycopg.connect(settings.supabase_db_url) as conn:
            row = conn.execute(
                """
                select request_count, tokens_budgeted
                from public.daily_usage
                where user_id = %s and usage_date = current_date
                """,
                (user.user_id,),
            ).fetchone()
    except Exception:
        return UsageSnapshot(request_count=0, tokens_budgeted=0)

    if row is None:
        return UsageSnapshot(request_count=0, tokens_budgeted=0)

    return UsageSnapshot(request_count=int(row[0]), tokens_budgeted=int(row[1]))
