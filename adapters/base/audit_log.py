"""AuditLogAdapter — the append-only audit trail interface.

The audit log is the architectural backbone of regulatory compliance
(EU AI Act, GDPR, APPI, J-SOX). Two non-negotiable constraints apply:

Constraint #3 — Audit-first ordering
    ``append()`` must complete and return an ``entry_id`` before an agent
    takes any subsequent action. If ``append()`` fails, the agent halts and
    escalates — it never proceeds with an unlogged action.

Constraint #5 — Approval provenance
    ``AuditEntry.approver_id`` and ``AuditEntry.approved_at`` are populated
    exclusively by the external workflow system (ticketing / HRIS) via
    :meth:`AuditLogAdapter.record_approval`. No agent may set these fields on
    its own entries — they are the architectural proof that a *human* acted,
    not the AI.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditEntry(BaseModel):
    """A single immutable audit-trail record.

    Entries never contain Zone 1 (PII) content. When recording a PII boundary
    violation, only the fact of the violation is stored (``pii_present``), never
    the offending data itself.
    """

    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str  # e.g. REQUEST_RECEIVED, RESPONSE_GENERATED, PII_BOUNDARY_VIOLATION
    agent_id: Optional[str] = None
    request_id: Optional[str] = None
    routing_id: Optional[str] = None
    jurisdiction: Optional[str] = None
    hitl_required: bool = False
    pii_present: bool = False

    # Populated ONLY by the external workflow system via record_approval().
    # Agents must never set these. See Constraint #5.
    approver_id: Optional[str] = None
    approved_at: Optional[datetime] = None

    detail: Optional[str] = None  # human-readable summary only — never PII
    timestamp: datetime = Field(default_factory=_utcnow)


class AuditLogAdapter(ABC):
    """Append-only audit log. Implementations must guarantee durability of a
    record before :meth:`append` returns."""

    @abstractmethod
    async def append(self, entry: AuditEntry) -> str:
        """Durably persist ``entry`` and return its ``entry_id``.

        Must raise on failure to persist — callers rely on a successful return
        as the signal that it is safe to proceed (Constraint #3).
        """
        ...

    @abstractmethod
    async def get(self, entry_id: str) -> Optional[AuditEntry]:
        """Return the entry with ``entry_id``, or ``None`` if absent."""
        ...

    @abstractmethod
    async def query(self, request_id: str) -> list[AuditEntry]:
        """Return all entries for ``request_id`` in chronological order."""
        ...

    @abstractmethod
    async def record_approval(
        self, entry_id: str, approver_id: str, approved_at: Optional[datetime] = None
    ) -> AuditEntry:
        """Attach human-approval provenance to an existing entry.

        This is the ONLY path by which ``approver_id`` / ``approved_at`` are
        set, and it is intended for the external workflow system — not agents
        (Constraint #5).
        """
        ...
