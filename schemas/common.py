"""Shared message schemas and enums used across all nine agents.

These are the envelope types every agent speaks. Per Constraint #2, no schema
in this package may carry Zone 1 (PII) fields: identifiers are anonymized
references (see :data:`AnonymizedEmployeeRef` / :data:`CohortRef`), and detail
payloads are free-form ``dict``s that the PII gateway and ``PIIDetector`` guard.
"""

from __future__ import annotations

import datetime
import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# Opaque, non-reversible references. The PII gateway is the only component that
# can resolve these back to a real person/cohort.
AnonymizedEmployeeRef = str
CohortRef = str


def _utcnow() -> datetime.datetime:
    # Timezone-aware UTC; `datetime.utcnow()` is deprecated from Python 3.12.
    return datetime.datetime.now(datetime.timezone.utc)


class Jurisdiction(str, Enum):
    JP = "JP"
    US_FED = "US-FED"
    US_CA = "US-CA"
    EU = "EU"
    SG = "SG"
    MULTI = "MULTI"


class Priority(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    STANDARD = "STANDARD"
    ASYNC = "ASYNC"


class HITLTier(str, Enum):
    MANDATORY = "MANDATORY"      # System halts — implementation blocked
    REQUIRED = "REQUIRED"        # Human notified — 24hr review window
    RECOMMENDED = "RECOMMENDED"  # Logged — no block
    NONE = "NONE"               # Administrative only


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"                  # LOW always triggers CHRO escalation


class OutputLanguage(str, Enum):
    EN = "EN"
    JP = "JP"
    BILINGUAL = "BILINGUAL"


class AgentRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    routing_id: Optional[str] = None
    source: str                                  # HUMAN_HR | SUB_AGENT | SYSTEM_EVENT
    jurisdiction_code: Jurisdiction
    output_language: OutputLanguage = OutputLanguage.EN
    priority: Priority = Priority.STANDARD
    requesting_user_role: str                    # CHRO | HRBP | MANAGER | SYSTEM
    hitl_approver: Optional[str] = None          # Slack channel or email
    timestamp: datetime.datetime = Field(default_factory=_utcnow)
    payload: dict = Field(default_factory=dict)


class AgentResponse(BaseModel):
    request_id: str
    agent_id: Optional[str] = None
    confidence: Confidence = Confidence.HIGH
    hitl_tier: HITLTier = HITLTier.NONE
    hitl_basis: Optional[str] = None
    requires_human_decision: bool = False
    full_output_ref: Optional[str] = None        # Storage key — not inline
    error: Optional[str] = None
    detail: Optional[str] = None
    jurisdiction_flags: list[str] = Field(default_factory=list)
    timestamp: datetime.datetime = Field(default_factory=_utcnow)
