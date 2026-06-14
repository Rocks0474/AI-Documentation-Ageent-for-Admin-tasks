"""Unit tests for the HRBP Agent."""

from __future__ import annotations

from adapters.base.storage import DataZone
from adapters.local.audit_log import LocalAuditLogAdapter
from adapters.local.notification import LocalNotificationAdapter
from adapters.local.storage import LocalStorageAdapter
from adapters.local.vector_db import LocalVectorDBAdapter
from agents.hrbp.agent import HRBPAgent
from schemas.common import AgentRequest, HITLTier, Jurisdiction


def _agent(tmp_path):
    audit = LocalAuditLogAdapter()
    storage = LocalStorageAdapter(root=str(tmp_path))
    agent = HRBPAgent(
        audit_log=audit,
        storage=storage,
        notification=LocalNotificationAdapter(),
        vector_db=LocalVectorDBAdapter(),
    )
    return agent, audit, storage


async def test_hrbp_produces_recommendation(tmp_path, monkeypatch):
    agent, audit, storage = _agent(tmp_path)

    async def fake_llm(system, messages):
        return "Recommend targeted retention conversations for the cohort."

    monkeypatch.setattr(agent, "_call_llm", fake_llm)

    request = AgentRequest(
        source="HUMAN_HR",
        jurisdiction_code=Jurisdiction.JP,
        requesting_user_role="MANAGER",
        payload={
            "topic": "rising attrition in engineering",
            "cohort_ref": "cohort_eng_jp",
            "signal_refs": ["analytics/req-9.json"],
        },
    )
    response = await agent.handle(request)

    assert response.hitl_tier == HITLTier.RECOMMENDED
    stored = await storage.get(response.full_output_ref, DataZone.ZONE2)
    assert b"retention conversations" in stored
    events = [e.event_type for e in await audit.query(response.request_id)]
    assert "HRBP_RECOMMENDATION" in events
