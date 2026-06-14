"""Unit tests for the HR Operations Agent."""

from __future__ import annotations

from adapters.base.storage import DataZone
from adapters.local.audit_log import LocalAuditLogAdapter
from adapters.local.notification import LocalNotificationAdapter
from adapters.local.storage import LocalStorageAdapter
from adapters.local.vector_db import LocalVectorDBAdapter
from agents.hr_ops.agent import HROpsAgent, statutory_obligations
from schemas.common import AgentRequest, HITLTier, Jurisdiction
from schemas.hr_ops import LifecycleEvent


def _agent(tmp_path):
    audit = LocalAuditLogAdapter()
    storage = LocalStorageAdapter(root=str(tmp_path))
    agent = HROpsAgent(
        audit_log=audit,
        storage=storage,
        notification=LocalNotificationAdapter(),
        vector_db=LocalVectorDBAdapter(),
    )
    return agent, audit, storage


def _request(event_type: str) -> AgentRequest:
    return AgentRequest(
        source="SYSTEM_EVENT",
        jurisdiction_code=Jurisdiction.JP,
        requesting_user_role="SYSTEM",
        payload={
            "event_type": event_type,
            "anonymized_employee_ref": "emp_ref_1",
            "effective_date": "2026-07-01",
        },
    )


def test_statutory_obligations_jp_offboarding():
    obligations = statutory_obligations(LifecycleEvent.OFFBOARDING, Jurisdiction.JP)
    assert "離職票の発行" in obligations
    assert len(obligations) == 4


def test_statutory_obligations_uncodified_jurisdiction_is_empty():
    assert statutory_obligations(LifecycleEvent.ONBOARDING, Jurisdiction.US_FED) == []


async def test_process_derives_obligations_then_generates_checklist(tmp_path, monkeypatch):
    agent, audit, storage = _agent(tmp_path)

    async def fake_llm(system, messages):
        return "1. File resignation paperwork\n2. Issue certificates"

    monkeypatch.setattr(agent, "_call_llm", fake_llm)
    response = await agent.handle(_request("OFFBOARDING"))

    assert response.hitl_tier == HITLTier.RECOMMENDED
    assert any(f.startswith("OBLIGATION:") for f in response.jurisdiction_flags)
    stored = await storage.get(response.full_output_ref, DataZone.ZONE2)
    assert b"resignation paperwork" in stored

    events = [e.event_type for e in await audit.query(response.request_id)]
    assert events == [
        "REQUEST_RECEIVED",
        "HR_OPS_OBLIGATIONS_DERIVED",
        "RESPONSE_GENERATED",
    ]
