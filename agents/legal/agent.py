"""HR Legal Agent — jurisdiction-aware opinions with confidence + watermark.

Three guarantees:

  - Jurisdiction routing: each question is routed to its applicable framework;
    multi-jurisdiction matters are not cleanly supported.
  - Confidence scoring: LOW confidence ALWAYS triggers CHRO escalation
    (MANDATORY HITL). Unsupported / multi-jurisdiction matters are forced to LOW.
  - Watermark: every opinion carries ``LEGAL_WATERMARK`` and cannot be emitted
    without it. The graph (Phase 3) is forbidden from stripping it; the agent
    guarantees it is always present at the source.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from adapters.base.audit_log import AuditEntry
from adapters.base.storage import DataZone
from agents.base.agent import BaseAgent
from agents.legal.jurisdiction_router import JurisdictionContext, route
from schemas.common import AgentRequest, AgentResponse, Confidence, HITLTier
from schemas.legal import LEGAL_WATERMARK, LegalOpinion, LegalQueryPayload

LEGAL_SYSTEM_PROMPT = """\
You are the HR Legal Agent for a global HR team. You provide informational legal
analysis — never definitive legal advice — grounded in the applicable framework:
{framework}.

Be precise about what the law requires versus what is discretionary. If the
matter is unsettled or spans jurisdictions, say so plainly. End your response
with a line exactly of the form: "CONFIDENCE: HIGH" or "CONFIDENCE: MEDIUM" or
"CONFIDENCE: LOW". Default jurisdiction: {jurisdiction}. Output language:
{language}.
"""

_CONFIDENCE_RE = re.compile(r"CONFIDENCE:\s*(HIGH|MEDIUM|LOW)", re.IGNORECASE)


class LegalAgent(BaseAgent):
    agent_id = "LEGAL_AGENT"
    SYSTEM_PROMPT_TEMPLATE = LEGAL_SYSTEM_PROMPT

    def _parse_payload(self, request: AgentRequest) -> LegalQueryPayload:
        data = dict(request.payload or {})
        data.setdefault("jurisdiction_code", request.jurisdiction_code)
        if "question" not in data:
            data["question"] = data.get("intent", "")
        return LegalQueryPayload(**data)

    @staticmethod
    def _parse_confidence_hint(raw: str) -> Optional[Confidence]:
        match = _CONFIDENCE_RE.search(raw)
        if not match:
            return None
        return Confidence[match.group(1).upper()]

    @staticmethod
    def _derive_confidence(
        ctx: JurisdictionContext, hint: Optional[Confidence]
    ) -> Confidence:
        # Unsupported / multi-jurisdiction matters can never be HIGH/MEDIUM.
        if not ctx.supported or ctx.multi:
            return Confidence.LOW
        return hint or Confidence.MEDIUM

    async def process(self, request: AgentRequest) -> AgentResponse:
        payload = self._parse_payload(request)
        ctx = route(payload.jurisdiction_code, payload.question)

        system = self._build_system_prompt(
            {
                "framework": ctx.framework,
                "jurisdiction": payload.jurisdiction_code.value,
                "language": request.output_language.value,
            }
        )
        raw = await self._call_llm(
            system=system,
            messages=[{"role": "user", "content": payload.question}],
        )
        confidence = self._derive_confidence(ctx, self._parse_confidence_hint(raw))

        # Persist the opinion. The watermark is set here and is non-removable.
        opinion = LegalOpinion(
            summary_ref=f"legal/{request.request_id}.txt",
            jurisdiction_code=payload.jurisdiction_code,
            confidence=confidence,
            watermark=LEGAL_WATERMARK,
            citations=[ctx.framework],
        )
        await self.storage.put(
            opinion.summary_ref, raw.encode("utf-8"), DataZone.ZONE2
        )
        await self.storage.put(
            f"legal/{request.request_id}.meta.json",
            json.dumps(opinion.model_dump(), ensure_ascii=False).encode("utf-8"),
            DataZone.ZONE2,
        )

        await self.audit_log.append(
            AuditEntry(
                event_type="LEGAL_OPINION",
                agent_id=self.agent_id,
                request_id=request.request_id,
                jurisdiction=payload.jurisdiction_code.value,
                detail=(
                    f"confidence={confidence.value} supported={ctx.supported} "
                    f"multi={ctx.multi}"
                ),
            )
        )

        # LOW confidence => CHRO escalation (MANDATORY); otherwise REQUIRED.
        if confidence == Confidence.LOW:
            hitl_tier = HITLTier.MANDATORY
            hitl_basis = "LOW confidence legal opinion — CHRO escalation required"
        else:
            hitl_tier = HITLTier.REQUIRED
            hitl_basis = "Legal opinion — human legal review required"

        flags = ["WATERMARKED", f"FRAMEWORK:{payload.jurisdiction_code.value}"]
        if ctx.multi:
            flags.append("MULTI_JURISDICTION")

        return AgentResponse(
            request_id=request.request_id,
            agent_id=self.agent_id,
            confidence=confidence,
            hitl_tier=hitl_tier,
            hitl_basis=hitl_basis,
            requires_human_decision=confidence == Confidence.LOW,
            full_output_ref=opinion.summary_ref,
            detail=LEGAL_WATERMARK,  # watermark surfaced on every response
            jurisdiction_flags=flags,
        )
