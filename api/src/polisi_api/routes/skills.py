"""Route for listing available skills."""

from __future__ import annotations

from fastapi import APIRouter

from polisi_api.chat.skills import SKILLS
from polisi_api.models import SkillInfo

router = APIRouter(prefix="/api", tags=["skills"])


@router.get("/skills", response_model=list[SkillInfo])
async def list_skills() -> list[SkillInfo]:
    return [
        SkillInfo(
            id=skill.id,
            name=skill.name,
            name_ms=skill.name_ms,
            description=skill.description,
            description_ms=skill.description_ms,
            icon=skill.icon,
        )
        for skill in SKILLS
    ]
