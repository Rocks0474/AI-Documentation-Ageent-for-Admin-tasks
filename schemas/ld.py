"""Learning & Development (L&D) Agent schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.common import Jurisdiction


class LearningPathRequest(BaseModel):
    skill_target: str
    role_family: str
    jurisdiction_code: Jurisdiction


class LearningPathResult(BaseModel):
    skill_target: str
    modules: list[str] = Field(default_factory=list)
    estimated_hours: int = 0
