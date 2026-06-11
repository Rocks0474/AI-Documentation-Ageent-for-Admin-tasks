"""Talent Acquisition (TA) Agent — pipeline aggregates and scheduling.

Reads pipeline data from Greenhouse (stub) and interview slots from GoodTime
(stub). Works only with anonymized aggregates — stage counts and interviewer
refs — never candidate names or contact details (Zone 1). Degrades gracefully:
if an integration is not connected, the agent still returns a (possibly empty)
result with a flag rather than failing.
"""

from __future__ import annotations

import json
from typing import Optional

from adapters.base.audit_log import AuditEntry
from adapters.base.storage import DataZone
from agents.base.agent import BaseAgent
from integrations.goodtime import GoodTimeStub
from integrations.greenhouse import GreenhouseStub
from schemas.common import AgentRequest, AgentResponse, Confidence, HITLTier
from schemas.ta import CandidateStageSummary, PipelinePayload


class TAAgent(BaseAgent):
    agent_id = "TA_AGENT"

    def __init__(
        self,
        *,
        greenhouse: Optional[GreenhouseStub] = None,
        goodtime: Optional[GoodTimeStub] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.greenhouse = greenhouse or GreenhouseStub()
        self.goodtime = goodtime or GoodTimeStub()

    def _parse_payload(self, request: AgentRequest) -> PipelinePayload:
        data = dict(request.payload or {})
        data.setdefault("jurisdiction_code", request.jurisdiction_code)
        return PipelinePayload(**data)

    async def process(self, request: AgentRequest) -> AgentResponse:
        payload = self._parse_payload(request)
        flags: list[str] = []

        snapshot = self.greenhouse.fetch_pipeline(payload.requisition_ref)
        if not self.greenhouse.connected:
            flags.append("GREENHOUSE_STUB")
        summary = CandidateStageSummary(
            requisition_ref=payload.requisition_ref,
            stage_counts=snapshot.stage_counts,
            total_candidates=snapshot.total,
        )

        slots = self.goodtime.fetch_slots(payload.requisition_ref)
        if not self.goodtime.connected:
            flags.append("GOODTIME_STUB")
        flags.append(f"SLOTS_AVAILABLE:{len(slots)}")

        ref = f"ta/{request.request_id}.json"
        await self.storage.put(
            ref,
            json.dumps(summary.model_dump(), ensure_ascii=False).encode("utf-8"),
            DataZone.ZONE2,
        )
        await self.audit_log.append(
            AuditEntry(
                event_type="TA_PIPELINE_SUMMARY",
                agent_id=self.agent_id,
                request_id=request.request_id,
                jurisdiction=payload.jurisdiction_code.value,
                detail=(
                    f"req={payload.requisition_ref} "
                    f"total={summary.total_candidates}"
                ),
            )
        )

        return AgentResponse(
            request_id=request.request_id,
            agent_id=self.agent_id,
            confidence=Confidence.HIGH,
            hitl_tier=HITLTier.NONE,
            full_output_ref=ref,
            jurisdiction_flags=flags,
        )
