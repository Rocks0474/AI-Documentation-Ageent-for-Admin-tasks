"""Director Agent — classifies incoming requests and routes them.

The Director is the orchestration entry node. It produces a deterministic
:class:`RoutingDecision` for each request and only consults the LLM when the
keyword classifier is not confident. Routing decisions are persisted (Zone 2)
and referenced from the audit trail, so every routing choice is explainable
after the fact.
"""

from __future__ import annotations

import json
import uuid
from typing import Optional

from adapters.base.audit_log import AuditEntry
from adapters.base.storage import DataZone
from agents.base.agent import BaseAgent
from agents.director.router import (
    Classification,
    DomainClassifier,
    build_routing_decision,
)
from schemas.common import AgentRequest, AgentResponse, Confidence, HITLTier
from schemas.director import Domain, RoutingDecision

DIRECTOR_SYSTEM_PROMPT = """\
You are the Director Agent of a global HR agent team. Your only job is to
classify an incoming HR request into exactly one domain and explain why.

Valid domains:
  ER        — employee relations: termination, harassment, discipline, unions
  LEGAL     — legal/statutory interpretation, jurisdiction questions
  CB        — compensation & benefits, pay bands, offers, pay equity
  LD        — learning & development, training, skills
  HR_OPS    — lifecycle ops: onboarding/offboarding, leave, statutory filings
  TA        — talent acquisition: recruiting, pipelines, interviews
  ANALYTICS — people analytics: attrition, headcount, workforce metrics
  HRBP      — generalist business partnering (use when nothing else fits)

Respond with ONLY the domain code (e.g. "ER"). Do not add commentary.
Default jurisdiction: {jurisdiction}. Output language: {language}.
"""


class DirectorAgent(BaseAgent):
    agent_id = "DIRECTOR_AGENT"
    SYSTEM_PROMPT_TEMPLATE = DIRECTOR_SYSTEM_PROMPT

    def __init__(self, *, classifier: Optional[DomainClassifier] = None, **kwargs):
        super().__init__(**kwargs)
        self.classifier = classifier or DomainClassifier()

    @staticmethod
    def _intent_text(request: AgentRequest) -> str:
        payload = request.payload or {}
        # Concatenate the free-text routing signals (no PII — payload is guarded
        # upstream by the PII gate in BaseAgent.handle()).
        parts = [
            str(payload.get("intent", "")),
            " ".join(str(c) for c in payload.get("context_refs", [])),
        ]
        return " ".join(p for p in parts if p).strip()

    async def route(self, request: AgentRequest) -> RoutingDecision:
        """Produce a routing decision (deterministic, LLM fallback if unsure)."""
        text = self._intent_text(request)
        classification = self.classifier.classify(text)

        if classification.domain is None or classification.confidence == Confidence.LOW:
            domain = await self._classify_with_llm(request, text)
            classification = Classification(
                domain=domain,
                confidence=Confidence.MEDIUM,  # LLM-assisted — not deterministic
                matched_keywords=[],
                scores=classification.scores,
            )

        return build_routing_decision(
            routing_id=request.routing_id or str(uuid.uuid4()),
            classification=classification,
            requested_priority=request.priority,
        )

    async def _classify_with_llm(self, request: AgentRequest, text: str) -> Domain:
        system = self._build_system_prompt(
            {
                "jurisdiction": request.jurisdiction_code.value,
                "language": request.output_language.value,
            }
        )
        raw = await self._call_llm(
            system=system,
            messages=[{"role": "user", "content": text or "(no intent provided)"}],
        )
        return self._parse_domain(raw)

    @staticmethod
    def _parse_domain(raw: str) -> Domain:
        token = raw.strip().upper()
        # Exact match first, then substring scan, then generalist default.
        for domain in Domain:
            if token == domain.value:
                return domain
        for domain in Domain:
            if domain.value in token:
                return domain
        return Domain.HRBP

    async def process(self, request: AgentRequest) -> AgentResponse:
        decision = await self.route(request)

        # Persist the routing decision (Zone 2 — controlled, no PII) and record
        # the routing event in the audit trail for explainability.
        ref = f"routing/{decision.routing_id}.json"
        await self.storage.put(
            ref,
            json.dumps(decision.model_dump(), ensure_ascii=False).encode("utf-8"),
            DataZone.ZONE2,
        )
        await self.audit_log.append(
            AuditEntry(
                event_type="ROUTING_DECISION",
                agent_id=self.agent_id,
                request_id=request.request_id,
                routing_id=decision.routing_id,
                jurisdiction=request.jurisdiction_code.value,
                detail=(
                    f"-> {decision.target_domain.value} "
                    f"(priority={decision.priority.value}, "
                    f"sequential={decision.requires_sequential})"
                ),
            )
        )

        return AgentResponse(
            request_id=request.request_id,
            agent_id=self.agent_id,
            confidence=Confidence.HIGH,
            hitl_tier=HITLTier.NONE,
            full_output_ref=ref,
            jurisdiction_flags=[f"ROUTED:{decision.target_domain.value}"],
        )
