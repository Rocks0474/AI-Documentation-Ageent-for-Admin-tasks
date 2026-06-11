"""End-to-end orchestration tests on LOCAL adapters.

Exercises the compiled LangGraph workflow across the key paths: a clean
single-agent run, the ER HARD_STOP -> HITL interrupt -> approval -> resume
cycle, the Legal LOW-confidence escalation with watermark preservation, and the
PII boundary short-circuit. LLM calls are mocked; everything else is real.
"""

from __future__ import annotations

from adapters.local.audit_log import LocalAuditLogAdapter
from adapters.local.notification import LocalNotificationAdapter
from adapters.local.storage import LocalStorageAdapter
from adapters.local.vector_db import LocalVectorDBAdapter
from orchestration.graph import (
    build_graph,
    build_registry,
    resume_with_approval,
    run_workflow,
)
from schemas.common import AgentRequest, Jurisdiction
from schemas.legal import LEGAL_WATERMARK


def _build_env(tmp_path):
    audit = LocalAuditLogAdapter()
    storage = LocalStorageAdapter(root=str(tmp_path))
    notifier = LocalNotificationAdapter()
    registry = build_registry(
        audit_log=audit,
        storage=storage,
        notification=notifier,
        vector_db=LocalVectorDBAdapter(),
    )

    async def fake_llm(system, messages):
        return "Reasoned guidance.\nCONFIDENCE: HIGH"

    for agent in (
        registry.director,
        registry.er,
        registry.legal,
        registry.hrbp,
        registry.hr_ops,
    ):
        agent._call_llm = fake_llm

    graph = build_graph(registry)
    return graph, audit, storage, notifier


# ---------------------------------------------------------------------------
# Clean single-agent path (Analytics, no HITL)
# ---------------------------------------------------------------------------

async def test_analytics_workflow_completes(tmp_path):
    graph, audit, _, notifier = _build_env(tmp_path)
    request = AgentRequest(
        source="HUMAN_HR",
        jurisdiction_code=Jurisdiction.JP,
        requesting_user_role="HRBP",
        payload={
            "intent": "attrition turnover dashboard",
            "metric": "attrition_rate",
            "cohort_ref": "cohort_eng_jp",
            "cohort_size": 50,
        },
    )
    state = await run_workflow(graph, request, thread_id="analytics-1")

    assert state["final"]["error"] is None
    assert state["final"]["agent_id"] == "ANALYTICS_AGENT"
    assert state.get("hitl_pending") in (False, None)
    events = [e.event_type for e in await audit.query(request.request_id)]
    assert events[0] == "WORKFLOW_ROUTED"
    assert events[-1] == "WORKFLOW_COMPLETED"
    assert notifier.sent == []


# ---------------------------------------------------------------------------
# ER clear path -> Module A runs
# ---------------------------------------------------------------------------

async def test_er_clear_runs_module_a(tmp_path):
    graph, audit, storage, notifier = _build_env(tmp_path)
    request = AgentRequest(
        source="HUMAN_HR",
        jurisdiction_code=Jurisdiction.JP,
        requesting_user_role="HRBP",
        payload={
            "intent": "employee grievance about scheduling",
            "case_summary": "employee grievance about shift scheduling fairness",
        },
    )
    state = await run_workflow(graph, request, thread_id="er-clear-1")

    assert state["final"]["agent_id"] == "ER_AGENT"
    assert state["final"]["hitl_tier"] == "RECOMMENDED"
    assert state["final"]["full_output_ref"].startswith("er/")
    events = [e.event_type for e in await audit.query(request.request_id)]
    assert "ER_COMPLIANCE_CHECK" in events
    assert "HITL_PENDING" not in events
    assert notifier.sent == []


# ---------------------------------------------------------------------------
# ER HARD_STOP -> HITL interrupt -> approval -> resume
# ---------------------------------------------------------------------------

async def test_er_hard_stop_suspends_then_resumes_with_approval(tmp_path):
    graph, audit, _, notifier = _build_env(tmp_path)
    request = AgentRequest(
        source="HUMAN_HR",
        jurisdiction_code=Jurisdiction.JP,
        requesting_user_role="HRBP",
        hitl_approver="#er-hitl",
        payload={
            "intent": "termination of employee",
            "case_summary": "manager wants to proceed with termination of employee",
        },
    )
    state = await run_workflow(graph, request, thread_id="er-hard-1")

    # Suspended at the HITL gate.
    assert state.get("hitl_pending") is True
    assert state["final"]["hitl_tier"] == "MANDATORY"
    assert "TERMINATION" in state["final"]["jurisdiction_flags"]
    assert "LEGAL_AGENT_REQUIRED" in state["final"]["jurisdiction_flags"]
    assert len(notifier.sent) == 1  # CHRO escalation fired

    events_mid = [e.event_type for e in await audit.query(request.request_id)]
    assert events_mid == ["WORKFLOW_ROUTED", "ER_COMPLIANCE_CHECK", "HITL_PENDING"]

    # External workflow posts approval; workflow resumes and completes.
    await resume_with_approval(graph, "er-hard-1", approver_id="chro@corp")
    entries = await audit.query(request.request_id)
    events = [e.event_type for e in entries]
    assert events[-1] == "WORKFLOW_COMPLETED"
    hitl_entry = next(e for e in entries if e.event_type == "HITL_PENDING")
    # Constraint #5: approval provenance written by the workflow, not an agent.
    assert hitl_entry.approver_id == "chro@corp"
    assert hitl_entry.approved_at is not None


# ---------------------------------------------------------------------------
# Legal LOW confidence -> HITL, watermark preserved
# ---------------------------------------------------------------------------

async def test_legal_multi_jurisdiction_escalates_and_keeps_watermark(tmp_path):
    graph, _, _, notifier = _build_env(tmp_path)
    request = AgentRequest(
        source="HUMAN_HR",
        jurisdiction_code=Jurisdiction.MULTI,
        requesting_user_role="CHRO",
        hitl_approver="#legal-hitl",
        payload={
            "intent": "need a legal opinion on jurisdiction",
            "question": "cross-border termination question",
        },
    )
    state = await run_workflow(graph, request, thread_id="legal-1")

    assert state.get("hitl_pending") is True
    assert state["final"]["confidence"] == "LOW"
    assert state["final"]["hitl_tier"] == "MANDATORY"
    assert "WATERMARKED" in state["final"]["jurisdiction_flags"]
    assert state["final"]["detail"] == LEGAL_WATERMARK  # watermark survived
    assert len(notifier.sent) == 1


# ---------------------------------------------------------------------------
# PII boundary -> short-circuit before any agent runs
# ---------------------------------------------------------------------------

async def test_pii_violation_short_circuits(tmp_path):
    graph, audit, _, notifier = _build_env(tmp_path)
    request = AgentRequest(
        source="HUMAN_HR",
        jurisdiction_code=Jurisdiction.JP,
        requesting_user_role="HRBP",
        payload={"intent": "compensation review", "name": "Jane Doe"},
    )
    state = await run_workflow(graph, request, thread_id="pii-1")

    assert state["final"]["error"] == "PII_BOUNDARY_VIOLATION"
    assert "Jane Doe" not in (state["final"]["detail"] or "")
    events = [e.event_type for e in await audit.query(request.request_id)]
    assert "PII_BOUNDARY_VIOLATION" in events
    # No agent-specific work happened.
    assert "ER_COMPLIANCE_CHECK" not in events
