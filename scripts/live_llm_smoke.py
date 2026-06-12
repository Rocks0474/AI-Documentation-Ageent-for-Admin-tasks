#!/usr/bin/env python3
"""Live LLM smoke test — Director routes a simple HRBP request end-to-end.

Runs the full stack on LOCAL adapters with a REAL Anthropic call (no mocking):

  1. publishes an HRBP-intent AgentRequest to the queue,
  2. the worker drives the LangGraph graph (Director routes -> HRBP),
  3. the HRBP agent makes a real Claude call (BaseAgent.model),
  4. prints the routing, the audit trail, and the model's actual output.

Requires ``ANTHROPIC_API_KEY`` (and network egress to api.anthropic.com).
Costs a few cents. Run from the repo root:

    ANTHROPIC_API_KEY=sk-ant-... python scripts/live_llm_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

# Allow running as `python scripts/live_llm_smoke.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force the LOCAL infrastructure target before anything reads CLOUD_TARGET.
os.environ.setdefault("CLOUD_TARGET", "LOCAL")

from adapters.base.storage import DataZone  # noqa: E402
from adapters.local.audit_log import LocalAuditLogAdapter  # noqa: E402
from adapters.local.notification import LocalNotificationAdapter  # noqa: E402
from adapters.local.queue import LocalQueueAdapter  # noqa: E402
from adapters.local.storage import LocalStorageAdapter  # noqa: E402
from adapters.local.vector_db import LocalVectorDBAdapter  # noqa: E402
from agents.base.agent import BaseAgent  # noqa: E402
from orchestration.graph import build_graph, build_registry  # noqa: E402
from orchestration.worker import QueueWorker  # noqa: E402
from schemas.common import AgentRequest, Jurisdiction  # noqa: E402

TOPIC = "routing"


async def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY is not set.\n"
            "Run:  ANTHROPIC_API_KEY=sk-ant-... python scripts/live_llm_smoke.py",
            file=sys.stderr,
        )
        return 2

    audit = LocalAuditLogAdapter()
    storage = LocalStorageAdapter(root=tempfile.mkdtemp(prefix="hr-smoke-"))
    queue = LocalQueueAdapter()
    registry = build_registry(
        audit_log=audit,
        storage=storage,
        notification=LocalNotificationAdapter(),
        vector_db=LocalVectorDBAdapter(),
    )
    graph = build_graph(registry)
    worker = QueueWorker(graph, queue, topic=TOPIC)

    print(f"Model: {BaseAgent.model}  |  CLOUD_TARGET={os.environ['CLOUD_TARGET']}\n")

    request = AgentRequest(
        source="HUMAN_HR",
        jurisdiction_code=Jurisdiction.JP,
        requesting_user_role="MANAGER",
        payload={
            "intent": "team engagement and retention strategy for engineering",
            "topic": "rising attrition signals in the engineering cohort",
            "cohort_ref": "cohort_eng_jp",
        },
    )

    # Show the deterministic routing decision (no LLM needed for this step).
    decision = await registry.director.route(request)
    print(f"Director routed -> {decision.target_domain.value} "
          f"(priority={decision.priority.value})")

    # Publish to the queue and let the worker drive the graph (real LLM call).
    await queue.publish(TOPIC, request.model_dump(mode="json"))
    print("Calling Claude via the HRBP agent ...\n")
    results = await worker.run_once()

    result = results[0]
    print(f"Worker status: {result.status.value}")
    final = result.final or {}
    print(f"Final agent:   {final.get('agent_id')}")
    print(f"HITL tier:     {final.get('hitl_tier')}")

    events = [e.event_type for e in await audit.query(request.request_id)]
    print(f"Audit trail:   {events}\n")

    ref = final.get("full_output_ref")
    if ref:
        output = (await storage.get(ref, DataZone.ZONE2)).decode("utf-8")
        print("=== HRBP recommendation (live Claude output) ===")
        print(output.strip())
    else:
        print("No output reference produced.")
        print("Detail:", final.get("detail"))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
