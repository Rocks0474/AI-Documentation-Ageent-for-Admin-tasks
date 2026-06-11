"""PIIDetector — Zone 1 (PII) pre-flight guard.

Every agent runs this over an incoming request before any processing. If Zone 1
data is detected the agent refuses the payload and returns
``PII_BOUNDARY_VIOLATION`` (see ``agents/base/agent.py``). Detection is
heuristic and intentionally conservative on the operational *envelope* (request
ids, roles, the HITL approver address) so that routine requests are not flagged.

Two detection strategies:

  1. Field-name detection — a key whose normalized name is a known Zone 1
     attribute (``name``, ``email``, ``salary``, ``my_number``, ``ssn``,
     ``nric``, ...).
  2. Value-pattern detection — a string value matching a high-signal pattern
     (email address, US SSN, Japanese My Number, Singapore NRIC).

Critically, a finding records only the *location* (key path) and *category* —
never the offending value. Constraint #2: never log PII content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# Operational envelope keys that are exempt from value scanning. These carry
# routing/operational data (e.g. `hitl_approver` may legitimately be an email).
DEFAULT_EXEMPT_KEYS: frozenset[str] = frozenset(
    {
        "request_id",
        "routing_id",
        "source",
        "jurisdiction_code",
        "jurisdiction",
        "output_language",
        "priority",
        "requesting_user_role",
        "hitl_approver",
        "hitl_tier",
        "hitl_basis",
        "timestamp",
        "agent_id",
        "entry_id",
        "event_type",
        "confidence",
        "full_output_ref",
    }
)

# Normalized key names that indicate Zone 1 data. Matched on the whole
# normalized key, so e.g. `pay_band_low` does NOT match `salary`.
PII_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "name",
        "first_name",
        "last_name",
        "full_name",
        "employee_name",
        "candidate_name",
        "legal_name",
        "email",
        "email_address",
        "personal_email",
        "phone",
        "phone_number",
        "mobile",
        "home_address",
        "address",
        "salary",
        "individual_salary",
        "compensation_amount",
        "base_pay",
        "my_number",
        "mynumber",
        "マイナンバー",
        "ssn",
        "social_security_number",
        "nric",
        "national_id",
        "passport",
        "passport_number",
        "date_of_birth",
        "dob",
        "birthdate",
        "health",
        "health_condition",
        "medical",
        "disability",
        "immigration_status",
        "visa_status",
        "bank_account",
        "bank_account_number",
    }
)

# High-signal value patterns. Keep conservative to avoid false positives.
_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("US_SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("JP_MY_NUMBER", re.compile(r"\b\d{12}\b")),
    ("SG_NRIC", re.compile(r"\b[STFGstfg]\d{7}[A-Za-z]\b")),
)

_NORMALIZE_RE = re.compile(r"[^0-9a-z぀-ヿ一-鿿]+")


def _normalize_key(key: str) -> str:
    return _NORMALIZE_RE.sub("_", key.strip().lower()).strip("_")


@dataclass(frozen=True)
class PIIFinding:
    """A single detection. Records location + category only — never the value."""

    location: str  # dotted key path, e.g. "payload.employee.name"
    category: str  # e.g. "FIELD_NAME:email" or "VALUE:US_SSN"


@dataclass
class PIIScanResult:
    detected: bool
    findings: list[PIIFinding] = field(default_factory=list)

    @property
    def categories(self) -> list[str]:
        return sorted({f.category for f in self.findings})

    @property
    def summary(self) -> str:
        """Safe, value-free summary suitable for logging/returning to callers."""
        if not self.detected:
            return "No Zone 1 data detected."
        parts = [f"{f.category}@{f.location}" for f in self.findings]
        return "Zone 1 data detected: " + "; ".join(sorted(parts))


class PIIDetector:
    def __init__(
        self,
        exempt_keys: Optional[Iterable[str]] = None,
        *,
        field_names: Optional[Iterable[str]] = None,
    ) -> None:
        self._exempt = (
            frozenset(exempt_keys) if exempt_keys is not None else DEFAULT_EXEMPT_KEYS
        )
        self._field_names = (
            frozenset(field_names) if field_names is not None else PII_FIELD_NAMES
        )

    def scan(self, data: Any) -> PIIScanResult:
        findings: list[PIIFinding] = []
        self._walk(data, path="", key=None, findings=findings)
        # De-duplicate while preserving order.
        seen: set[tuple[str, str]] = set()
        unique: list[PIIFinding] = []
        for finding in findings:
            token = (finding.location, finding.category)
            if token not in seen:
                seen.add(token)
                unique.append(finding)
        return PIIScanResult(detected=bool(unique), findings=unique)

    def _walk(
        self,
        node: Any,
        *,
        path: str,
        key: Optional[str],
        findings: list[PIIFinding],
    ) -> None:
        if isinstance(node, dict):
            for child_key, child_value in node.items():
                normalized = _normalize_key(str(child_key))
                child_path = f"{path}.{child_key}" if path else str(child_key)
                if normalized in self._exempt:
                    continue
                if normalized in self._field_names:
                    findings.append(
                        PIIFinding(
                            location=child_path,
                            category=f"FIELD_NAME:{normalized}",
                        )
                    )
                self._walk(
                    child_value, path=child_path, key=normalized, findings=findings
                )
        elif isinstance(node, (list, tuple, set)):
            for index, item in enumerate(node):
                child_path = f"{path}[{index}]"
                self._walk(item, path=child_path, key=key, findings=findings)
        elif isinstance(node, str):
            if key in self._exempt:
                return
            for category, pattern in _VALUE_PATTERNS:
                if pattern.search(node):
                    findings.append(
                        PIIFinding(location=path or "<root>", category=f"VALUE:{category}")
                    )
