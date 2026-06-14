"""Director Agent routing logic and priority queue.

Routing is deterministic-first: a keyword classifier maps an intent to a
:class:`Domain` with a confidence score. Deterministic routing is auditable and
free, which matters for enterprise trust ("can a Japanese CHRO trust this?").
The Director Agent falls back to the LLM only when the classifier is not
confident (see ``agents/director/agent.py``).

The :class:`RoutingQueue` orders routed work by :class:`Priority`
(CRITICAL > HIGH > STANDARD > ASYNC), FIFO within a priority band.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Optional

from schemas.common import Confidence, Priority
from schemas.director import Domain, RoutingDecision

# Deterministic keyword -> domain table. Domains are evaluated in the order
# below, so safety-critical domains (ER, LEGAL) win ties.
DOMAIN_KEYWORDS: dict[Domain, tuple[str, ...]] = {
    Domain.ER: (
        "termination", "terminate", "dismissal", "harassment", "discrimination",
        "discipline", "disciplinary", "grievance", "misconduct", "investigation",
        "layoff", "mass layoff", "redundancy", "whistleblower", "union",
        "団体交渉", "解雇", "整理解雇", "公益通報", "ハラスメント",
    ),
    Domain.LEGAL: (
        "legal opinion", "statute", "statutory interpretation", "regulation",
        "contract review", "litigation", "jurisdiction", "lawsuit", "法律",
        "法的", "legal risk",
    ),
    Domain.CB: (
        "compensation", "salary band", "pay band", "offer range", "bonus",
        "merit increase", "pay equity", "benefits", "remuneration", "賞与", "報酬",
    ),
    Domain.LD: (
        "training", "learning", "development plan", "upskilling", "reskilling",
        "course", "curriculum", "skills taxonomy", "lms", "研修",
    ),
    Domain.HR_OPS: (
        "onboarding", "offboarding", "transfer", "leave request", "payroll",
        "statutory filing", "lifecycle", "contract renewal", "算定基礎", "年末調整",
        "入社", "退社",
    ),
    Domain.TA: (
        "recruiting", "recruitment", "candidate", "pipeline", "interview",
        "hiring", "requisition", "sourcing", "offer letter", "採用",
    ),
    Domain.ANALYTICS: (
        "analytics", "attrition", "turnover", "headcount", "metrics", "dashboard",
        "cohort", "trend", "workforce report", "分析",
    ),
    Domain.HRBP: (
        "engagement", "retention", "manager coaching", "org design",
        "team morale", "people strategy", "business partner",
    ),
}

# Subset of ER signals severe enough to escalate routing priority to CRITICAL.
_ER_CRITICAL_HINTS: frozenset[str] = frozenset(
    {
        "termination", "terminate", "dismissal", "harassment", "discrimination",
        "mass layoff", "whistleblower", "団体交渉", "解雇", "整理解雇", "公益通報",
    }
)

# Base priority per domain before any escalation.
_DOMAIN_BASE_PRIORITY: dict[Domain, Priority] = {
    Domain.ER: Priority.HIGH,
    Domain.LEGAL: Priority.HIGH,
}

# Domains that, when chosen, run as a sequential ER -> LEGAL pair.
_SEQUENTIAL_ER_LEGAL = (Domain.ER, Domain.LEGAL)


@dataclass
class Classification:
    """Result of deterministic keyword classification."""

    domain: Optional[Domain]
    confidence: Confidence
    matched_keywords: list[str] = field(default_factory=list)
    scores: dict[Domain, int] = field(default_factory=dict)


class DomainClassifier:
    """Deterministic keyword classifier over an intent string."""

    def __init__(self, keyword_table: Optional[dict[Domain, tuple[str, ...]]] = None):
        self._table = keyword_table or DOMAIN_KEYWORDS

    def classify(self, text: str) -> Classification:
        haystack = text.lower()
        scores: dict[Domain, int] = {}
        matched: dict[Domain, list[str]] = {}

        for domain, keywords in self._table.items():
            hits = [kw for kw in keywords if kw.lower() in haystack]
            if hits:
                scores[domain] = len(hits)
                matched[domain] = hits

        if not scores:
            return Classification(domain=None, confidence=Confidence.LOW, scores={})

        top_score = max(scores.values())
        leaders = [d for d, s in scores.items() if s == top_score]
        # Tie-break by the fixed table order (ER/LEGAL first => safety-first).
        winner = next(d for d in self._table if d in leaders)

        if len(leaders) == 1 and top_score >= 1:
            confidence = Confidence.HIGH
        else:
            confidence = Confidence.MEDIUM  # ambiguous — multiple domains tied

        return Classification(
            domain=winner,
            confidence=confidence,
            matched_keywords=matched[winner],
            scores=scores,
        )


def derive_priority(
    domain: Domain, requested: Priority, matched_keywords: list[str]
) -> Priority:
    """Combine the requester's priority, the domain floor, and ER escalation."""
    base = _DOMAIN_BASE_PRIORITY.get(domain, requested)
    candidates = {requested, base}
    if domain == Domain.ER and any(
        kw in _ER_CRITICAL_HINTS for kw in matched_keywords
    ):
        candidates.add(Priority.CRITICAL)
    # Return the most urgent among the candidates.
    order = [Priority.CRITICAL, Priority.HIGH, Priority.STANDARD, Priority.ASYNC]
    return next(p for p in order if p in candidates)


def build_routing_decision(
    routing_id: str,
    classification: Classification,
    requested_priority: Priority,
) -> RoutingDecision:
    """Turn a classification into a concrete :class:`RoutingDecision`."""
    domain = classification.domain or Domain.HRBP  # generalist fallback
    priority = derive_priority(
        domain, requested_priority, classification.matched_keywords
    )

    # ER cases that require Legal run as a sequential ER -> LEGAL workflow.
    sequential = domain == Domain.ER and any(
        kw in _ER_CRITICAL_HINTS for kw in classification.matched_keywords
    )

    rationale = (
        f"matched={classification.matched_keywords}; "
        f"confidence={classification.confidence.value}"
        if classification.domain
        else "no keyword match — defaulted to HRBP generalist"
    )

    return RoutingDecision(
        routing_id=routing_id,
        target_domain=domain,
        priority=priority,
        rationale=rationale,
        requires_sequential=sequential,
        sequence=list(_SEQUENTIAL_ER_LEGAL) if sequential else [],
    )


_PRIORITY_RANK: dict[Priority, int] = {
    Priority.CRITICAL: 0,
    Priority.HIGH: 1,
    Priority.STANDARD: 2,
    Priority.ASYNC: 3,
}


class RoutingQueue:
    """Priority queue for routed work. CRITICAL first; FIFO within a band."""

    def __init__(self) -> None:
        # Heap of (priority_rank, insertion_seq, decision).
        self._heap: list[tuple[int, int, RoutingDecision]] = []
        self._counter = itertools.count()

    def __len__(self) -> int:
        return len(self._heap)

    def enqueue(self, decision: RoutingDecision) -> None:
        import heapq

        rank = _PRIORITY_RANK[decision.priority]
        heapq.heappush(self._heap, (rank, next(self._counter), decision))

    def dequeue(self) -> Optional[RoutingDecision]:
        import heapq

        if not self._heap:
            return None
        return heapq.heappop(self._heap)[2]
