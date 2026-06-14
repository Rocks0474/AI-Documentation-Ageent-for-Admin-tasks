"""FastAPI ingestion + approval API over the orchestration graph.

Endpoints:

  - ``POST /requests``                 — validate + PII-gate an AgentRequest,
    publish it to the ingress queue (the worker drives the graph). 202 Accepted.
  - ``GET  /requests/{request_id}``    — status (QUEUED / PROCESSING /
    PENDING_APPROVAL / COMPLETED) + the audit trail.
  - ``POST /requests/{request_id}/approve`` — resume a HITL-suspended run by
    posting the human approver id (Constraint #5: provenance written here, by
    the workflow system, not by an agent).
  - ``GET  /healthz``                  — liveness.

PII is gated at the ingestion boundary so Zone 1 data never even enters the
queue (defence in depth — the graph also gates it).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from orchestration.graph import resume_with_approval
from schemas.common import AgentRequest
from service.context import ServiceContext, build_context_async

logger = structlog.get_logger()


# --- API schemas -----------------------------------------------------------

class IngestAccepted(BaseModel):
    request_id: str
    status: str = "QUEUED"


class ApproveBody(BaseModel):
    approver_id: str = Field(min_length=1)


class AuditEventOut(BaseModel):
    event_type: str
    agent_id: Optional[str] = None
    jurisdiction: Optional[str] = None
    approver_id: Optional[str] = None
    detail: Optional[str] = None
    timestamp: str


class StatusOut(BaseModel):
    request_id: str
    status: str
    events: list[AuditEventOut]
    final: Optional[dict] = None


class ApproveOut(BaseModel):
    request_id: str
    status: str
    final: Optional[dict] = None


def _env_truthy(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _ctx(request: Request) -> ServiceContext:
    return request.app.state.context


def _thread_config(request_id: str) -> dict:
    return {"configurable": {"thread_id": request_id}}


async def _status_and_final(graph, request_id: str, has_events: bool):
    snapshot = await graph.aget_state(_thread_config(request_id))
    if snapshot.values:
        final = snapshot.values.get("final")
        if snapshot.next:  # interrupted before finalize => awaiting approval
            return "PENDING_APPROVAL", final
        return "COMPLETED", final
    return ("PROCESSING" if has_events else "QUEUED"), None


def create_app(
    context: Optional[ServiceContext] = None,
    *,
    run_worker: Optional[bool] = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ctx = getattr(app.state, "context", None)
        if ctx is None:
            ctx = await build_context_async()
            app.state.context = ctx

        do_worker = (
            run_worker
            if run_worker is not None
            else _env_truthy("API_RUN_WORKER", default=True)
        )
        stop = asyncio.Event()
        task = asyncio.create_task(ctx.worker.run_forever(stop)) if do_worker else None
        if task:
            logger.info("api.worker_started", topic=ctx.topic)
        try:
            yield
        finally:
            if task:
                stop.set()
                try:
                    await asyncio.wait_for(task, timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    task.cancel()

    app = FastAPI(title="AI HR Agent Team API", version="0.1.0", lifespan=lifespan)
    if context is not None:
        app.state.context = context

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.post("/requests", status_code=202, response_model=IngestAccepted)
    async def ingest(
        request: AgentRequest, ctx: ServiceContext = Depends(_ctx)
    ) -> IngestAccepted:
        # PII gate at the boundary — Zone 1 data must never enter the queue.
        pii = ctx.pii_detector.scan(request.model_dump())
        if pii.detected:
            raise HTTPException(
                status_code=422,
                detail={"error": "PII_BOUNDARY_VIOLATION", "summary": pii.summary},
            )
        await ctx.queue.publish(ctx.topic, request.model_dump(mode="json"))
        logger.info("api.request_queued", request_id=request.request_id)
        return IngestAccepted(request_id=request.request_id, status="QUEUED")

    @app.get("/requests/{request_id}", response_model=StatusOut)
    async def get_status(
        request_id: str, ctx: ServiceContext = Depends(_ctx)
    ) -> StatusOut:
        entries = await ctx.audit.query(request_id)
        status, final = await _status_and_final(ctx.graph, request_id, bool(entries))
        if status == "QUEUED" and not entries:
            # Could be genuinely unknown; still report QUEUED (idempotent view).
            pass
        events = [
            AuditEventOut(
                event_type=e.event_type,
                agent_id=e.agent_id,
                jurisdiction=e.jurisdiction,
                approver_id=e.approver_id,
                detail=e.detail,
                timestamp=e.timestamp.isoformat(),
            )
            for e in entries
        ]
        return StatusOut(
            request_id=request_id, status=status, events=events, final=final
        )

    @app.post("/requests/{request_id}/approve", response_model=ApproveOut)
    async def approve(
        request_id: str,
        body: ApproveBody,
        ctx: ServiceContext = Depends(_ctx),
    ) -> ApproveOut:
        snapshot = await ctx.graph.aget_state(_thread_config(request_id))
        if not snapshot.values:
            raise HTTPException(status_code=404, detail="Unknown request_id")
        if not snapshot.next:
            raise HTTPException(
                status_code=409, detail="Request is not awaiting approval"
            )
        final_state = await resume_with_approval(
            ctx.graph, request_id, approver_id=body.approver_id
        )
        logger.info(
            "api.request_approved", request_id=request_id, approver_id=body.approver_id
        )
        return ApproveOut(
            request_id=request_id, status="COMPLETED", final=final_state.get("final")
        )

    return app
