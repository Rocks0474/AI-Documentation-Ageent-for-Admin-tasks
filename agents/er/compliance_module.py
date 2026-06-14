"""Module B — the ER Agent's deterministic compliance gate.

Runs before Module A (the LLM reasoning layer) in every ER case (Constraint #4).
Pure Python: no LLM calls, no network calls. A rule match yields an immediate
result that the prompt layer cannot override. ``HARD_STOP`` bypasses Module A
entirely.

Implementation note: rules are expressed as plain predicate callables over a
typed context. This is deliberately *not* an ``eval``-based string-template
engine — that approach is both a security hazard and impossible to evaluate
correctly at runtime (the templates would have to be evaluated as live Python).
Deterministic predicates are auditable, testable, and cannot be influenced by
any model output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class StatutoryDeadline:
    statute: str
    deadline: Optional[datetime]
    action_required: str


@dataclass
class ComplianceResult:
    result: str  # HARD_STOP | COMPLIANCE_FLAG | CLEAR
    triggered_rules: list[str] = field(default_factory=list)
    rule_descriptions: list[str] = field(default_factory=list)
    statutory_deadlines: list[StatutoryDeadline] = field(default_factory=list)
    legal_agent_required: bool = False
    hitl_tier: str = "NONE"
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class _RuleContext:
    """Normalized inputs a rule predicate evaluates against."""

    facts: str  # already lower-cased
    jurisdiction: str
    employee_count: int
    works_council_present: bool
    union_present: bool


# Rules that, on match, force an immediate HARD_STOP. Order is most-severe
# first; every matching rule is collected (not just the first).
_Predicate = Callable[["_RuleContext"], bool]

# Rules whose presence requires routing to the Legal Agent.
_LEGAL_AGENT_RULES = frozenset(
    {
        "TERMINATION",
        "HARASSMENT_ALLEGATION",
        "SEIRI_KAIKO_JP",
        "UNION_DEMAND",
        "EU_COLLECTIVE_DISMISSAL",
    }
)


class ERComplianceModule:
    """Deterministic rule engine. All rules return immediately on match."""

    HARD_STOP_RULES: list[tuple[str, _Predicate, str]] = [
        (
            "TERMINATION",
            lambda c: "termination" in c.facts,
            "Termination detected — MANDATORY HITL, Legal Agent required",
        ),
        (
            "HARASSMENT_ALLEGATION",
            lambda c: "harassment" in c.facts or "discrimination" in c.facts,
            "Harassment/discrimination allegation — investigation protocol, "
            "Legal Agent required",
        ),
        (
            "WARN_TRIGGER_US",
            lambda c: c.employee_count >= 100 and c.jurisdiction == "US-FED",
            "WARN Act threshold — 60-day notice clock",
        ),
        (
            "CALWARN_TRIGGER",
            lambda c: c.employee_count >= 50 and c.jurisdiction == "US-CA",
            "Cal-WARN threshold — stricter than federal",
        ),
        (
            "SEIRI_KAIKO_JP",
            lambda c: c.jurisdiction == "JP" and "mass layoff" in c.facts,
            "整理解雇 — 4-factor test required, Legal Agent required",
        ),
        (
            "EU_COLLECTIVE_DISMISSAL",
            lambda c: c.jurisdiction == "EU" and "collective" in c.facts,
            "EU collective dismissal — works council consultation mandatory",
        ),
        (
            "UNION_DEMAND",
            lambda c: "団体交渉" in c.facts or "union demand" in c.facts,
            "Union 団体交渉 demand — negotiation protocol, Legal Agent required",
        ),
        (
            "WORKS_COUNCIL",
            lambda c: c.works_council_present,
            "Works council consultation obligation triggered",
        ),
        (
            "PROTECTED_LEAVE",
            lambda c: (
                "育児休業" in c.facts
                or "fmla" in c.facts
                or "maternity" in c.facts
            ),
            "Protected leave intersection with disciplinary action",
        ),
        (
            "WHISTLEBLOWER",
            lambda c: "公益通報" in c.facts or "whistleblower" in c.facts,
            "Whistleblower signal — enhanced protection protocol",
        ),
        (
            "DATA_BREACH_PII",
            lambda c: "data breach" in c.facts and "employee" in c.facts,
            "Employee PII data breach — APPI/GDPR notification clock starts",
        ),
    ]

    def check(
        self,
        facts: str,
        jurisdiction: str,
        employee_count: int = 0,
        works_council_present: bool = False,
        union_present: bool = False,
    ) -> ComplianceResult:
        context = _RuleContext(
            facts=facts.lower(),
            jurisdiction=jurisdiction,
            employee_count=employee_count,
            works_council_present=works_council_present,
            union_present=union_present,
        )

        triggered: list[str] = []
        descriptions: list[str] = []

        for rule_id, predicate, description in self.HARD_STOP_RULES:
            try:
                matched = predicate(context)
            except Exception:  # noqa: S112 — a malformed rule must never crash the gate
                continue
            if matched:
                triggered.append(rule_id)
                descriptions.append(description)

        if triggered:
            return ComplianceResult(
                result="HARD_STOP",
                triggered_rules=triggered,
                rule_descriptions=descriptions,
                legal_agent_required=any(r in _LEGAL_AGENT_RULES for r in triggered),
                hitl_tier="MANDATORY",
            )

        return ComplianceResult(result="CLEAR")
