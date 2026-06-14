"""End-to-end tests for the queue-consumer worker on LOCAL adapters.

Publishes AgentRequests to a LOCAL queue, runs the worker, and asserts it drives
the orchestration graph and handles each terminal state with the right ack
semantics. LLM calls are mocked.
"""

from __future__ import annotations

from adapters.local.audit_log import LocalAuditLogAdapter
from adapters.local.notification import LocalNotificationAdapter
from adapters.local.queue import LocalQueueAdapter
from adapters.local.storage import LocalStorageAdapter
from adapters.local.vector_db import LocalVectorDBAdapter
from orchestration.graph import build_graph, build_registry, resume_with_approval
from orchestration.worker import QueueWorker, WorkerStatus
from schemas.common import AgentRequest, Jurisdiction

TOPIC = "routing"


class _RecordingQueue(LocalQueueAdapter):
    """LOCAL queue that records which message ids were acknowledged."""

    def __init__(self) -> None:
        super().__init__()
        self.acked: list[str] = []

    async def ack(self, topic: str, message_id: str) -> None:
        self.acked.append(message_id)
        await super().ack(topic, message_id)


def _build_env(tmp_path, *, llm_overrides=None):
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
    for name, override in (llm_overrides or {}).items():
        getattr(registry, name)._call_llm = override

    graph = build_graph(registry)
    queue = _RecordingQueue()
    worker = QueueWorker(graph, queue, topic=TOPIC, batch_size=10)
    return worker, graph, queue, audit, notifier


def _request(**payload) -> AgentRequest:
    return AgentRequest(
        source="HUMAN_HR",
        jurisdiction_code=Jurisdiction.JP,
        requesting_user_role="HRBP",
        hitl_approver="#hr-hitl",
        payload=payload,
    )


async def _publish(queue, request: AgentRequest) -> str:
    return await queue.publish(TOPIC, request.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Happy path — completes and acks
# ---------------------------------------------------------------------------

async def test_worker_processes_request_and_acks(tmp_path):
    worker, _, queue, audit, _ = _build_env(tmp_path)
    request = _request(
        intent="attrition turnover dashboard",
        metric="attrition_rate",
        cohort_ref="cohort_eng_jp",
        cohort_size=50,
    )
    mid = await _publish(queue, request)

    results = await worker.run_once()

    assert len(results) == 1
    assert results[0].status == WorkerStatus.COMPLETED
    assert results[0].request_id == request.request_id
    assert queue.acked == [mid]  # acknowledged
    events = [e.event_type for e in await audit.query(request.request_id)]
    assert events[0] == "WORKFLOW_ROUTED" and events[-1] == "WORKFLOW_COMPLETED"
    # Queue is drained.
    assert await worker.run_once() == []


# ---------------------------------------------------------------------------
# HITL — suspends, acks, and is resumable on the same thread id
# ---------------------------------------------------------------------------

async def test_worker_hitl_suspends_acks_and_resumes(tmp_path):
    worker, graph, queue, audit, notifier = _build_env(tmp_path)
    request = _request(
        intent="termination of employee",
        case_summary="manager wants to proceed with termination of employee",
    )
    mid = await _publish(queue, request)

    results = await worker.run_once()

    assert results[0].status == WorkerStatus.HITL_PENDING
    assert results[0].final["hitl_tier"] == "MANDATORY"
    assert "TERMINATION" in results[0].final["jurisdiction_flags"]
    assert queue.acked == [mid]  # parked work is acked
    assert len(notifier.sent) == 1  # CHRO escalation fired

    # The approval API (later) resumes the exact suspended run via request_id.
    await resume_with_approval(graph, request.request_id, approver_id="chro@corp")
    entries = await audit.query(request.request_id)
    assert [e.event_type for e in entries][-1] == "WORKFLOW_COMPLETED"
    hitl = next(e for e in entries if e.event_type == "HITL_PENDING")
    assert hitl.approver_id == "chro@corp"


# ---------------------------------------------------------------------------
# Poison message — invalid body is acked and dropped
# ---------------------------------------------------------------------------

async def test_worker_drops_invalid_message(tmp_path):
    worker, _, queue, _, _ = _build_env(tmp_path)
    mid = await queue.publish(TOPIC, {"not": "an AgentRequest"})

    results = await worker.run_once()

    assert results[0].status == WorkerStatus.INVALID
    assert queue.acked == [mid]  # dropped, not redelivered forever


# ---------------------------------------------------------------------------
# Transient error — NOT acked, so the broker redelivers
# ---------------------------------------------------------------------------

async def test_worker_does_not_ack_on_processing_error(tmp_path):
    async def boom(system, messages):
        raise RuntimeError("downstream blip")

    worker, _, queue, _, _ = _build_env(tmp_path, llm_overrides={"hrbp": boom})
    request = _request(intent="team engagement and retention strategy")
    await _publish(queue, request)

    results = await worker.run_once()

    assert results[0].status == WorkerStatus.ERROR
    assert queue.acked == []  # not acked => will redeliver


# ---------------------------------------------------------------------------
# Batch — mixed outcomes in one pull
# ---------------------------------------------------------------------------

async def test_worker_processes_a_batch(tmp_path):
    worker, _, queue, _, _ = _build_env(tmp_path)
    r1 = _request(
        intent="attrition turnover dashboard",
        metric="m", cohort_ref="c", cohort_size=50,
    )
    r2 = _request(intent="candidate pipeline interview", requisition_ref="req-1", role_title="SWE")
    await _publish(queue, r1)
    await _publish(queue, r2)

    results = await worker.run_once()
    assert {r.status for r in results} == {WorkerStatus.COMPLETED}
    assert len(queue.acked) == 2


# ---------------------------------------------------------------------------
# Factory wiring — build_default_worker assembles agents + graph under LOCAL
# ---------------------------------------------------------------------------

def test_build_default_worker_wires_factory(monkeypatch):
    from adapters import factory
    from orchestration.worker import QueueWorker, build_default_worker

    monkeypatch.setenv("CLOUD_TARGET", "LOCAL")
    factory.reset_factory()
    try:
        worker = build_default_worker(topic="routing")
        assert isinstance(worker, QueueWorker)
    finally:
        factory.reset_factory()
