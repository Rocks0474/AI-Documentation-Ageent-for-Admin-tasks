"""Unit tests for the Director Agent: classifier, queue, routing, audit."""

from __future__ import annotations

import pytest

from adapters.local.audit_log import LocalAuditLogAdapter
from adapters.local.notification import LocalNotificationAdapter
from adapters.local.storage import LocalStorageAdapter
from adapters.local.vector_db import LocalVectorDBAdapter
from agents.director.agent import DirectorAgent
from agents.director.router import (
    DomainClassifier,
    RoutingQueue,
    build_routing_decision,
    derive_priority,
)
from schemas.common import AgentRequest, Confidence, Jurisdiction, Priority
from schemas.director import Domain, RoutingDecision

# ---------------------------------------------------------------------------
# Deterministic classifier
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("manager wants to proceed with termination of employee", Domain.ER),
        ("need a legal opinion on jurisdiction", Domain.LEGAL),
        ("review the pay band and offer range", Domain.CB),
        ("set up training and upskilling course", Domain.LD),
        ("onboarding and offboarding lifecycle tasks", Domain.HR_OPS),
        ("candidate pipeline and interview scheduling", Domain.TA),
        ("attrition turnover dashboard metrics", Domain.ANALYTICS),
        ("team engagement and retention strategy", Domain.HRBP),
    ],
)
def test_classifier_routes_known_intents(text, expected):
    result = DomainClassifier().classify(text)
    assert result.domain == expected
    assert result.confidence in (Confidence.HIGH, Confidence.MEDIUM)


def test_classifier_no_match_is_low_confidence():
    result = DomainClassifier().classify("zzz qqq unrelated gibberish")
    assert result.domain is None
    assert result.confidence == Confidence.LOW


def test_classifier_tiebreak_prefers_safety_first():
    # Contains both an ER and a CB keyword; ER must win the tie (safety first).
    result = DomainClassifier().classify("termination and compensation question")
    assert result.domain == Domain.ER


# ---------------------------------------------------------------------------
# Priority derivation
# ---------------------------------------------------------------------------

def test_er_termination_escalates_to_critical():
    assert (
        derive_priority(Domain.ER, Priority.STANDARD, ["termination"])
        == Priority.CRITICAL
    )


def test_domain_floor_applied():
    # LEGAL has a HIGH floor even if the requester asked for STANDARD.
    assert derive_priority(Domain.LEGAL, Priority.STANDARD, []) == Priority.HIGH


def test_requester_priority_respected_when_higher():
    assert derive_priority(Domain.TA, Priority.CRITICAL, []) == Priority.CRITICAL


# ---------------------------------------------------------------------------
# build_routing_decision
# ---------------------------------------------------------------------------

def test_build_decision_sequential_er_legal():
    classification = DomainClassifier().classify("termination of an employee")
    decision = build_routing_decision("rt-1", classification, Priority.STANDARD)
    assert decision.target_domain == Domain.ER
    assert decision.priority == Priority.CRITICAL
    assert decision.requires_sequential is True
    assert decision.sequence == [Domain.ER, Domain.LEGAL]


def test_build_decision_no_match_defaults_to_hrbp():
    classification = DomainClassifier().classify("zzz unrelated")
    decision = build_routing_decision("rt-2", classification, Priority.STANDARD)
    assert decision.target_domain == Domain.HRBP
    assert decision.requires_sequential is False


# ---------------------------------------------------------------------------
# RoutingQueue
# ---------------------------------------------------------------------------

def _decision(domain: Domain, priority: Priority, rid: str) -> RoutingDecision:
    return RoutingDecision(routing_id=rid, target_domain=domain, priority=priority)


def test_routing_queue_orders_by_priority_then_fifo():
    queue = RoutingQueue()
    queue.enqueue(_decision(Domain.TA, Priority.STANDARD, "a"))
    queue.enqueue(_decision(Domain.ER, Priority.CRITICAL, "b"))
    queue.enqueue(_decision(Domain.CB, Priority.STANDARD, "c"))
    queue.enqueue(_decision(Domain.LEGAL, Priority.HIGH, "d"))
    assert len(queue) == 4
    order = [queue.dequeue().routing_id for _ in range(4)]
    assert order == ["b", "d", "a", "c"]  # CRITICAL, HIGH, then FIFO STANDARD
    assert queue.dequeue() is None


# ---------------------------------------------------------------------------
# DirectorAgent end-to-end (deterministic + LLM fallback)
# ---------------------------------------------------------------------------

def _director(tmp_path) -> tuple[DirectorAgent, LocalAuditLogAdapter, LocalStorageAdapter]:
    audit = LocalAuditLogAdapter()
    storage = LocalStorageAdapter(root=str(tmp_path))
    agent = DirectorAgent(
        audit_log=audit,
        storage=storage,
        notification=LocalNotificationAdapter(),
        vector_db=LocalVectorDBAdapter(),
    )
    return agent, audit, storage


def _request(intent: str) -> AgentRequest:
    return AgentRequest(
        source="HUMAN_HR",
        jurisdiction_code=Jurisdiction.JP,
        requesting_user_role="HRBP",
        payload={"intent": intent},
    )


async def test_director_route_deterministic(tmp_path):
    agent, _, _ = _director(tmp_path)
    decision = await agent.route(_request("candidate pipeline interview"))
    assert decision.target_domain == Domain.TA


async def test_director_route_llm_fallback(tmp_path, monkeypatch):
    agent, _, _ = _director(tmp_path)

    async def fake_llm(system, messages):
        return "ANALYTICS"

    monkeypatch.setattr(agent, "_call_llm", fake_llm)
    decision = await agent.route(_request("zzz unknown gibberish"))
    assert decision.target_domain == Domain.ANALYTICS


async def test_director_process_writes_decision_and_audit(tmp_path):
    agent, audit, storage = _director(tmp_path)
    response = await agent.handle(_request("attrition turnover dashboard"))

    assert response.error is None
    assert response.full_output_ref and response.full_output_ref.startswith("routing/")
    assert response.jurisdiction_flags == ["ROUTED:ANALYTICS"]

    events = [e.event_type for e in await audit.query(response.request_id)]
    assert events == ["REQUEST_RECEIVED", "ROUTING_DECISION", "RESPONSE_GENERATED"]
    # The decision JSON was persisted to Zone 2.
    from adapters.base.storage import DataZone

    raw = await storage.get(response.full_output_ref, DataZone.ZONE2)
    assert b"ANALYTICS" in raw
