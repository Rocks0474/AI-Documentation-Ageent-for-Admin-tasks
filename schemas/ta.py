"""Talent Acquisition (TA) Agent schemas.

Candidates are referenced by anonymized requisition/stage aggregates only —
no candidate names or contact details (Zone 1) appear here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.common import Jurisdiction


class PipelinePayload(BaseModel):
    requisition_ref: str
    role_title: str
    jurisdiction_code: Jurisdiction


class CandidateStageSummary(BaseModel):
    requisition_ref: str
    stage_counts: dict[str, int] = Field(default_factory=dict)
    total_candidates: int = 0
