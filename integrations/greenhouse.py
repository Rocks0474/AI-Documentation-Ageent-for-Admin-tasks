"""Greenhouse ATS integration — stub.

Returns deterministic fake pipeline aggregates (stage counts only — never
candidate names or contact details, which would be Zone 1). The real connector
(Phase 4/5) implements the same :meth:`GreenhouseStub.fetch_pipeline` signature.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass
class PipelineSnapshot:
    requisition_ref: str
    stage_counts: dict[str, int] = field(default_factory=dict)
    total: int = 0


class GreenhouseStub:
    DEFAULT_STAGES: tuple[str, ...] = ("applied", "screen", "onsite", "offer")

    def __init__(self, connected: bool = False) -> None:
        self.connected = connected

    def fetch_pipeline(self, requisition_ref: str) -> PipelineSnapshot:
        counts: dict[str, int] = {}
        for stage in self.DEFAULT_STAGES:
            digest = hashlib.sha256(f"{requisition_ref}:{stage}".encode()).hexdigest()
            counts[stage] = int(digest[:4], 16) % 25  # 0..24, deterministic
        return PipelineSnapshot(
            requisition_ref=requisition_ref,
            stage_counts=counts,
            total=sum(counts.values()),
        )
