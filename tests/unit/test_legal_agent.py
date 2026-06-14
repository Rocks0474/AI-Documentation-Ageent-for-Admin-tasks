"""Unit tests for the HR Legal Agent: routing, confidence, watermark."""

from __future__ import annotations

import json

from adapters.base.storage import DataZone
from adapters.local.audit_log import LocalAuditLogAdapter
from adapters.local.notification import LocalNotificationAdapter
from adapters.local.storage import LocalStorageAdapter
from adapters.local.vector_db import LocalVectorDBAdapter
from agents.legal.agent import LegalAgent
from agents.legal.jurisdiction_router import route
from schemas.common import AgentRequest, Confidence, HITLTier, Jurisdiction
from schemas.legal import LEGAL_WATERMARK

# ---------------------------------------------------------------------------
# Jurisdiction router
# ---------------------------------------------------------------------------

def test_router_supported_single_jurisdiction():
    ctx = route(Jurisdiction.JP, "what notice is required for resignation?")
    assert ctx.supported is True
    assert ctx.multi is False
    assert "Japanese" in ctx.framework


def test_router_multi_jurisdiction_enum_not_supported():
    ctx = route(Jurisdiction.MULTI, "cross-border question")
    assert ctx.supported is False
    assert ctx.multi is True


def test_router_detects_multi_from_question_text():
    ctx = route(Jurisdiction.JP, "compare rules in Japan vs California")
    assert ctx.multi is True
    assert ctx.supported is False


# ---------------------------------------------------------------------------
# Legal Agent
# ---------------------------------------------------------------------------

def _agent(tmp_path):
    audit = LocalAuditLogAdapter()
    storage = LocalStorageAdapter(root=str(tmp_path))
    notifier = LocalNotificationAdapter()
    agent = LegalAgent(
        audit_log=audit,
        storage=storage,
        notification=notifier,
        vector_db=LocalVectorDBAdapter(),
    )
    return agent, audit, storage, notifier


def _request(question: str, jurisdiction=Jurisdiction.JP) -> AgentRequest:
    return AgentRequest(
        source="SUB_AGENT",
        jurisdiction_code=jurisdiction,
        requesting_user_role="SYSTEM",
        hitl_approver="#legal-hitl",
        payload={"question": question},
    )


async def test_supported_high_confidence_opinion_is_watermarked(tmp_path, monkeypatch):
    agent, audit, storage, notifier = _agent(tmp_path)

    async def fake_llm(system, messages):
        return "Analysis of the matter.\nCONFIDENCE: HIGH"

    monkeypatch.setattr(agent, "_call_llm", fake_llm)
    response = await agent.handle(_request("notice period for resignation?"))

    assert response.confidence == Confidence.HIGH
    assert response.hitl_tier == HITLTier.REQUIRED  # not LOW => no CHRO escalation
    assert "WATERMARKED" in response.jurisdiction_flags
    assert response.detail == LEGAL_WATERMARK
    # Opinion metadata persisted with the watermark.
    meta = json.loads(
        await storage.get(f"legal/{response.request_id}.meta.json", DataZone.ZONE2)
    )
    assert meta["watermark"] == LEGAL_WATERMARK
    assert notifier.sent == []  # REQUIRED does not notify


async def test_multi_jurisdiction_forces_low_and_chro_escalation(tmp_path, monkeypatch):
    agent, _, _, notifier = _agent(tmp_path)

    async def fake_llm(system, messages):
        # Even if the model claims HIGH, multi-jurisdiction forces LOW.
        return "Cross-border analysis.\nCONFIDENCE: HIGH"

    monkeypatch.setattr(agent, "_call_llm", fake_llm)
    response = await agent.handle(_request("cross-border", Jurisdiction.MULTI))

    assert response.confidence == Confidence.LOW
    assert response.hitl_tier == HITLTier.MANDATORY
    assert response.requires_human_decision is True
    assert "MULTI_JURISDICTION" in response.jurisdiction_flags
    assert len(notifier.sent) == 1  # CHRO escalation fired


async def test_llm_low_hint_triggers_escalation_even_when_supported(tmp_path, monkeypatch):
    agent, _, _, notifier = _agent(tmp_path)

    async def fake_llm(system, messages):
        return "Unsettled area.\nCONFIDENCE: LOW"

    monkeypatch.setattr(agent, "_call_llm", fake_llm)
    response = await agent.handle(_request("an unsettled JP question"))

    assert response.confidence == Confidence.LOW
    assert response.hitl_tier == HITLTier.MANDATORY
    assert len(notifier.sent) == 1


async def test_missing_confidence_hint_defaults_to_medium(tmp_path, monkeypatch):
    agent, _, _, _ = _agent(tmp_path)

    async def fake_llm(system, messages):
        return "Analysis with no confidence marker."

    monkeypatch.setattr(agent, "_call_llm", fake_llm)
    response = await agent.handle(_request("a supported JP question"))
    assert response.confidence == Confidence.MEDIUM
