"""HRIS connectors — the only code that returns real employee PII (Zone 1).

A connector fetches an :class:`EmployeeRecord` from a source HR system. That
record contains Zone 1 data (names, national ids, salary figures, dates of
birth) and **must never leave the PII gateway boundary** — the gateway converts
it into a Zone 2 ``AnonymizedContext`` before anything reaches an agent.
"""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel


class EmployeeRecord(BaseModel):
    """ZONE 1 — real employee PII. Never serialize this toward an agent.

    Returned by HRIS connectors and consumed only inside the PII gateway.
    """

    employee_id: str
    full_name: str                       # Zone 1
    email: str                           # Zone 1
    national_id: Optional[str] = None    # マイナンバー / SSN / NRIC — Zone 1
    date_of_birth: Optional[datetime.date] = None  # Zone 1
    department: str
    job_level: str
    employment_type: str
    hire_date: datetime.date
    base_salary: int                     # Zone 1 (individual figure)
    currency: str
    manager_employee_id: Optional[str] = None
    jurisdiction: str
    on_protected_leave: bool = False


class HRISConnector(ABC):
    """Source-system connector returning Zone 1 employee records."""

    system_name: str = "BASE"

    @abstractmethod
    async def get_employee(self, employee_id: str) -> EmployeeRecord:
        """Return the full (Zone 1) record for ``employee_id``.

        Raises :class:`KeyError` if no such employee exists.
        """
        ...

    @abstractmethod
    async def list_employee_ids(self) -> list[str]:
        """Return the known employee ids (used to seed tokenization in dev)."""
        ...
