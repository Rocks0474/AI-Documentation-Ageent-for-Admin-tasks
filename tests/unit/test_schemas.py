"""Unit tests for the Pydantic schemas, including PII-safety review."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pii_gateway.detector import PIIDetector
from schemas.analytics import CohortAnalyticsResult
from schemas.cb import OfferRangeResult
from schemas.common import (
    AgentRequest,
    AgentResponse,
    Confidence,
    HITLTier,
    Jurisdiction,
    OutputLanguage,
    Priority,
)
from schemas.director import Domain, RoutingDecision
from schemas.er import ERCasePayload
from schemas.legal import LEGAL_WATERMARK, LegalOpinion


def test_agent_request_defaults():
    req = AgentRequest(
        source="HUMAN_HR",
        jurisdiction_code=Jurisdiction.JP,
        requesting_user_role="CHRO",
    )
    assert req.request_id  # auto uuid
    assert req.output_language == OutputLanguage.EN
    assert req.priority == Priority.STANDARD
    assert req.timestamp.tzinfo is not None  # timezone-aware


def test_agent_request_rejects_bad_enum():
    with pytest.raises(ValidationError):
        AgentRequest(
            source="HUMAN_HR",
            jurisdiction_code="MARS",  # not a Jurisdiction
            requesting_user_role="CHRO",
        )


def test_agent_response_defaults():
    resp = AgentResponse(request_id="r1")
    assert resp.confidence == Confidence.HIGH
    assert resp.hitl_tier == HITLTier.NONE
    assert resp.jurisdiction_flags == []


def test_routing_decision_roundtrip():
    decision = RoutingDecision(
        routing_id="rt-1",
        target_domain=Domain.ER,
        requires_sequential=True,
        sequence=[Domain.ER, Domain.LEGAL],
    )
    assert decision.target_domain == Domain.ER
    assert decision.sequence == [Domain.ER, Domain.LEGAL]


def test_er_case_payload_is_anonymized():
    payload = ERCasePayload(
        case_summary="manager requests guidance on a performance concern",
        anonymized_employee_ref="emp_ref_abc",
        jurisdiction_code=Jurisdiction.JP,
        employee_count=5,
    )
    assert payload.anonymized_employee_ref == "emp_ref_abc"


def test_legal_opinion_carries_watermark():
    opinion = LegalOpinion(
        summary_ref="audit/opinion-1",
        jurisdiction_code=Jurisdiction.EU,
        confidence=Confidence.MEDIUM,
    )
    assert opinion.watermark == LEGAL_WATERMARK


def test_cb_offer_range_uses_bands_not_individual_salary():
    result = OfferRangeResult(
        role_title="Software Engineer",
        level="L4",
        currency="JPY",
        pay_band_low=8_000_000,
        pay_band_high=11_000_000,
    )
    # Field names use "pay_band", not "salary" — passes PII review.
    assert "salary" not in result.model_dump()


def test_analytics_cohort_privacy_floor_field():
    result = CohortAnalyticsResult(
        metric="attrition_rate",
        cohort_ref="cohort_eng_jp",
        cohort_size=4,
        suppressed=True,
    )
    assert result.suppressed is True


def test_no_schema_payload_trips_pii_detector():
    """Realistic instances of each schema must be PII-clean (Constraint #2)."""
    detector = PIIDetector()
    instances = [
        AgentRequest(
            source="HUMAN_HR",
            jurisdiction_code=Jurisdiction.JP,
            requesting_user_role="HRBP",
            hitl_approver="#hr-hitl",
            payload={"intent": "summarize remote work policy"},
        ),
        ERCasePayload(
            case_summary="guidance on attendance policy",
            jurisdiction_code=Jurisdiction.JP,
        ),
        OfferRangeResult(
            role_title="SWE", level="L4", currency="JPY",
            pay_band_low=8e6, pay_band_high=1.1e7,
        ),
    ]
    for instance in instances:
        assert not detector.scan(instance.model_dump()).detected
