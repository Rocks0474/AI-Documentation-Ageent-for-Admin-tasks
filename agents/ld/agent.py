"""Learning & Development (L&D) Agent — skill-targeted learning paths.

Builds a learning path deterministically from the LMS catalog (stub) for a
given skill target, so recommendations are reproducible and auditable. No PII:
the agent works with skills and role families, not individuals.
"""

from __future__ import annotations

import json

from adapters.base.audit_log import AuditEntry
from adapters.base.storage import DataZone
from agents.base.agent import BaseAgent
from integrations.lms import LMSStub
from schemas.common import AgentRequest, AgentResponse, Confidence, HITLTier
from schemas.ld import LearningPathRequest, LearningPathResult


class LDAgent(BaseAgent):
    agent_id = "LD_AGENT"

    def __init__(self, *, lms: LMSStub | None = None, **kwargs):
        super().__init__(**kwargs)
        self.lms = lms or LMSStub()

    def _parse_payload(self, request: AgentRequest) -> LearningPathRequest:
        data = dict(request.payload or {})
        data.setdefault("jurisdiction_code", request.jurisdiction_code)
        return LearningPathRequest(**data)

    async def process(self, request: AgentRequest) -> AgentResponse:
        payload = self._parse_payload(request)
        modules = self.lms.fetch_modules(payload.skill_target)

        result = LearningPathResult(
            skill_target=payload.skill_target,
            modules=[f"{m.code} {m.title}" for m in modules],
            estimated_hours=sum(m.hours for m in modules),
        )

        ref = f"ld/{request.request_id}.json"
        await self.storage.put(
            ref,
            json.dumps(result.model_dump(), ensure_ascii=False).encode("utf-8"),
            DataZone.ZONE2,
        )
        await self.audit_log.append(
            AuditEntry(
                event_type="LD_LEARNING_PATH",
                agent_id=self.agent_id,
                request_id=request.request_id,
                jurisdiction=payload.jurisdiction_code.value,
                detail=(
                    f"skill={payload.skill_target} "
                    f"modules={len(result.modules)} hours={result.estimated_hours}"
                ),
            )
        )

        return AgentResponse(
            request_id=request.request_id,
            agent_id=self.agent_id,
            confidence=Confidence.HIGH,
            hitl_tier=HITLTier.RECOMMENDED,
            hitl_basis="Learning path — recommend manager review",
            full_output_ref=ref,
        )
