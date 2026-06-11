"""Unit tests for the C&B, TA, and L&D agents (deterministic by design)."""

from __future__ import annotations

import json

from adapters.base.storage import DataZone
from adapters.local.audit_log import LocalAuditLogAdapter
from adapters.local.notification import LocalNotificationAdapter
from adapters.local.storage import LocalStorageAdapter
from adapters.local.vector_db import LocalVectorDBAdapter
from agents.cb.agent import CBAgent, compute_offer_range
from agents.ld.agent import LDAgent
from agents.ta.agent import TAAgent
from schemas.cb import OfferRangeRequest
from schemas.common import AgentRequest, HITLTier, Jurisdiction


def _adapters(tmp_path):
    return {
        "audit_log": LocalAuditLogAdapter(),
        "storage": LocalStorageAdapter(root=str(tmp_path)),
        "notification": LocalNotificationAdapter(),
        "vector_db": LocalVectorDBAdapter(),
    }


def _request(**payload) -> AgentRequest:
    return AgentRequest(
        source="HUMAN_HR",
        jurisdiction_code=Jurisdiction.JP,
        requesting_user_role="HRBP",
        payload=payload,
    )


# ---------------------------------------------------------------------------
# C&B
# ---------------------------------------------------------------------------

def test_compute_offer_range_is_deterministic_and_banded():
    req = OfferRangeRequest(
        role_title="Software Engineer", level="L4", location="Tokyo",
        jurisdiction_code=Jurisdiction.JP,
    )
    a = compute_offer_range(req)
    b = compute_offer_range(req)
    assert a == b  # deterministic
    assert a.currency == "JPY"
    assert a.pay_band_low < a.pay_band_high
    assert "salary" not in a.model_dump()  # bands, not individual salary


def test_compute_offer_range_currency_by_jurisdiction():
    req = OfferRangeRequest(
        role_title="SWE", level="L4", location="SF",
        jurisdiction_code=Jurisdiction.US_CA,
    )
    assert compute_offer_range(req).currency == "USD"


def test_unknown_level_falls_back_to_default():
    req = OfferRangeRequest(
        role_title="SWE", level="Lxx", location="Tokyo",
        jurisdiction_code=Jurisdiction.JP,
    )
    # Falls back to the L3 band.
    assert compute_offer_range(req).pay_band_low == 5_500_000


async def test_cb_agent_persists_and_audits(tmp_path):
    agent = CBAgent(**_adapters(tmp_path))
    response = await agent.handle(
        _request(role_title="SWE", level="L4", location="Tokyo")
    )
    assert response.hitl_tier == HITLTier.RECOMMENDED
    result = json.loads(
        await agent.storage.get(response.full_output_ref, DataZone.ZONE2)
    )
    assert result["currency"] == "JPY"
    events = [e.event_type for e in await agent.audit_log.query(response.request_id)]
    assert "CB_OFFER_RANGE" in events


# ---------------------------------------------------------------------------
# TA
# ---------------------------------------------------------------------------

async def test_ta_agent_returns_anonymized_pipeline(tmp_path):
    agent = TAAgent(**_adapters(tmp_path))
    response = await agent.handle(
        _request(requisition_ref="req-eng-42", role_title="SWE")
    )
    summary = json.loads(
        await agent.storage.get(response.full_output_ref, DataZone.ZONE2)
    )
    assert summary["requisition_ref"] == "req-eng-42"
    assert set(summary["stage_counts"]) == {"applied", "screen", "onsite", "offer"}
    assert summary["total_candidates"] == sum(summary["stage_counts"].values())
    # Stubs not connected -> flags reflect graceful degradation.
    assert "GREENHOUSE_STUB" in response.jurisdiction_flags
    assert any(f.startswith("SLOTS_AVAILABLE:") for f in response.jurisdiction_flags)


# ---------------------------------------------------------------------------
# L&D
# ---------------------------------------------------------------------------

async def test_ld_agent_builds_learning_path(tmp_path):
    agent = LDAgent(**_adapters(tmp_path))
    response = await agent.handle(
        _request(skill_target="people_management", role_family="manager")
    )
    result = json.loads(
        await agent.storage.get(response.full_output_ref, DataZone.ZONE2)
    )
    assert result["skill_target"] == "people_management"
    assert len(result["modules"]) == 3
    assert result["estimated_hours"] == 18  # 8 + 6 + 4


async def test_ld_agent_unknown_skill_uses_generic_path(tmp_path):
    agent = LDAgent(**_adapters(tmp_path))
    response = await agent.handle(
        _request(skill_target="quantum_basket_weaving", role_family="ic")
    )
    result = json.loads(
        await agent.storage.get(response.full_output_ref, DataZone.ZONE2)
    )
    assert [m.split()[0] for m in result["modules"]] == ["GEN-101", "GEN-201"]
