"""Shared service context — one graph instance for the API and the worker.

The HTTP API (which posts approvals) and the queue worker (which suspends runs
at the HITL gate) must operate over the *same* compiled graph + checkpointer, or
an approval cannot resume the run that was suspended. :class:`ServiceContext`
builds that single shared instance.

Checkpointer selection (the durable HITL store):

  - Default / dev: in-process ``MemorySaver`` — fine when the API and worker run
    in one process; suspended runs do not survive a restart.
  - Production: an ``AsyncPostgresSaver`` (the ``postgres`` extra) when
    ``CHECKPOINTER_DB_URL`` / ``DATABASE_URL`` is a Postgres DSN — so suspended
    HITL runs are durable and shared across API and worker processes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from adapters.base.audit_log import AuditLogAdapter
from adapters.base.queue import QueueAdapter
from adapters.factory import get_audit_log, get_queue
from orchestration.graph import AgentRegistry, build_graph, build_registry
from orchestration.worker import QueueWorker
from pii_gateway.detector import PIIDetector

DEFAULT_TOPIC = "routing"


@dataclass
class ServiceContext:
    registry: AgentRegistry
    graph: object
    queue: QueueAdapter
    audit: AuditLogAdapter
    worker: QueueWorker
    pii_detector: PIIDetector
    topic: str


def _memory_saver():
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


async def build_checkpointer_async():
    """Return a checkpointer based on env config (Postgres if a DSN is set)."""
    dsn = os.environ.get("CHECKPOINTER_DB_URL") or os.environ.get("DATABASE_URL")
    if dsn and dsn.startswith(("postgres://", "postgresql://")):
        return await build_postgres_checkpointer(dsn)
    return _memory_saver()


async def build_postgres_checkpointer(dsn: str):
    """Build and set up an AsyncPostgresSaver (requires the ``postgres`` extra)."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(dsn, open=False, kwargs={"autocommit": True})
    await pool.open()
    saver = AsyncPostgresSaver(pool)
    await saver.setup()  # idempotent — creates checkpoint tables if absent
    return saver


def build_context(
    *,
    checkpointer=None,
    registry: AgentRegistry | None = None,
    queue: QueueAdapter | None = None,
    audit: AuditLogAdapter | None = None,
    topic: str = DEFAULT_TOPIC,
) -> ServiceContext:
    """Build a context with a given (or in-memory) checkpointer.

    Adapters resolve via the factory by default, so registry agents, the queue,
    and the audit log all share the active ``CLOUD_TARGET`` implementations.
    ``queue`` / ``audit`` (and ``registry``) may be injected for tests.
    """
    registry = registry or build_registry()
    graph = build_graph(registry, checkpointer=checkpointer or _memory_saver())
    queue = queue or get_queue()
    audit = audit or get_audit_log()
    return ServiceContext(
        registry=registry,
        graph=graph,
        queue=queue,
        audit=audit,
        worker=QueueWorker(graph, queue, topic=topic),
        pii_detector=PIIDetector(),
        topic=topic,
    )


async def build_context_async(*, topic: str = DEFAULT_TOPIC) -> ServiceContext:
    """Build a context, selecting the checkpointer from the environment."""
    checkpointer = await build_checkpointer_async()
    return build_context(checkpointer=checkpointer, topic=topic)
