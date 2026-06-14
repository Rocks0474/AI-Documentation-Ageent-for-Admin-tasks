"""Pydantic message schemas for inter-agent communication.

Per Constraint #2, every schema here is reviewed for Zone 1 (PII) field names.
Identifiers are anonymized references; personal data never appears in a schema.
"""

from schemas.common import (
    AgentRequest,
    AgentResponse,
    AnonymizedEmployeeRef,
    CohortRef,
    Confidence,
    HITLTier,
    Jurisdiction,
    OutputLanguage,
    Priority,
)

__all__ = [
    "AgentRequest",
    "AgentResponse",
    "AnonymizedEmployeeRef",
    "CohortRef",
    "Confidence",
    "HITLTier",
    "Jurisdiction",
    "OutputLanguage",
    "Priority",
]
