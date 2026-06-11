"""Unit tests for the People Analytics Agent — privacy floor is the focus."""

from __future__ import annotations

import json

from adapters.base.storage import DataZone
from adapters.local.audit_log import LocalAuditLogAdapter
from adapters.local.notification import LocalNotificationAdapter
from adapters.local.storage import LocalStorageAdapter
from adapters.local.vector_db import LocalVectorDBAdapter
from agents.analytics.agent import PeopleAnalyticsAgent
from integrations.panalyt import CohortMetric, PanalytStub
from schemas.common import AgentRequest, HITLTier, Jurisdiction


class _ExplodingPanalyt(PanalytStub):
    """Must never be called when a cohort is suppressed."""

    def fetch_cohort_metric(self, metric: str, cohort_ref: str) -> CohortMetric:
        raise AssertionError("Panalyt must not be queried for a suppressed cohort")


def _agent(tmp_path, *, panalyt=None, minimum=10):
    audit = LocalAuditLogAdapter()
    storage = LocalStorageAdapter(root=str(tmp_path))
    agent = PeopleAnalyticsAgent(
        minimum_cohort_size=minimum,
        panalyt=panalyt or PanalytStub(),
        audit_log=audit,
        storage=storage,
        notification=LocalNotificationAdapter(),
        vector_db=LocalVectorDBAdapter(),
    )
    return agent, audit, storage


def _request(metric: str, cohort_ref: str, cohort_size: int) -> AgentRequest:
    return AgentRequest(
        source="HUMAN_HR",
        jurisdiction_code=Jurisdiction.JP,
        requesting_user_role="HRBP",
        payload={
            "metric": metric,
            "cohort_ref": cohort_ref,
            "cohort_size": cohort_size,
        },
    )


async def test_small_cohort_is_suppressed_without_data_fetch(tmp_path):
    agent, audit, storage = _agent(tmp_path, panalyt=_ExplodingPanalyt())
    response = await agent.handle(_request("attrition_rate", "cohort_eng_jp", 4))

    assert "COHORT_SUPPRESSED" in response.jurisdiction_flags
    result = json.loads(await storage.get(response.full_output_ref, DataZone.ZONE2))
    assert result["suppressed"] is True
    assert result["value"] is None

    events = [e.event_type for e in await audit.query(response.request_id)]
    assert "ANALYTICS_SUPPRESSED" in events


async def test_large_cohort_returns_value(tmp_path):
    agent, _, storage = _agent(tmp_path)
    response = await agent.handle(_request("attrition_rate", "cohort_eng_jp", 50))

    assert response.hitl_tier == HITLTier.NONE
    assert response.jurisdiction_flags == []
    result = json.loads(await storage.get(response.full_output_ref, DataZone.ZONE2))
    assert result["suppressed"] is False
    assert isinstance(result["value"], (int, float))


async def test_floor_is_configurable(tmp_path):
    # With a minimum of 5, a cohort of 6 is allowed through.
    agent, _, storage = _agent(tmp_path, minimum=5)
    response = await agent.handle(_request("enps", "cohort_sales_sg", 6))
    result = json.loads(await storage.get(response.full_output_ref, DataZone.ZONE2))
    assert result["suppressed"] is False
