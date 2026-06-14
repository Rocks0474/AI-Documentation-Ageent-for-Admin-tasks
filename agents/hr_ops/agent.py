"""HR Operations Agent — lifecycle workflows and statutory obligations.

For each lifecycle event the agent first derives the *deterministic* statutory
obligations that apply (auditable, jurisdiction-specific — this is what a
Japanese HR team must be able to trust), then asks the LLM for a practical
execution checklist. The deterministic obligations are never invented by the
model.
"""

from __future__ import annotations

from adapters.base.audit_log import AuditEntry
from adapters.base.storage import DataZone
from agents.base.agent import BaseAgent
from schemas.common import AgentRequest, AgentResponse, Confidence, HITLTier, Jurisdiction
from schemas.hr_ops import LifecycleEvent, LifecycleEventPayload

# Deterministic statutory obligations by (jurisdiction, lifecycle event).
# Japan is covered in depth; other jurisdictions fall back to LLM guidance only.
STATUTORY_OBLIGATIONS: dict[tuple[Jurisdiction, LifecycleEvent], list[str]] = {
    (Jurisdiction.JP, LifecycleEvent.ONBOARDING): [
        "健康保険・厚生年金保険資格取得届",
        "雇用保険被保険者資格取得届",
        "労働条件通知書の交付",
    ],
    (Jurisdiction.JP, LifecycleEvent.OFFBOARDING): [
        "健康保険・厚生年金保険資格喪失届",
        "雇用保険被保険者資格喪失届",
        "離職票の発行",
        "源泉徴収票の発行",
    ],
    (Jurisdiction.JP, LifecycleEvent.LEAVE): [
        "育児休業給付金の申請",
        "社会保険料免除の申請",
    ],
    (Jurisdiction.JP, LifecycleEvent.TRANSFER): [
        "住所変更届",
        "通勤手当の再計算",
    ],
}

HR_OPS_SYSTEM_PROMPT = """\
You are the HR Operations Agent for a global HR team. Given a lifecycle event
and the statutory obligations that have already been determined, produce a
clear, ordered execution checklist for the HR operations team. Do not invent
statutory requirements — work from the obligations provided. Default
jurisdiction: {jurisdiction}. Output language: {language}.
"""


def statutory_obligations(
    event: LifecycleEvent, jurisdiction: Jurisdiction
) -> list[str]:
    """Return the deterministic statutory obligations for an event."""
    return list(STATUTORY_OBLIGATIONS.get((jurisdiction, event), []))


class HROpsAgent(BaseAgent):
    agent_id = "HR_OPS_AGENT"
    SYSTEM_PROMPT_TEMPLATE = HR_OPS_SYSTEM_PROMPT

    def _parse_payload(self, request: AgentRequest) -> LifecycleEventPayload:
        data = dict(request.payload or {})
        data.setdefault("jurisdiction_code", request.jurisdiction_code)
        return LifecycleEventPayload(**data)

    async def process(self, request: AgentRequest) -> AgentResponse:
        payload = self._parse_payload(request)
        obligations = statutory_obligations(
            payload.event_type, payload.jurisdiction_code
        )

        await self.audit_log.append(
            AuditEntry(
                event_type="HR_OPS_OBLIGATIONS_DERIVED",
                agent_id=self.agent_id,
                request_id=request.request_id,
                jurisdiction=payload.jurisdiction_code.value,
                detail=f"{payload.event_type.value}: {len(obligations)} obligation(s)",
            )
        )

        system = self._build_system_prompt(
            {
                "jurisdiction": payload.jurisdiction_code.value,
                "language": request.output_language.value,
            }
        )
        user = (
            f"Lifecycle event: {payload.event_type.value}\n"
            f"Effective date: {payload.effective_date.isoformat()}\n"
            f"Statutory obligations: {obligations or '[none codified]'}"
        )
        checklist = await self._call_llm(
            system=system, messages=[{"role": "user", "content": user}]
        )

        ref = f"hr_ops/{request.request_id}.txt"
        await self.storage.put(ref, checklist.encode("utf-8"), DataZone.ZONE2)

        return AgentResponse(
            request_id=request.request_id,
            agent_id=self.agent_id,
            confidence=Confidence.HIGH,
            hitl_tier=HITLTier.RECOMMENDED,
            hitl_basis="HR operations checklist — recommend human review",
            full_output_ref=ref,
            jurisdiction_flags=[f"OBLIGATION:{o}" for o in obligations],
        )
