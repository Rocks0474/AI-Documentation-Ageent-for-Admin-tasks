"""HR Legal Agent schemas.

Legal opinions always carry a watermark that the orchestration graph cannot
remove, and a confidence score (LOW always triggers CHRO escalation). The
opinion body is stored by reference, never inlined.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.common import Confidence, Jurisdiction

LEGAL_WATERMARK = "AI-GENERATED — NOT LEGAL ADVICE — HUMAN REVIEW REQUIRED"


class LegalQueryPayload(BaseModel):
    question: str
    jurisdiction_code: Jurisdiction
    context_refs: list[str] = Field(default_factory=list)


class LegalOpinion(BaseModel):
    summary_ref: str  # storage key for the full opinion — not inline
    jurisdiction_code: Jurisdiction
    confidence: Confidence
    watermark: str = LEGAL_WATERMARK
    citations: list[str] = Field(default_factory=list)
