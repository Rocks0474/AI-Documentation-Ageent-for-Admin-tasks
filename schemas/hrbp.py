"""HR Business Partner (HRBP) Agent schemas.

The HRBP consumes anonymized Analytics signals and organizational context;
it operates on cohort references, never individuals.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from schemas.common import CohortRef, Jurisdiction


class HRBPConsultPayload(BaseModel):
    topic: str
    cohort_ref: Optional[CohortRef] = None
    jurisdiction_code: Jurisdiction
    signal_refs: list[str] = Field(default_factory=list)


class HRBPRecommendation(BaseModel):
    topic: str
    summary_ref: str  # storage key — not inline
    recommended_actions: list[str] = Field(default_factory=list)
