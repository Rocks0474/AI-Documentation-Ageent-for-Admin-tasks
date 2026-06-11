"""Employee Relations (ER) Agent schemas.

The ER case payload carries an anonymized, fact-only summary — never names or
other Zone 1 data. The compliance verdict mirrors the deterministic Module B
result (see ``agents/er/compliance_module.py``).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from schemas.common import AnonymizedEmployeeRef, HITLTier, Jurisdiction


class ERCasePayload(BaseModel):
    case_summary: str  # anonymized facts only — no names, no PII
    anonymized_employee_ref: Optional[AnonymizedEmployeeRef] = None
    jurisdiction_code: Jurisdiction
    employee_count: int = 0
    works_council_present: bool = False
    union_present: bool = False


class ERComplianceVerdict(BaseModel):
    result: str  # HARD_STOP | COMPLIANCE_FLAG | CLEAR
    triggered_rules: list[str] = Field(default_factory=list)
    rule_descriptions: list[str] = Field(default_factory=list)
    legal_agent_required: bool = False
    hitl_tier: HITLTier = HITLTier.NONE
