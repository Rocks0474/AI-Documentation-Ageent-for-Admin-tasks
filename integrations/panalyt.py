"""Panalyt people-analytics integration — stub.

Returns deterministic fake cohort metrics derived from a hash of the inputs, so
tests are stable. The real Panalyt connector (Phase 4/5) will implement the same
:meth:`PanalytStub.fetch_cohort_metric` signature.

Important: this stub returns only aggregate cohort values — never individual
records. The cohort privacy floor is enforced by the Analytics Agent, not here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass
class CohortMetric:
    metric: str
    cohort_ref: str
    value: float


class PanalytStub:
    """No-op Panalyt connector returning deterministic fake aggregates."""

    def __init__(self, connected: bool = False) -> None:
        # `connected` mirrors PANALYT_CONNECTED; agents degrade gracefully when
        # False. The stub still returns data so local flows are exercisable.
        self.connected = connected

    def fetch_cohort_metric(self, metric: str, cohort_ref: str) -> CohortMetric:
        digest = hashlib.sha256(f"{metric}:{cohort_ref}".encode()).hexdigest()
        # Map the first bytes to a stable value in [0, 100).
        value = round((int(digest[:8], 16) % 10_000) / 100.0, 2)
        return CohortMetric(metric=metric, cohort_ref=cohort_ref, value=value)
