"""Workday HRIS connector — stub.

US-context fake data (US names, SSN-format national id, USD salaries),
deterministic per ``employee_id``. Returns Zone 1 records; the gateway
anonymizes them. Replace with a real Workday client in deployment.
"""

from __future__ import annotations

import datetime
import hashlib

from pii_gateway.hris_connectors.base import EmployeeRecord, HRISConnector

_FIRST = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Sam", "Jamie"]
_LAST = ["Johnson", "Williams", "Brown", "Garcia", "Miller", "Davis", "Lopez", "Wilson"]
_DEPARTMENTS = ["Engineering", "Sales", "Corporate", "People", "Finance", "Product"]
_LEVELS = ["L1", "L2", "L3", "L4", "L5", "L6"]


def _seed(employee_id: str) -> int:
    return int(hashlib.sha256(employee_id.encode()).hexdigest()[:12], 16)


class WorkdayConnector(HRISConnector):
    system_name = "WORKDAY"

    def __init__(self, employee_ids: list[str] | None = None) -> None:
        self._employee_ids = employee_ids or [f"wd-{i:04d}" for i in range(1, 21)]

    async def list_employee_ids(self) -> list[str]:
        return list(self._employee_ids)

    async def get_employee(self, employee_id: str) -> EmployeeRecord:
        if employee_id not in self._employee_ids:
            raise KeyError(employee_id)

        n = _seed(employee_id)
        first = _FIRST[n % len(_FIRST)]
        last = _LAST[(n // 7) % len(_LAST)]
        level_idx = (n // 13) % len(_LEVELS)
        base = 70_000 + level_idx * 35_000 + (n % 15_000)  # USD
        ssn = f"{n % 900 + 100:03d}-{n % 90 + 10:02d}-{n % 9000 + 1000:04d}"

        return EmployeeRecord(
            employee_id=employee_id,
            full_name=f"{first} {last}",
            email=f"{first.lower()}.{last.lower()}@example.com",
            national_id=ssn,
            date_of_birth=datetime.date(1972 + (n % 30), 1 + (n % 12), 1 + (n % 27)),
            department=_DEPARTMENTS[(n // 17) % len(_DEPARTMENTS)],
            job_level=_LEVELS[level_idx],
            employment_type="FULL_TIME",
            hire_date=datetime.date(2014 + (n % 11), 1 + (n % 12), 1 + (n % 27)),
            base_salary=base,
            currency="USD",
            manager_employee_id=self._employee_ids[(n // 19) % len(self._employee_ids)],
            jurisdiction="US-FED",
            on_protected_leave=(n % 11 == 0),
        )
