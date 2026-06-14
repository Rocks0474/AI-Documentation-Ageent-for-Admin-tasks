"""LOCAL AuditLogAdapter — in-memory append-only log.

Durable for the lifetime of the process, which is sufficient for local
development and tests. ``append`` returns only after the entry is recorded, so
callers can rely on it for the audit-first ordering guarantee (Constraint #3).
``approver_id`` / ``approved_at`` are only ever set via
:meth:`record_approval` (Constraint #5).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from adapters.base.audit_log import AuditEntry, AuditLogAdapter


class LocalAuditLogAdapter(AuditLogAdapter):
    def __init__(self) -> None:
        self._entries: dict[str, AuditEntry] = {}
        self._order: list[str] = []
        self._lock = asyncio.Lock()

    async def append(self, entry: AuditEntry) -> str:
        async with self._lock:
            self._entries[entry.entry_id] = entry
            self._order.append(entry.entry_id)
        return entry.entry_id

    async def get(self, entry_id: str) -> Optional[AuditEntry]:
        return self._entries.get(entry_id)

    async def query(self, request_id: str) -> list[AuditEntry]:
        return [
            self._entries[eid]
            for eid in self._order
            if self._entries[eid].request_id == request_id
        ]

    async def record_approval(
        self,
        entry_id: str,
        approver_id: str,
        approved_at: Optional[datetime] = None,
    ) -> AuditEntry:
        async with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                raise KeyError(entry_id)
            updated = entry.model_copy(
                update={
                    "approver_id": approver_id,
                    "approved_at": approved_at or datetime.now(timezone.utc),
                }
            )
            self._entries[entry_id] = updated
        return updated


_adapter: Optional[LocalAuditLogAdapter] = None


def get_adapter() -> LocalAuditLogAdapter:
    global _adapter
    if _adapter is None:
        _adapter = LocalAuditLogAdapter()
    return _adapter
