"""HR Business Partner (HRBP) Agent.

The generalist partner. It consumes anonymized Analytics signals (by reference)
and organizational context to produce people-strategy recommendations. It
operates only on cohort references — never individuals.
"""

from __future__ import annotations

from adapters.base.audit_log import AuditEntry
from adapters.base.storage import DataZone
from agents.base.agent import BaseAgent
from schemas.common import AgentRequest, AgentResponse, Confidence, HITLTier
from schemas.hrbp import HRBPConsultPayload

HRBP_SYSTEM_PROMPT = """\
You are the HR Business Partner (HRBP) Agent for a global HR team. Using the
topic and any anonymized analytics signals provided (by reference only),
recommend concrete people-strategy actions a manager or CHRO can take. Work at
the cohort level — never reference or infer individual employees. Default
jurisdiction: {jurisdiction}. Output language: {language}.
"""


class HRBPAgent(BaseAgent):
    agent_id = "HRBP_AGENT"
    SYSTEM_PROMPT_TEMPLATE = HRBP_SYSTEM_PROMPT

    def _parse_payload(self, request: AgentRequest) -> HRBPConsultPayload:
        data = dict(request.payload or {})
        data.setdefault("jurisdiction_code", request.jurisdiction_code)
        return HRBPConsultPayload(**data)

    async def process(self, request: AgentRequest) -> AgentResponse:
        payload = self._parse_payload(request)

        system = self._build_system_prompt(
            {
                "jurisdiction": payload.jurisdiction_code.value,
                "language": request.output_language.value,
            }
        )
        user = (
            f"Topic: {payload.topic}\n"
            f"Cohort: {payload.cohort_ref or '[unspecified]'}\n"
            f"Analytics signals (refs): {payload.signal_refs or '[none]'}"
        )
        recommendation = await self._call_llm(
            system=system, messages=[{"role": "user", "content": user}]
        )

        ref = f"hrbp/{request.request_id}.txt"
        await self.storage.put(ref, recommendation.encode("utf-8"), DataZone.ZONE2)

        await self.audit_log.append(
            AuditEntry(
                event_type="HRBP_RECOMMENDATION",
                agent_id=self.agent_id,
                request_id=request.request_id,
                jurisdiction=payload.jurisdiction_code.value,
                detail=f"topic={payload.topic}",
            )
        )

        return AgentResponse(
            request_id=request.request_id,
            agent_id=self.agent_id,
            confidence=Confidence.HIGH,
            hitl_tier=HITLTier.RECOMMENDED,
            hitl_basis="HRBP recommendation — recommend human review",
            full_output_ref=ref,
        )
