"""PII gateway — the anonymized-ref resolver service (not an agent).

This is the only component that touches real employee PII. It:

  - issues opaque ``anonymized_employee_ref`` tokens for real employee ids
    (tokenization; the reverse mapping lives only here, the "token vault"),
  - resolves a ref by fetching the Zone 1 :class:`EmployeeRecord` from an HRIS
    connector and returning only an :class:`AnonymizedContext` (Zone 2 —
    bands/categories, never names, national ids, dates of birth, or salary
    figures).

A Zone 1 field must never appear in the resolved context. As a safety net, the
gateway runs the :class:`PIIDetector` over every context it produces and refuses
to return one that trips it (that would be a sanitization bug).
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import os
from typing import Optional

from pydantic import BaseModel, Field

from pii_gateway.detector import PIIDetector
from pii_gateway.hris_connectors.base import EmployeeRecord, HRISConnector


class UnknownRefError(KeyError):
    """Raised when an anonymized ref has not been issued by this gateway."""


class AnonymizedContext(BaseModel):
    """ZONE 2 — safe to pass to agents. Contains no Zone 1 fields.

    Identifiers are anonymized refs; quantities are coarse bands, not figures.
    """

    anonymized_employee_ref: str
    department: str
    job_level: str
    employment_type: str
    jurisdiction: str
    tenure_band: str                       # e.g. "3-5y"
    age_band: Optional[str] = None         # e.g. "30-39" (coarse — not DOB)
    pay_band: Optional[str] = None         # e.g. "JPY 6-8M" (band — not figure)
    anonymized_manager_ref: Optional[str] = None
    on_protected_leave: bool = False
    flags: list[str] = Field(default_factory=list)


def _tenure_band(hire_date: datetime.date, today: datetime.date) -> str:
    years = (today - hire_date).days / 365.25
    if years < 1:
        return "<1y"
    if years < 3:
        return "1-3y"
    if years < 5:
        return "3-5y"
    if years < 10:
        return "5-10y"
    return "10y+"


def _age_band(dob: Optional[datetime.date], today: datetime.date) -> Optional[str]:
    if dob is None:
        return None
    age = int((today - dob).days / 365.25)
    decade = max(20, (age // 10) * 10)
    return f"{decade}-{decade + 9}"


def _pay_band(salary: int, currency: str) -> str:
    # Coarse bands keep individual compensation out of Zone 2. Thresholds are
    # JPY-indexed; other currencies are scaled to comparable bands.
    factor = {"JPY": 1.0, "USD": 150.0, "EUR": 160.0, "SGD": 110.0}.get(currency, 1.0)
    jpy = salary * factor
    edges = [4_000_000, 6_000_000, 8_000_000, 11_000_000, 15_000_000]
    labels_jpy = ["<4M", "4-6M", "6-8M", "8-11M", "11-15M", "15M+"]
    idx = sum(1 for e in edges if jpy >= e)
    return f"{currency} {labels_jpy[idx]}"


class PIIGateway:
    def __init__(
        self,
        connector: HRISConnector,
        *,
        salt: Optional[str] = None,
        detector: Optional[PIIDetector] = None,
    ) -> None:
        self._connector = connector
        # In production this salt is a managed secret and the vault is a
        # KMS-encrypted store; in LOCAL/dev it is in-memory.
        self._salt = (salt or os.environ.get("PII_GATEWAY_SALT", "local-dev-salt")).encode()
        self._vault: dict[str, str] = {}  # anonymized_ref -> employee_id
        self._detector = detector or PIIDetector()

    def _ref_for(self, employee_id: str) -> str:
        digest = hmac.new(self._salt, employee_id.encode(), hashlib.sha256).hexdigest()
        return f"emp_ref_{digest[:16]}"

    async def tokenize(self, employee_id: str) -> str:
        """Issue (idempotently) the anonymized ref for a real employee id."""
        ref = self._ref_for(employee_id)
        self._vault[ref] = employee_id
        return ref

    async def seed_from_connector(self) -> list[str]:
        """Tokenize every known employee; returns the issued refs (dev helper)."""
        return [await self.tokenize(eid) for eid in await self._connector.list_employee_ids()]

    async def resolve(
        self, anonymized_employee_ref: str, *, today: Optional[datetime.date] = None
    ) -> AnonymizedContext:
        """Resolve a ref to a Zone 2 context. PII never leaves this method."""
        employee_id = self._vault.get(anonymized_employee_ref)
        if employee_id is None:
            raise UnknownRefError(anonymized_employee_ref)

        record = await self._connector.get_employee(employee_id)  # Zone 1
        context = self._sanitize(anonymized_employee_ref, record, today or datetime.date.today())

        # Safety net: a produced context must never trip the PII detector.
        scan = self._detector.scan(context.model_dump())
        if scan.detected:
            raise RuntimeError(
                f"PII gateway sanitization leak ({scan.summary}) — refusing to return context"
            )
        return context

    def _sanitize(
        self, ref: str, record: EmployeeRecord, today: datetime.date
    ) -> AnonymizedContext:
        manager_ref = (
            self._ref_for(record.manager_employee_id)
            if record.manager_employee_id
            else None
        )
        return AnonymizedContext(
            anonymized_employee_ref=ref,
            department=record.department,
            job_level=record.job_level,
            employment_type=record.employment_type,
            jurisdiction=record.jurisdiction,
            tenure_band=_tenure_band(record.hire_date, today),
            age_band=_age_band(record.date_of_birth, today),
            pay_band=_pay_band(record.base_salary, record.currency),
            anonymized_manager_ref=manager_ref,
            on_protected_leave=record.on_protected_leave,
        )


def build_connector(system: Optional[str] = None) -> HRISConnector:
    """Build the HRIS connector for ``HRIS_SYSTEM`` (SMARTHR by default)."""
    name = (system or os.environ.get("HRIS_SYSTEM", "SMARTHR")).upper()
    if name == "WORKDAY":
        from pii_gateway.hris_connectors.workday import WorkdayConnector

        return WorkdayConnector()
    from pii_gateway.hris_connectors.smarthr import SmartHRConnector

    return SmartHRConnector()


def build_pii_gateway() -> PIIGateway:
    """Build a PII gateway wired to the configured HRIS connector."""
    return PIIGateway(build_connector())
