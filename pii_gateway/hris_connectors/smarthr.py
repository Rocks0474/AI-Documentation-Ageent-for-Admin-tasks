"""SmartHR HRIS connector — stub.

SmartHR is a Japanese HRIS, so the fake data is JP-context: kanji + romaji
names, a 12-digit My Number (マイナンバー), JPY salaries. Data is deterministic
per ``employee_id`` (hash-derived) so tests are stable. Returns Zone 1 records —
the gateway anonymizes them before any agent sees anything.

Replace with a real SmartHR API client (``HRIS_API_BASE_URL`` + the
``hris-api-key`` secret) in deployment; the interface is unchanged.
"""

from __future__ import annotations

import datetime
import hashlib

from pii_gateway.hris_connectors.base import EmployeeRecord, HRISConnector

_FAMILY = ["佐藤", "鈴木", "高橋", "田中", "渡辺", "伊藤", "山本", "中村"]
_FAMILY_ROMAJI = [
    "Sato", "Suzuki", "Takahashi", "Tanaka", "Watanabe", "Ito", "Yamamoto", "Nakamura",
]
_GIVEN = ["陽菜", "蓮", "結衣", "大翔", "さくら", "悠真", "美咲", "湊"]
_GIVEN_ROMAJI = ["Hina", "Ren", "Yui", "Hiroto", "Sakura", "Yuma", "Misaki", "Minato"]
_DEPARTMENTS = ["Engineering", "Sales", "Corporate", "People", "Finance", "Product"]
_LEVELS = ["L1", "L2", "L3", "L4", "L5", "L6"]
_EMPLOYMENT = ["正社員", "契約社員"]


def _seed(employee_id: str) -> int:
    return int(hashlib.sha256(employee_id.encode()).hexdigest()[:12], 16)


class SmartHRConnector(HRISConnector):
    system_name = "SMARTHR"

    def __init__(self, employee_ids: list[str] | None = None) -> None:
        self._employee_ids = employee_ids or [f"emp-{i:04d}" for i in range(1, 21)]

    async def list_employee_ids(self) -> list[str]:
        return list(self._employee_ids)

    async def get_employee(self, employee_id: str) -> EmployeeRecord:
        if employee_id not in self._employee_ids:
            raise KeyError(employee_id)

        n = _seed(employee_id)
        fam = n % len(_FAMILY)
        giv = (n // 7) % len(_GIVEN)
        level_idx = (n // 13) % len(_LEVELS)
        # Base salary scales with level, JPY.
        base = 3_000_000 + level_idx * 2_200_000 + (n % 900_000)
        hire_year = 2014 + (n % 11)
        birth_year = 1972 + (n % 30)
        my_number = f"{n % 1_000_000_000_000:012d}"  # 12 digits — マイナンバー

        return EmployeeRecord(
            employee_id=employee_id,
            full_name=f"{_FAMILY[fam]}{_GIVEN[giv]} ({_FAMILY_ROMAJI[fam]} {_GIVEN_ROMAJI[giv]})",
            email=f"{_FAMILY_ROMAJI[fam].lower()}.{_GIVEN_ROMAJI[giv].lower()}@example.co.jp",
            national_id=my_number,
            date_of_birth=datetime.date(birth_year, 1 + (n % 12), 1 + (n % 27)),
            department=_DEPARTMENTS[(n // 17) % len(_DEPARTMENTS)],
            job_level=_LEVELS[level_idx],
            employment_type=_EMPLOYMENT[n % len(_EMPLOYMENT)],
            hire_date=datetime.date(hire_year, 1 + (n % 12), 1 + (n % 27)),
            base_salary=base,
            currency="JPY",
            manager_employee_id=self._employee_ids[(n // 19) % len(self._employee_ids)],
            jurisdiction="JP",
            on_protected_leave=(n % 11 == 0),
        )
