"""HR Operations Agent schemas — lifecycle workflows and statutory calendar."""

from __future__ import annotations

import datetime
from enum import Enum

from pydantic import BaseModel

from schemas.common import AnonymizedEmployeeRef, Jurisdiction


class LifecycleEvent(str, Enum):
    ONBOARDING = "ONBOARDING"
    OFFBOARDING = "OFFBOARDING"
    TRANSFER = "TRANSFER"
    LEAVE = "LEAVE"


class LifecycleEventPayload(BaseModel):
    event_type: LifecycleEvent
    anonymized_employee_ref: AnonymizedEmployeeRef
    jurisdiction_code: Jurisdiction
    effective_date: datetime.date


class StatutoryFilingAlert(BaseModel):
    filing_type: str  # e.g. 算定基礎届, 年末調整
    deadline_days: int
    jurisdiction_code: Jurisdiction
