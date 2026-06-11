"""Unit tests for PIIDetector — Zone 1 detection (Constraint #2)."""

from __future__ import annotations

import pytest

from pii_gateway.detector import PIIDetector


@pytest.fixture
def detector() -> PIIDetector:
    return PIIDetector()


# ---------------------------------------------------------------------------
# Field-name detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "field",
    ["name", "full_name", "email", "salary", "my_number", "ssn", "nric"],
)
def test_detects_zone1_field_names(detector, field):
    result = detector.scan({"payload": {field: "REDACTED"}})
    assert result.detected
    assert any(field in c for c in result.categories)


def test_clean_payload_clears(detector):
    result = detector.scan(
        {
            "payload": {
                "intent": "summarize remote work policy",
                "anonymized_employee_ref": "emp_ref_123",
                "cohort_ref": "cohort_eng_jp",
                "pay_band_low": 8_000_000,
            }
        }
    )
    assert not result.detected
    assert result.summary == "No Zone 1 data detected."


def test_pay_band_does_not_match_salary(detector):
    # "pay_band_low" must NOT be flagged as the Zone 1 "salary" field.
    result = detector.scan({"pay_band_low": 100, "pay_band_high": 200})
    assert not result.detected


# ---------------------------------------------------------------------------
# Value-pattern detection
# ---------------------------------------------------------------------------

def test_detects_email_value(detector):
    result = detector.scan({"payload": {"note": "contact jane.doe@corp.com asap"}})
    assert result.detected
    assert "VALUE:EMAIL" in result.categories


def test_detects_us_ssn_value(detector):
    result = detector.scan({"payload": {"note": "id 123-45-6789"}})
    assert result.detected
    assert "VALUE:US_SSN" in result.categories


def test_detects_sg_nric_value(detector):
    result = detector.scan({"payload": {"note": "S1234567A"}})
    assert result.detected
    assert "VALUE:SG_NRIC" in result.categories


# ---------------------------------------------------------------------------
# Envelope exemption — operational fields must not cause false positives
# ---------------------------------------------------------------------------

def test_hitl_approver_email_is_exempt(detector):
    # hitl_approver may legitimately be an email; it must not trip the gate.
    result = detector.scan(
        {
            "request_id": "r1",
            "requesting_user_role": "CHRO",
            "hitl_approver": "chro@corp.com",
            "payload": {"intent": "policy question"},
        }
    )
    assert not result.detected


# ---------------------------------------------------------------------------
# Summary never leaks values
# ---------------------------------------------------------------------------

def test_summary_contains_no_pii_value(detector):
    result = detector.scan({"payload": {"email": "secret.person@corp.com"}})
    assert result.detected
    assert "secret.person@corp.com" not in result.summary
    # Only category + location appear.
    assert "FIELD_NAME:email" in result.summary
