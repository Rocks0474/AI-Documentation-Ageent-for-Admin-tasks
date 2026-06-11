"""Unit tests for BaseAgent.handle() — PII gate and audit-first ordering."""

from __future__ import annotations

from typing import Optional

import pytest

from adapters.base.audit_log import AuditEntry, AuditLogAdapter
from adapters.local.audit_log import LocalAuditLogAdapter
from adapters.local.notification import LocalNotificationAdapter
from agents.base.agent import BaseAgent
from schemas.common import AgentRequest, AgentResponse, HITLTier, Jurisdiction


class _RecordingAuditLog(LocalAuditLogAdapter):
    """Audit log that snapshots the event sequence at append time."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[str] = []

    async def append(self, entry: AuditEntry) -> str:
        self.events.append(entry.event_type)
        return await super().append(entry)


class _EchoAgent(BaseAgent):
    agent_id = "ECHO_AGENT"

    def __init__(self, *, audit_log: AuditLogAdapter, notification, hitl=HITLTier.NONE):
        super().__init__(audit_log=audit_log, notification=notification)
        self.processed = False
        self.events_at_process: Optional[list[str]] = None
        self._hitl = hitl

    async def process(self, request: AgentRequest) -> AgentResponse:
        self.processed = True
        # Snapshot what the audit log already contains when process() runs.
        self.events_at_process = list(getattr(self.audit_log, "events", []))
        return AgentResponse(
            request_id=request.request_id,
            agent_id=self.agent_id,
            hitl_tier=self._hitl,
            hitl_basis="test-basis" if self._hitl != HITLTier.NONE else None,
        )


def _request(**payload) -> AgentRequest:
    return AgentRequest(
        source="HUMAN_HR",
        jurisdiction_code=Jurisdiction.JP,
        requesting_user_role="HRBP",
        hitl_approver="#hr-hitl",
        payload=payload,
    )


async def test_pii_violation_short_circuits_before_process():
    audit = _RecordingAuditLog()
    agent = _EchoAgent(audit_log=audit, notification=LocalNotificationAdapter())

    response = await agent.handle(_request(name="Jane Doe"))

    assert response.error == "PII_BOUNDARY_VIOLATION"
    assert response.hitl_tier == HITLTier.MANDATORY
    assert agent.processed is False
    assert audit.events == ["PII_BOUNDARY_VIOLATION"]
    # Summary must not leak the offending value.
    assert "Jane Doe" not in (response.detail or "")


async def test_audit_entry_written_before_process_runs():
    audit = _RecordingAuditLog()
    agent = _EchoAgent(audit_log=audit, notification=LocalNotificationAdapter())

    response = await agent.handle(_request(intent="policy question"))

    assert agent.processed is True
    # REQUEST_RECEIVED was already logged when process() ran (Constraint #3).
    assert agent.events_at_process == ["REQUEST_RECEIVED"]
    assert audit.events == ["REQUEST_RECEIVED", "RESPONSE_GENERATED"]
    assert response.error is None


async def test_mandatory_hitl_sends_notification():
    audit = _RecordingAuditLog()
    notifier = LocalNotificationAdapter()
    agent = _EchoAgent(audit_log=audit, notification=notifier, hitl=HITLTier.MANDATORY)

    await agent.handle(_request(intent="needs human sign-off"))

    assert len(notifier.sent) == 1
    assert notifier.sent[0].recipient == "#hr-hitl"
    assert notifier.sent[0].priority == "critical"


async def test_process_error_is_logged_then_reraised():
    audit = _RecordingAuditLog()

    class _BoomAgent(BaseAgent):
        agent_id = "BOOM_AGENT"

        async def process(self, request: AgentRequest) -> AgentResponse:
            raise RuntimeError("kaboom")

    agent = _BoomAgent(audit_log=audit, notification=LocalNotificationAdapter())
    with pytest.raises(RuntimeError, match="kaboom"):
        await agent.handle(_request(intent="trigger error"))

    assert audit.events == ["REQUEST_RECEIVED", "PROCESSING_ERROR"]
