"""BaseAgent — the abstract base every HR agent inherits from.

Enforces the cross-cutting guarantees from the architecture spec:

  - PII gate (Constraint #2): the request is scanned before any processing;
    Zone 1 data => immediate ``PII_BOUNDARY_VIOLATION``, never reaching the LLM.
  - Audit-first ordering (Constraint #3): an audit entry is appended *before*
    ``process()`` runs; if the append fails the agent halts (the exception
    propagates) rather than proceeding unlogged.
  - HITL escalation: a ``MANDATORY`` result notifies the designated approver.

Layer 1 purity: this module imports only ``adapters.base`` / ``adapters.factory``,
``schemas``, ``pii_gateway``, ``structlog``, and (lazily) ``anthropic``. No
cloud-provider SDK is imported, directly or transitively.

The Anthropic client is created lazily on first use so agents can be
instantiated and unit-tested in Phase 1 without the SDK or an API key.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

import structlog

from adapters.base.audit_log import AuditEntry, AuditLogAdapter
from adapters.base.notification import NotificationAdapter
from adapters.base.storage import StorageAdapter
from adapters.base.vector_db import VectorDBAdapter
from adapters.factory import (
    get_audit_log,
    get_notification,
    get_storage,
    get_vector_db,
)
from pii_gateway.detector import PIIDetector
from schemas.common import AgentRequest, AgentResponse, HITLTier

logger = structlog.get_logger()


class BaseAgent(ABC):
    """All nine HR agents inherit from this class.

    Enforces: audit-first pattern, PII detection, HITL gate, data-zone
    constraints, and structured error handling.
    """

    agent_id: str = "BASE_AGENT"  # overridden by subclass: "ER_AGENT", etc.
    model: str = "claude-sonnet-4-20250514"
    SYSTEM_PROMPT_TEMPLATE: str = ""

    def __init__(
        self,
        *,
        audit_log: Optional[AuditLogAdapter] = None,
        storage: Optional[StorageAdapter] = None,
        notification: Optional[NotificationAdapter] = None,
        vector_db: Optional[VectorDBAdapter] = None,
        pii_detector: Optional[PIIDetector] = None,
    ) -> None:
        # Adapters resolve through the factory (CLOUD_TARGET-driven) by default;
        # tests may inject fakes/mocks.
        self.audit_log = audit_log or get_audit_log()
        self.storage = storage or get_storage()
        self.notification = notification or get_notification()
        self.vector_db = vector_db or get_vector_db()
        self.pii_detector = pii_detector or PIIDetector()
        self._client: Any = None  # lazily constructed anthropic.Anthropic()

    @property
    def client(self) -> Any:
        """Lazily construct the Anthropic client (API key from env/SecretsAdapter)."""
        if self._client is None:
            import anthropic  # imported lazily — not needed for Phase 1 tests

            self._client = anthropic.Anthropic()
        return self._client

    async def handle(self, request: AgentRequest) -> AgentResponse:
        """Main entry point. All agents call this — not ``process()`` directly.

        Enforces: PII check -> audit log -> process -> audit log -> return.
        """
        # Step 1: PII gate — refuse if Zone 1 data detected in request.
        pii_result = self.pii_detector.scan(request.model_dump())
        if pii_result.detected:
            await self._log_pii_violation(request, pii_result)
            return AgentResponse(
                request_id=request.request_id,
                agent_id=self.agent_id,
                error="PII_BOUNDARY_VIOLATION",
                detail=pii_result.summary,  # summary only — never PII content
                hitl_tier=HITLTier.MANDATORY,
                requires_human_decision=True,
            )

        # Step 2: Audit log — before processing. A failure here raises and the
        # agent halts; it never proceeds with an unlogged action (Constraint #3).
        await self.audit_log.append(
            AuditEntry(
                event_type="REQUEST_RECEIVED",
                agent_id=self.agent_id,
                request_id=request.request_id,
                jurisdiction=request.jurisdiction_code.value,
            )
        )

        # Step 3: Process.
        try:
            response = await self.process(request)
        except Exception as exc:
            await self._log_error(request, exc)
            raise

        # Step 4: Audit log — after processing.
        await self.audit_log.append(
            AuditEntry(
                event_type="RESPONSE_GENERATED",
                agent_id=self.agent_id,
                request_id=request.request_id,
                jurisdiction=request.jurisdiction_code.value,
                hitl_required=response.hitl_tier != HITLTier.NONE,
            )
        )

        # Step 5: HITL notification if mandatory.
        if response.hitl_tier == HITLTier.MANDATORY:
            await self._notify_hitl(request, response)

        return response

    @abstractmethod
    async def process(self, request: AgentRequest) -> AgentResponse:
        """Subclass implements domain logic here."""
        ...

    def _build_system_prompt(self, runtime_vars: dict) -> str:
        """Subclass provides base prompt; this injects runtime vars."""
        base = self.SYSTEM_PROMPT_TEMPLATE
        for key, value in runtime_vars.items():
            base = base.replace(f"{{{key}}}", str(value))
        # Always append data-handling constraints — cannot be overridden.
        base += "\n\n" + DATA_HANDLING_CONSTRAINTS
        return base

    async def _call_llm(self, system: str, messages: list) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=messages,
        )
        return response.content[0].text

    async def _log_pii_violation(
        self, request: AgentRequest, pii_result: Any
    ) -> None:
        await self.audit_log.append(
            AuditEntry(
                event_type="PII_BOUNDARY_VIOLATION",
                agent_id=self.agent_id,
                request_id=request.request_id,
                jurisdiction=request.jurisdiction_code.value,
                pii_present=True,
                detail=pii_result.summary,  # value-free summary only
                # Never log pii_result content — only the violation event.
            )
        )

    async def _log_error(self, request: AgentRequest, exc: Exception) -> None:
        await self.audit_log.append(
            AuditEntry(
                event_type="PROCESSING_ERROR",
                agent_id=self.agent_id,
                request_id=request.request_id,
                jurisdiction=request.jurisdiction_code.value,
                detail=type(exc).__name__,  # type only — no message/PII
            )
        )

    async def _notify_hitl(
        self, request: AgentRequest, response: AgentResponse
    ) -> None:
        from adapters.base.notification import Notification, NotificationChannel

        await self.notification.send(
            Notification(
                channel=NotificationChannel.SLACK,
                recipient=request.hitl_approver or "",
                subject=f"HITL Required — {self.agent_id} — {request.request_id}",
                body=(
                    f"Action required. Request ID: {request.request_id}. "
                    f"Basis: {response.hitl_basis}. "
                    f"Full output: {response.full_output_ref}"
                ),
                priority="critical",
                request_id=request.request_id,
            )
        )


# Appended to every agent system prompt — cannot be overridden.
DATA_HANDLING_CONSTRAINTS = """
DATA HANDLING CONSTRAINTS — NON-NEGOTIABLE

ZONE 1 — PROHIBITED: You must never request, store, process, or output
any personally identifiable information including: employee names,
national IDs (マイナンバー / SSN / NRIC), salary figures linked to
individuals, health or disability data, immigration status, or any
other Zone 1 data. If Zone 1 data appears in any input, you must:
  1. Refuse to process the payload
  2. Return error: {"error": "PII_BOUNDARY_VIOLATION"}
  3. Do NOT log the PII content — log only the violation event

ZONE 2 — CONTROLLED: You may read anonymized organizational context.
You may not write to Zone 2 without an explicit zone2_write_token.

ZONE 3 — PERMITTED: You may read and learn from public knowledge
including regulatory content, published benchmarks, and HR frameworks.

PII BOUNDARY VIOLATION = IMMEDIATE HALT. No exceptions.
"""
