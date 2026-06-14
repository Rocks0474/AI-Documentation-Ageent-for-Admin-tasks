"""LMS / learning-catalog integration — stub.

Returns a deterministic fake course catalog keyed by skill. The real connector
(Phase 4/5) implements the same :meth:`LMSStub.fetch_modules` signature.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CourseModule:
    code: str
    title: str
    hours: int


# A small illustrative catalog. Unknown skills fall back to a generic path.
_CATALOG: dict[str, list[CourseModule]] = {
    "people_management": [
        CourseModule("PM-101", "Foundations of People Management", 8),
        CourseModule("PM-201", "Coaching and Feedback", 6),
        CourseModule("PM-301", "Performance Conversations", 4),
    ],
    "data_literacy": [
        CourseModule("DL-101", "Data Literacy Basics", 5),
        CourseModule("DL-201", "Interpreting People Analytics", 6),
    ],
    "compliance": [
        CourseModule("CMP-101", "Global HR Compliance Overview", 4),
        CourseModule("CMP-210", "Data Protection (GDPR / APPI)", 5),
    ],
}

_GENERIC = [
    CourseModule("GEN-101", "Skill Foundations", 6),
    CourseModule("GEN-201", "Applied Practice", 6),
]


class LMSStub:
    def __init__(self, connected: bool = False) -> None:
        self.connected = connected

    def fetch_modules(self, skill_target: str) -> list[CourseModule]:
        return list(_CATALOG.get(skill_target.lower().replace(" ", "_"), _GENERIC))
