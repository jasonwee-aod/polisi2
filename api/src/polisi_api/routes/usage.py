"""Usage and rate limit status endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from polisi_api.config import Settings, get_settings
from polisi_api.ratelimit import UsageSnapshot, get_usage

router = APIRouter(prefix="/api", tags=["usage"])


@router.get("/usage")
async def current_usage(
    usage: UsageSnapshot = Depends(get_usage),
    settings: Settings = Depends(get_settings),
) -> dict:
    return {
        "requests": {
            "used": usage.request_count,
            "limit": settings.rate_limit_daily_requests,
            "remaining": max(0, settings.rate_limit_daily_requests - usage.request_count),
        },
        "tokens": {
            "used": usage.tokens_budgeted,
            "limit": settings.rate_limit_daily_tokens,
            "remaining": max(0, settings.rate_limit_daily_tokens - usage.tokens_budgeted),
        },
        "tier": "free",
    }
