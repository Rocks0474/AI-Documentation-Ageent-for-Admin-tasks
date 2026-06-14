"""People Analytics Agent schemas.

Enforces the cohort privacy floor: results for cohorts smaller than
``MINIMUM_COHORT_SIZE`` are suppressed so individuals cannot be re-identified.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from schemas.common import CohortRef, Jurisdiction


class CohortAnalyticsRequest(BaseModel):
    metric: str
    cohort_ref: CohortRef
    jurisdiction_code: Jurisdiction
    cohort_size: int


class CohortAnalyticsResult(BaseModel):
    metric: str
    cohort_ref: CohortRef
    cohort_size: int
    value: Optional[float] = None
    suppressed: bool = False  # True when cohort_size < minimum_cohort_size
    minimum_cohort_size: int = 10
