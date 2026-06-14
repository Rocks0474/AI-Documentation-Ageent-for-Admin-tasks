"""Director Agent schemas — domain classification and routing."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from schemas.common import Jurisdiction, Priority


class Domain(str, Enum):
    HRBP = "HRBP"
    CB = "CB"
    LD = "LD"
    ER = "ER"
    HR_OPS = "HR_OPS"
    TA = "TA"
    ANALYTICS = "ANALYTICS"
    LEGAL = "LEGAL"


class DirectorRequestPayload(BaseModel):
    """The intent the Director classifies. No PII — anonymized context refs only."""

    intent: str
    jurisdiction_code: Jurisdiction
    context_refs: list[str] = Field(default_factory=list)


class RoutingDecision(BaseModel):
    routing_id: str
    target_domain: Domain
    priority: Priority = Priority.STANDARD
    rationale: Optional[str] = None
    requires_sequential: bool = False
    sequence: list[Domain] = Field(default_factory=list)
