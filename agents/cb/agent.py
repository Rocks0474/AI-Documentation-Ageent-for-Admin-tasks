"""Compensation & Benefits (C&B) Agent — deterministic pay-band engine.

Comp recommendations must be auditable and reproducible, so offer ranges are
computed deterministically from an internal benchmark table — not invented by an
LLM. The bands here are illustrative internal placeholders; the real product
plugs in market data via the same interface. Bands are role/level/location
ranges, never an individual's salary (which would be Zone 1).
"""

from __future__ import annotations

import json

from adapters.base.audit_log import AuditEntry
from adapters.base.storage import DataZone
from agents.base.agent import BaseAgent
from schemas.cb import OfferRangeRequest, OfferRangeResult
from schemas.common import AgentRequest, AgentResponse, Confidence, HITLTier, Jurisdiction

# Illustrative base bands (annual, JPY-indexed) by level.
_BASE_BANDS_JPY: dict[str, tuple[int, int]] = {
    "L1": (3_000_000, 4_500_000),
    "L2": (4_000_000, 6_000_000),
    "L3": (5_500_000, 8_000_000),
    "L4": (7_500_000, 11_000_000),
    "L5": (10_000_000, 15_000_000),
    "L6": (14_000_000, 21_000_000),
}
_DEFAULT_LEVEL = "L3"

# Jurisdiction -> (currency, conversion factor applied to the JPY-indexed base).
# Factors are illustrative only.
_JURISDICTION_CURRENCY: dict[Jurisdiction, tuple[str, float]] = {
    Jurisdiction.JP: ("JPY", 1.0),
    Jurisdiction.US_FED: ("USD", 0.0067),
    Jurisdiction.US_CA: ("USD", 0.0075),
    Jurisdiction.EU: ("EUR", 0.0062),
    Jurisdiction.SG: ("SGD", 0.0090),
    Jurisdiction.MULTI: ("USD", 0.0067),
}


def compute_offer_range(req: OfferRangeRequest) -> OfferRangeResult:
    """Deterministically compute an offer range for a role/level/jurisdiction."""
    level = req.level.upper()
    low_jpy, high_jpy = _BASE_BANDS_JPY.get(level, _BASE_BANDS_JPY[_DEFAULT_LEVEL])
    currency, factor = _JURISDICTION_CURRENCY.get(
        req.jurisdiction_code, _JURISDICTION_CURRENCY[Jurisdiction.JP]
    )
    return OfferRangeResult(
        role_title=req.role_title,
        level=level,
        currency=currency,
        pay_band_low=round(low_jpy * factor, 2),
        pay_band_high=round(high_jpy * factor, 2),
        benchmark_source="INTERNAL",
    )


class CBAgent(BaseAgent):
    agent_id = "CB_AGENT"

    def _parse_payload(self, request: AgentRequest) -> OfferRangeRequest:
        data = dict(request.payload or {})
        data.setdefault("jurisdiction_code", request.jurisdiction_code)
        return OfferRangeRequest(**data)

    async def process(self, request: AgentRequest) -> AgentResponse:
        payload = self._parse_payload(request)
        result = compute_offer_range(payload)

        ref = f"cb/{request.request_id}.json"
        await self.storage.put(
            ref,
            json.dumps(result.model_dump(), ensure_ascii=False).encode("utf-8"),
            DataZone.ZONE2,
        )
        await self.audit_log.append(
            AuditEntry(
                event_type="CB_OFFER_RANGE",
                agent_id=self.agent_id,
                request_id=request.request_id,
                jurisdiction=payload.jurisdiction_code.value,
                detail=(
                    f"{result.role_title}/{result.level}: "
                    f"{result.pay_band_low}-{result.pay_band_high} {result.currency}"
                ),
            )
        )

        return AgentResponse(
            request_id=request.request_id,
            agent_id=self.agent_id,
            confidence=Confidence.HIGH,
            hitl_tier=HITLTier.RECOMMENDED,
            hitl_basis="Offer range — recommend human review before extending",
            full_output_ref=ref,
        )
