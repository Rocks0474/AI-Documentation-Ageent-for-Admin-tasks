"""Jurisdiction router for the HR Legal Agent.

Maps a legal question + jurisdiction to the applicable legal framework and
decides whether the matter is cleanly within a single supported jurisdiction.
Multi-jurisdiction questions (explicitly MULTI, or a question that references
two or more jurisdictions) are flagged as not cleanly supported, which forces a
LOW confidence and CHRO escalation downstream.
"""

from __future__ import annotations

from dataclasses import dataclass

from schemas.common import Jurisdiction

# Applicable legal framework summary per supported jurisdiction.
FRAMEWORKS: dict[Jurisdiction, str] = {
    Jurisdiction.JP: "Japanese labor law (労働基準法・労働契約法), APPI",
    Jurisdiction.US_FED: "US federal employment law (FLSA, Title VII, FMLA, WARN)",
    Jurisdiction.US_CA: "California employment law (Cal-WARN, FEHA, CCPA/CPRA)",
    Jurisdiction.EU: "EU law (EU AI Act, GDPR, collective dismissal directives)",
    Jurisdiction.SG: "Singapore Employment Act, PDPA",
}

# Tokens used to detect when a question spans multiple jurisdictions.
_JURISDICTION_MENTIONS: dict[Jurisdiction, tuple[str, ...]] = {
    Jurisdiction.JP: ("japan", "japanese", "日本", "tokyo"),
    Jurisdiction.US_FED: ("federal", "u.s. federal", "united states"),
    Jurisdiction.US_CA: ("california", "cal-warn", "feha"),
    Jurisdiction.EU: ("eu", "europe", "european union", "gdpr"),
    Jurisdiction.SG: ("singapore", "singaporean"),
}


@dataclass
class JurisdictionContext:
    jurisdiction: Jurisdiction
    framework: str
    supported: bool  # cleanly within one supported jurisdiction
    multi: bool      # spans multiple jurisdictions


def _detect_multi(jurisdiction: Jurisdiction, question: str) -> bool:
    if jurisdiction == Jurisdiction.MULTI:
        return True
    haystack = question.lower()
    matched = {
        j
        for j, tokens in _JURISDICTION_MENTIONS.items()
        if any(t in haystack for t in tokens)
    }
    return len(matched) >= 2


def route(jurisdiction: Jurisdiction, question: str = "") -> JurisdictionContext:
    multi = _detect_multi(jurisdiction, question)
    supported = jurisdiction in FRAMEWORKS and not multi
    framework = FRAMEWORKS.get(
        jurisdiction, "multi-jurisdictional — requires specialist human review"
    )
    return JurisdictionContext(
        jurisdiction=jurisdiction,
        framework=framework,
        supported=supported,
        multi=multi,
    )
