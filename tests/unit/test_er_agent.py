"""Unit tests for the ER Agent: Module B before Module A, hard-stop bypass."""

from __future__ import annotations

from adapters.base.storage import DataZone
from adapters.local.audit_log import LocalAuditLogAdapter
from adapters.local.notification import LocalNotificationAdapter
from adapters.local.storage import LocalStorageAdapter
from adapters.local.vector_db import LocalVectorDBAdapter
from agents.er.agent import ERAgent
from schemas.common import AgentRequest, HITLTier, Jurisdiction


def _er_agent(tmp_path):
    audit = LocalAuditLogAdapter()
    storage = LocalStorageAdapter(root=str(tmp_path))
    notifier = LocalNotificationAdapter()
    agent = ERAgent(
        audit_log=audit,
        storage=storage,
        notification=notifier,
        vector_db=LocalVectorDBAdapter(),
    )
    return agent, audit, storage, notifier


def _request(case_summary: str, **payload) -> AgentRequest:
    return AgentRequest(
        source="HUMAN_HR",
        jurisdiction_code=Jurisdiction.JP,
        requesting_user_role="HRBP",
        hitl_approver="#er-hitl",
        payload={"case_summary": case_summary, **payload},
    )


async def test_hard_stop_bypasses_module_a(tmp_path, monkeypatch):
    agent, audit, storage, notifier = _er_agent(tmp_path)

    async def boom(system, messages):
        raise AssertionError("Module A (LLM) must NOT run on HARD_STOP")

    monkeypatch.setattr(agent, "_call_llm", boom)

    response = await agent.handle(
        _request("manager wants to proceed with termination of employee")
    )

    assert response.hitl_tier == HITLTier.MANDATORY
    assert response.requires_human_decision is True
    assert "TERMINATION" in response.jurisdiction_flags
    assert "LEGAL_AGENT_REQUIRED" in response.jurisdiction_flags
    # No Module A output persisted.
    assert response.full_output_ref is None
    # Compliance check was audited before the response, and HITL fired.
    events = [e.event_type for e in await audit.query(response.request_id)]
    assert events == [
        "REQUEST_RECEIVED",
        "ER_COMPLIANCE_CHECK",
        "RESPONSE_GENERATED",
    ]
    assert len(notifier.sent) == 1  # MANDATORY => HITL notification


async def test_compliance_audited_before_module_a_on_clear(tmp_path, monkeypatch):
    agent, audit, storage, notifier = _er_agent(tmp_path)
    calls: list[str] = []

    async def fake_llm(system, messages):
        # When Module A runs, the compliance check must already be logged.
        seq = [audit._entries[eid].event_type for eid in audit._order]
        calls.append("llm")
        assert "ER_COMPLIANCE_CHECK" in seq
        return "Here is measured ER guidance."

    monkeypatch.setattr(agent, "_call_llm", fake_llm)

    response = await agent.handle(_request("employee asking about remote work policy"))

    assert calls == ["llm"]  # Module A ran exactly once
    assert response.hitl_tier == HITLTier.RECOMMENDED
    assert response.full_output_ref and response.full_output_ref.startswith("er/")
    stored = await storage.get(response.full_output_ref, DataZone.ZONE2)
    assert b"measured ER guidance" in stored

    events = [e.event_type for e in await audit.query(response.request_id)]
    assert events.index("ER_COMPLIANCE_CHECK") < events.index("RESPONSE_GENERATED")
    assert notifier.sent == []  # RECOMMENDED does not notify


async def test_whistleblower_hard_stop(tmp_path, monkeypatch):
    agent, audit, _, _ = _er_agent(tmp_path)
    monkeypatch.setattr(
        agent, "_call_llm",
        lambda system, messages: (_ for _ in ()).throw(AssertionError("no LLM")),
    )
    response = await agent.handle(
        _request("employee filed a 公益通報 about accounting irregularities")
    )
    assert response.hitl_tier == HITLTier.MANDATORY
    assert "WHISTLEBLOWER" in response.jurisdiction_flags


async def test_payload_jurisdiction_defaults_from_envelope(tmp_path, monkeypatch):
    agent, _, storage, _ = _er_agent(tmp_path)

    async def fake_llm(system, messages):
        return "guidance"

    monkeypatch.setattr(agent, "_call_llm", fake_llm)
    # No jurisdiction_code in payload — must inherit from the request envelope.
    response = await agent.handle(_request("question about attendance policy"))
    assert response.error is None
    assert response.full_output_ref is not None
