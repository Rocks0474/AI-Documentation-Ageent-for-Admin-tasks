"""GoodTime interview-scheduling integration — stub.

Returns deterministic fake scheduling slots. Interviewers are referenced by an
anonymized ref, never by name. The real connector (Phase 4/5) implements the
same :meth:`GoodTimeStub.fetch_slots` signature.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass
class SchedulingSlot:
    start_iso: str
    interviewer_ref: str


class GoodTimeStub:
    def __init__(self, connected: bool = False) -> None:
        self.connected = connected

    def fetch_slots(self, requisition_ref: str, count: int = 3) -> list[SchedulingSlot]:
        slots: list[SchedulingSlot] = []
        for i in range(count):
            digest = hashlib.sha256(f"{requisition_ref}:{i}".encode()).hexdigest()
            day = 1 + (int(digest[:2], 16) % 28)
            hour = 9 + (int(digest[2:4], 16) % 8)
            slots.append(
                SchedulingSlot(
                    start_iso=f"2026-07-{day:02d}T{hour:02d}:00:00+09:00",
                    interviewer_ref=f"interviewer_ref_{digest[:6]}",
                )
            )
        return slots
