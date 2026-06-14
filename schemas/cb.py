"""Compensation & Benefits (C&B) Agent schemas.

Pay bands are role/level/location-based ranges — never an individual's salary,
which would be Zone 1. Field names deliberately avoid the ``salary`` token to
keep schemas clean under PII review (Constraint #2).
"""

from __future__ import annotations

from pydantic import BaseModel

from schemas.common import Jurisdiction


class OfferRangeRequest(BaseModel):
    role_title: str
    level: str
    location: str  # work location — not a home address
    jurisdiction_code: Jurisdiction


class OfferRangeResult(BaseModel):
    role_title: str
    level: str
    currency: str
    pay_band_low: float
    pay_band_high: float
    benchmark_source: str = "INTERNAL"
