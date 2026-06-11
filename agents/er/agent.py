"""Employee Relations (ER) Agent — Module B (deterministic) + Module A (LLM).

Order is non-negotiable (Constraint #4):

  1. Module B (``ERComplianceModule``) runs first — pure, deterministic rule
     checks. Its result is written to the audit log *before* Module A runs.
  2. ``HARD_STOP`` from Module B bypasses Module A entirely and returns a
     MANDATORY HITL response (no LLM inference happens).
  3. ``CLEAR`` allows Module A — the LLM reasoning layer — to run.

The graph (Phase 3) reinforces this ordering structurally; the agent enforces
it here so the guarantee holds even when an agent is invoked directly.
"""

from __future__ import annotations

from adapters.base.audit_log import AuditEntry
from adapters.base.storage import DataZone
from agents.base.agent import BaseAgent
from agents.er.compliance_module import ComplianceResult, ERComplianceModule
from schemas.common import AgentRequest, AgentResponse, Confidence, HITLTier
from schemas.er import ERCasePayload

ER_SYSTEM_PROMPT = """\
You are the Employee Relations (ER) Agent for a global HR team. You advise on
ER matters that have already cleared a deterministic compliance gate. Provide
measured, procedurally-sound guidance grounded in the relevant jurisdiction.

You never make termination, disciplinary, or settlement decisions — you outline
options, process steps, and risks for a human to decide. Default jurisdiction:
{jurisdiction}. Output language: {language}.
"""


class ERAgent(BaseAgent):
    agent_id = "ER_AGENT"
    SYSTEM_PROMPT_TEMPLATE = ER_SYSTEM_PROMPT

    def __init__(self, *, compliance: ERComplianceModule | None = None, **kwargs):
        super().__init__(**kwargs)
        self.compliance = compliance or ERComplianceModule()

    def parse_payload(self, request: AgentRequest) -> ERCasePayload:
        data = dict(request.payload or {})
        data.setdefault("jurisdiction_code", request.jurisdiction_code)
        if "case_summary" not in data:
            data["case_summary"] = data.get("facts") or data.get("intent") or ""
        return ERCasePayload(**data)

    async def run_module_b(
        self, request: AgentRequest, payload: ERCasePayload
    ) -> ComplianceResult:
        """Module B — deterministic compliance gate, audited before Module A.

        Exposed as a standalone step so the orchestration graph can model it as
        a synchronous pre-node that must return CLEAR before Module A runs
        (Constraint #4).
        """
        result = self.compliance.check(
            facts=payload.case_summary,
            jurisdiction=payload.jurisdiction_code.value,
            employee_count=payload.employee_count,
            works_council_present=payload.works_council_present,
            union_present=payload.union_present,
        )
        # Audit the compliance verdict BEFORE Module A can run (Constraint #4).
        await self.audit_log.append(
            AuditEntry(
                event_type="ER_COMPLIANCE_CHECK",
                agent_id=self.agent_id,
                request_id=request.request_id,
                jurisdiction=payload.jurisdiction_code.value,
                detail=f"{result.result}: {','.join(result.triggered_rules)}",
            )
        )
        return result

    async def process(self, request: AgentRequest) -> AgentResponse:
        payload = self.parse_payload(request)

        # --- Module B — deterministic, runs FIRST -----------------------
        result = await self.run_module_b(request, payload)

        if result.result == "HARD_STOP":
            return self.hard_stop_response(request, result)

        # --- Module A — LLM reasoning (only on CLEAR) -------------------
        return await self.run_module_a(request, payload)

    def hard_stop_response(
        self, request: AgentRequest, result: ComplianceResult
    ) -> AgentResponse:
        flags = list(result.triggered_rules)
        if result.legal_agent_required:
            flags.append("LEGAL_AGENT_REQUIRED")
        return AgentResponse(
            request_id=request.request_id,
            agent_id=self.agent_id,
            confidence=Confidence.HIGH,
            hitl_tier=HITLTier.MANDATORY,
            hitl_basis="; ".join(result.rule_descriptions) or "ER hard stop",
            requires_human_decision=True,
            jurisdiction_flags=flags,
        )

    async def run_module_a(
        self, request: AgentRequest, payload: ERCasePayload
    ) -> AgentResponse:
        system = self._build_system_prompt(
            {
                "jurisdiction": payload.jurisdiction_code.value,
                "language": request.output_language.value,
            }
        )
        output = await self._call_llm(
            system=system,
            messages=[{"role": "user", "content": payload.case_summary}],
        )

        ref = f"er/{request.request_id}.txt"
        await self.storage.put(ref, output.encode("utf-8"), DataZone.ZONE2)

        return AgentResponse(
            request_id=request.request_id,
            agent_id=self.agent_id,
            confidence=Confidence.HIGH,
            hitl_tier=HITLTier.RECOMMENDED,  # ER guidance is logged for review
            hitl_basis="ER advisory output — recommend human review",
            full_output_ref=ref,
        )
