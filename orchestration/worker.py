"""Queue-consumer worker — drives the orchestration graph from a QueueAdapter.

The worker pulls messages from the ingress topic, deserializes each into an
:class:`AgentRequest`, and runs it through the LangGraph orchestration graph
(entering at the Director Agent). It handles every terminal state:

  - COMPLETED      — the workflow finished; the message is acked.
  - HITL_PENDING   — the workflow suspended at the HITL gate awaiting human
                     approval; the message is acked (the work is parked, and
                     resumes later via the approval API on the same thread id).
  - INVALID        — the message could not be parsed (poison); it is acked and
                     dropped so it does not redeliver forever.
  - ERROR          — processing raised (e.g. a transient downstream failure);
                     the message is NOT acked, so the broker redelivers it.

The graph thread id is the request id, so an approval posted later via
``orchestration.graph.resume_with_approval`` resumes the exact suspended run.

Note: the in-process MemorySaver checkpointer means the worker and the approval
API must share one graph instance. Production needs a durable checkpointer so
suspended HITL runs survive restarts and span processes — see DEPLOYMENT notes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import structlog

from adapters.base.queue import QueueAdapter, QueueMessage
from orchestration.graph import run_workflow
from schemas.common import AgentRequest

logger = structlog.get_logger()

# Topic the worker consumes ingress requests from. Maps to the GCP routing
# subscription / the AWS SQS routing queue in the deployed environments.
DEFAULT_TOPIC = "routing"


class WorkerStatus(str, Enum):
    COMPLETED = "COMPLETED"
    HITL_PENDING = "HITL_PENDING"
    INVALID = "INVALID"
    ERROR = "ERROR"


@dataclass
class WorkerResult:
    status: WorkerStatus
    message_id: str
    request_id: Optional[str] = None
    final: Optional[dict] = None
    detail: Optional[str] = None

    @property
    def acked(self) -> bool:
        """Whether a message in this state should be acknowledged."""
        return self.status in (
            WorkerStatus.COMPLETED,
            WorkerStatus.HITL_PENDING,
            WorkerStatus.INVALID,
        )


class QueueWorker:
    def __init__(
        self,
        graph,
        queue: QueueAdapter,
        *,
        topic: str = DEFAULT_TOPIC,
        batch_size: int = 10,
        poll_interval: float = 1.0,
    ) -> None:
        self._graph = graph
        self._queue = queue
        self._topic = topic
        self._batch_size = batch_size
        self._poll_interval = poll_interval

    @staticmethod
    def _to_request(body: dict) -> AgentRequest:
        # Accept the AgentRequest dump directly, or wrapped under "request".
        if isinstance(body.get("request"), dict):
            body = body["request"]
        return AgentRequest.model_validate(body)

    async def _process(self, message: QueueMessage) -> WorkerResult:
        try:
            request = self._to_request(message.body)
        except Exception as exc:  # noqa: BLE001 - poison message => drop
            logger.warning(
                "worker.invalid_message",
                message_id=message.message_id,
                error=type(exc).__name__,
            )
            return WorkerResult(
                WorkerStatus.INVALID, message.message_id, detail=type(exc).__name__
            )

        state = await run_workflow(self._graph, request, thread_id=request.request_id)
        final = state.get("final")
        if state.get("hitl_pending"):
            logger.info(
                "worker.hitl_pending",
                request_id=request.request_id,
                agent_id=(final or {}).get("agent_id"),
                hitl_basis=(final or {}).get("hitl_basis"),
            )
            return WorkerResult(
                WorkerStatus.HITL_PENDING, message.message_id, request.request_id, final
            )

        logger.info(
            "worker.completed",
            request_id=request.request_id,
            agent_id=(final or {}).get("agent_id"),
            error=(final or {}).get("error"),
        )
        return WorkerResult(
            WorkerStatus.COMPLETED, message.message_id, request.request_id, final
        )

    async def run_once(self) -> list[WorkerResult]:
        """Pull and process one batch; ack successful/handled messages."""
        messages = await self._queue.pull(self._topic, max_messages=self._batch_size)
        results: list[WorkerResult] = []
        for message in messages:
            try:
                result = await self._process(message)
            except Exception as exc:  # noqa: BLE001 - transient => redeliver
                logger.error(
                    "worker.processing_error",
                    message_id=message.message_id,
                    error=type(exc).__name__,
                )
                results.append(
                    WorkerResult(
                        WorkerStatus.ERROR,
                        message.message_id,
                        detail=type(exc).__name__,
                    )
                )
                continue  # do NOT ack — let the broker redeliver

            if result.acked:
                await self._queue.ack(self._topic, message.message_id)
            results.append(result)
        return results

    async def run_forever(self, stop_event: Optional[asyncio.Event] = None) -> None:
        """Poll-process until ``stop_event`` is set (graceful shutdown)."""
        stop_event = stop_event or asyncio.Event()
        logger.info("worker.start", topic=self._topic, batch_size=self._batch_size)
        while not stop_event.is_set():
            results = await self.run_once()
            if not results:
                # Idle backoff that still responds promptly to a stop signal.
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=self._poll_interval
                    )
                except asyncio.TimeoutError:
                    pass
        logger.info("worker.stop")


def build_default_worker(*, topic: str = DEFAULT_TOPIC) -> QueueWorker:
    """Build a worker wired to factory adapters and a fresh graph.

    Adapters resolve via the factory (CLOUD_TARGET-driven), so the same worker
    runs on LOCAL / GCP / AWS. Real LLM-backed agents require an Anthropic key;
    deterministic agents run without one.
    """
    from adapters.factory import get_queue
    from orchestration.graph import build_graph, build_registry

    registry = build_registry()
    graph = build_graph(registry)
    return QueueWorker(graph, get_queue(), topic=topic)
