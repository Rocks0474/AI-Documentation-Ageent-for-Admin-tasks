"""End-to-end tests for the FastAPI ingestion + approval API on LOCAL adapters.

Uses an in-process ASGI transport so the API, the shared graph, and the worker
all run on one event loop. The worker is driven manually (run_once) between
steps for determinism. LLM calls are mocked.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import MemorySaver

from adapters.local.audit_log import LocalAuditLogAdapter
from adapters.local.notification import LocalNotificationAdapter
from adapters.local.queue import LocalQueueAdapter
from adapters.local.storage import LocalStorageAdapter
from adapters.local.vector_db import LocalVectorDBAdapter
from orchestration.graph import build_registry
from service.api import create_app
from service.context import build_context


def _make_context(tmp_path, *, llm_overrides=None):
    audit = LocalAuditLogAdapter()
    registry = build_registry(
        audit_log=audit,
        storage=LocalStorageAdapter(root=str(tmp_path)),
        notification=LocalNotificationAdapter(),
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
    for name, override in (llm_overrides or {}).items():
        getattr(registry, name)._call_llm = override

    return build_context(
        registry=registry,
        queue=LocalQueueAdapter(),
        audit=audit,
        checkpointer=MemorySaver(),
    )


def _client(context):
    app = create_app(context=context, run_worker=False)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _request_body(**payload) -> dict:
    return {
        "source": "HUMAN_HR",
        "jurisdiction_code": "JP",
        "requesting_user_role": "HRBP",
        "hitl_approver": "#hr-hitl",
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

async def test_healthz(tmp_path):
    ctx = _make_context(tmp_path)
    async with _client(ctx) as client:
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Ingest -> worker -> completed status
# ---------------------------------------------------------------------------

async def test_ingest_then_status_completed(tmp_path):
    ctx = _make_context(tmp_path)
    async with _client(ctx) as client:
        body = _request_body(
            intent="attrition turnover dashboard",
            metric="attrition_rate",
            cohort_ref="cohort_eng_jp",
            cohort_size=50,
        )
        resp = await client.post("/requests", json=body)
        assert resp.status_code == 202
        rid = resp.json()["request_id"]

        # Before the worker runs: QUEUED.
        status = (await client.get(f"/requests/{rid}")).json()
        assert status["status"] == "QUEUED"

        await ctx.worker.run_once()  # drive the queue

        status = (await client.get(f"/requests/{rid}")).json()
        assert status["status"] == "COMPLETED"
        assert status["final"]["agent_id"] == "ANALYTICS_AGENT"
        assert status["events"][0]["event_type"] == "WORKFLOW_ROUTED"
        assert status["events"][-1]["event_type"] == "WORKFLOW_COMPLETED"


# ---------------------------------------------------------------------------
# PII gated at ingestion — never enters the queue
# ---------------------------------------------------------------------------

async def test_ingest_rejects_pii(tmp_path):
    ctx = _make_context(tmp_path)
    async with _client(ctx) as client:
        body = _request_body(intent="comp review", name="Jane Doe")
        resp = await client.post("/requests", json=body)
        assert resp.status_code == 422
        assert resp.json()["detail"]["error"] == "PII_BOUNDARY_VIOLATION"
        assert "Jane Doe" not in str(resp.json())
        # Nothing was queued.
        assert await ctx.queue.pull(ctx.topic) == []


# ---------------------------------------------------------------------------
# Full HITL lifecycle: ingest -> pending -> approve -> completed
# ---------------------------------------------------------------------------

async def test_hitl_lifecycle_ingest_pending_approve(tmp_path):
    ctx = _make_context(tmp_path)
    async with _client(ctx) as client:
        body = _request_body(
            intent="termination of employee",
            case_summary="manager wants to proceed with termination of employee",
        )
        rid = (await client.post("/requests", json=body)).json()["request_id"]
        await ctx.worker.run_once()

        status = (await client.get(f"/requests/{rid}")).json()
        assert status["status"] == "PENDING_APPROVAL"
        assert status["final"]["hitl_tier"] == "MANDATORY"
        assert "TERMINATION" in status["final"]["jurisdiction_flags"]

        # Approve -> resumes the suspended run.
        approve = await client.post(
            f"/requests/{rid}/approve", json={"approver_id": "chro@corp"}
        )
        assert approve.status_code == 200
        assert approve.json()["status"] == "COMPLETED"

        status = (await client.get(f"/requests/{rid}")).json()
        assert status["status"] == "COMPLETED"
        # Approval provenance recorded by the workflow (Constraint #5).
        hitl = next(e for e in status["events"] if e["event_type"] == "HITL_PENDING")
        assert hitl["approver_id"] == "chro@corp"


# ---------------------------------------------------------------------------
# Approve error cases
# ---------------------------------------------------------------------------

async def test_approve_unknown_request_404(tmp_path):
    ctx = _make_context(tmp_path)
    async with _client(ctx) as client:
        resp = await client.post(
            "/requests/does-not-exist/approve", json={"approver_id": "x"}
        )
        assert resp.status_code == 404


async def test_approve_completed_request_409(tmp_path):
    ctx = _make_context(tmp_path)
    async with _client(ctx) as client:
        body = _request_body(
            intent="attrition turnover dashboard",
            metric="m", cohort_ref="c", cohort_size=50,
        )
        rid = (await client.post("/requests", json=body)).json()["request_id"]
        await ctx.worker.run_once()  # completes (not a HITL case)
        resp = await client.post(
            f"/requests/{rid}/approve", json={"approver_id": "x"}
        )
        assert resp.status_code == 409
