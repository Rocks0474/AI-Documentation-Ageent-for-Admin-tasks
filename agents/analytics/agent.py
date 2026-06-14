"""People Analytics Agent — cohort metrics with a deterministic privacy floor.

The privacy floor is the core guarantee: any cohort smaller than
``minimum_cohort_size`` is suppressed *before* any data is fetched or returned,
so individuals cannot be re-identified from small-cohort aggregates. This is a
deterministic, non-LLM decision (re-identification risk is not something to
delegate to a model). Cohort values come from the Panalyt integration (stubbed).
"""

from __future__ import annotations

import json
from typing import Optional

from adapters.base.audit_log import AuditEntry
from adapters.base.storage import DataZone
from agents.base.agent import BaseAgent
from integrations.panalyt import PanalytStub
from schemas.analytics import CohortAnalyticsRequest, CohortAnalyticsResult
from schemas.common import AgentRequest, AgentResponse, Confidence, HITLTier


class PeopleAnalyticsAgent(BaseAgent):
    agent_id = "ANALYTICS_AGENT"

    def __init__(
        self,
        *,
        minimum_cohort_size: int = 10,
        panalyt: Optional[PanalytStub] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.minimum_cohort_size = minimum_cohort_size
        self.panalyt = panalyt or PanalytStub()

    def _parse_payload(self, request: AgentRequest) -> CohortAnalyticsRequest:
        data = dict(request.payload or {})
        data.setdefault("jurisdiction_code", request.jurisdiction_code)
        return CohortAnalyticsRequest(**data)

    async def process(self, request: AgentRequest) -> AgentResponse:
        payload = self._parse_payload(request)

        # --- Privacy floor — deterministic, BEFORE any data fetch ------
        if payload.cohort_size < self.minimum_cohort_size:
            result = CohortAnalyticsResult(
                metric=payload.metric,
                cohort_ref=payload.cohort_ref,
                cohort_size=payload.cohort_size,
                value=None,
                suppressed=True,
                minimum_cohort_size=self.minimum_cohort_size,
            )
            await self.audit_log.append(
                AuditEntry(
                    event_type="ANALYTICS_SUPPRESSED",
                    agent_id=self.agent_id,
                    request_id=request.request_id,
                    jurisdiction=payload.jurisdiction_code.value,
                    detail=(
                        f"cohort_size={payload.cohort_size} < "
                        f"min={self.minimum_cohort_size}"
                    ),
                )
            )
            return await self._respond(request, result, suppressed=True)

        # --- Above the floor — fetch the aggregate metric --------------
        metric = self.panalyt.fetch_cohort_metric(payload.metric, payload.cohort_ref)
        result = CohortAnalyticsResult(
            metric=payload.metric,
            cohort_ref=payload.cohort_ref,
            cohort_size=payload.cohort_size,
            value=metric.value,
            suppressed=False,
            minimum_cohort_size=self.minimum_cohort_size,
        )
        return await self._respond(request, result, suppressed=False)

    async def _respond(
        self,
        request: AgentRequest,
        result: CohortAnalyticsResult,
        *,
        suppressed: bool,
    ) -> AgentResponse:
        ref = f"analytics/{request.request_id}.json"
        await self.storage.put(
            ref,
            json.dumps(result.model_dump(), ensure_ascii=False).encode("utf-8"),
            DataZone.ZONE2,
        )
        return AgentResponse(
            request_id=request.request_id,
            agent_id=self.agent_id,
            confidence=Confidence.HIGH,
            hitl_tier=HITLTier.NONE,
            full_output_ref=ref,
            detail=f"{result.metric} suppressed={suppressed}",
            jurisdiction_flags=["COHORT_SUPPRESSED"] if suppressed else [],
        )
