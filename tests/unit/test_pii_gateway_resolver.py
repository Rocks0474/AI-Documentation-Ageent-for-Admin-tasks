"""Tests for the PII gateway resolver and HRIS connectors (Constraint #2).

The central guarantee: a Zone 1 EmployeeRecord trips the PII detector, but the
Zone 2 AnonymizedContext the gateway produces does not — and no real PII value
appears anywhere in the resolved output.
"""

from __future__ import annotations

import datetime
import json

import pytest

from pii_gateway.detector import PIIDetector
from pii_gateway.gateway import (
    AnonymizedContext,
    PIIGateway,
    UnknownRefError,
    build_pii_gateway,
)
from pii_gateway.hris_connectors.smarthr import SmartHRConnector
from pii_gateway.hris_connectors.workday import WorkdayConnector

TODAY = datetime.date(2026, 6, 12)


def _gateway(connector=None) -> PIIGateway:
    return PIIGateway(connector or SmartHRConnector(), salt="test-salt")


# ---------------------------------------------------------------------------
# Connectors return Zone 1 PII (deterministically)
# ---------------------------------------------------------------------------

async def test_smarthr_record_is_zone1_and_deterministic():
    connector = SmartHRConnector()
    rec1 = await connector.get_employee("emp-0001")
    rec2 = await connector.get_employee("emp-0001")
    assert rec1 == rec2  # deterministic
    assert rec1.full_name and rec1.national_id and rec1.base_salary > 0
    # A raw record DOES trip the PII detector (that's the whole point).
    assert PIIDetector().scan(rec1.model_dump(mode="json")).detected is True


async def test_unknown_employee_raises():
    with pytest.raises(KeyError):
        await SmartHRConnector().get_employee("nobody")


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

async def test_tokenize_is_opaque_and_idempotent():
    gw = _gateway()
    ref1 = await gw.tokenize("emp-0001")
    ref2 = await gw.tokenize("emp-0001")
    assert ref1 == ref2                       # idempotent / deterministic
    assert ref1.startswith("emp_ref_")
    assert "emp-0001" not in ref1             # opaque — no source id leaked


async def test_resolve_unknown_ref_raises():
    gw = _gateway()
    with pytest.raises(UnknownRefError):
        await gw.resolve("emp_ref_never_issued")


# ---------------------------------------------------------------------------
# The boundary: resolved context is Zone 2 — no PII
# ---------------------------------------------------------------------------

async def test_resolved_context_is_pii_free():
    gw = _gateway()
    ref = await gw.tokenize("emp-0001")
    ctx = await gw.resolve(ref, today=TODAY)

    assert isinstance(ctx, AnonymizedContext)
    # No Zone 1 fields present at all.
    dump = ctx.model_dump()
    for forbidden in ("full_name", "email", "national_id", "date_of_birth", "base_salary"):
        assert forbidden not in dump
    # Bands, not figures/dates.
    assert ctx.tenure_band and ctx.age_band and ctx.pay_band
    assert ctx.pay_band.startswith("JPY ")
    # The detector does NOT trip on the context.
    assert PIIDetector().scan(dump).detected is False


async def test_real_pii_values_never_appear_in_context():
    connector = SmartHRConnector()
    gw = PIIGateway(connector, salt="test-salt")
    record = await connector.get_employee("emp-0007")
    ref = await gw.tokenize("emp-0007")
    ctx = await gw.resolve(ref, today=TODAY)

    blob = json.dumps(ctx.model_dump(), ensure_ascii=False)
    # None of the actual PII values leak into the Zone 2 context.
    assert record.full_name not in blob
    assert (record.national_id or "") not in blob
    assert str(record.base_salary) not in blob
    assert record.email not in blob


async def test_manager_ref_is_anonymized():
    connector = SmartHRConnector()
    gw = PIIGateway(connector, salt="test-salt")
    record = await connector.get_employee("emp-0003")
    ref = await gw.tokenize("emp-0003")
    ctx = await gw.resolve(ref, today=TODAY)
    if record.manager_employee_id:
        assert ctx.anonymized_manager_ref
        assert record.manager_employee_id not in ctx.anonymized_manager_ref


# ---------------------------------------------------------------------------
# Seeding + Workday parity + factory
# ---------------------------------------------------------------------------

async def test_seed_from_connector_issues_refs_for_all():
    gw = _gateway()
    refs = await gw.seed_from_connector()
    assert len(refs) == 20
    ctx = await gw.resolve(refs[0], today=TODAY)
    assert ctx.anonymized_employee_ref == refs[0]


async def test_workday_connector_resolves_to_clean_context():
    gw = PIIGateway(WorkdayConnector(), salt="test-salt")
    ref = await gw.tokenize("wd-0005")
    ctx = await gw.resolve(ref, today=TODAY)
    assert ctx.jurisdiction == "US-FED"
    assert ctx.pay_band.startswith("USD ")
    assert PIIDetector().scan(ctx.model_dump()).detected is False


def test_build_pii_gateway_defaults_to_smarthr(monkeypatch):
    monkeypatch.delenv("HRIS_SYSTEM", raising=False)
    gw = build_pii_gateway()
    assert gw._connector.system_name == "SMARTHR"


def test_build_pii_gateway_workday(monkeypatch):
    monkeypatch.setenv("HRIS_SYSTEM", "WORKDAY")
    gw = build_pii_gateway()
    assert gw._connector.system_name == "WORKDAY"
