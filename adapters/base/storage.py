"""StorageAdapter — object storage interface, partitioned by data zone.

Storage is partitioned by :class:`DataZone`. Zone 1 (PII) is deliberately
*absent* from this interface: agents and adapters never read or write Zone 1
data. The PII gateway is the only component that touches real personal data,
and it does not use this adapter for it.

Zone mapping to concrete buckets (e.g. ``GCS_BUCKET_ZONE2``,
``S3_BUCKET_AUDIT``) is resolved inside the concrete implementation, never by
the caller.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional


class DataZone(str, Enum):
    """Permitted storage zones. Zone 1 (PII) is intentionally not representable."""

    ZONE2 = "ZONE2"  # Controlled — anonymized organizational context
    ZONE3 = "ZONE3"  # Permitted — public knowledge, benchmarks, frameworks
    AUDIT = "AUDIT"  # Append-only audit artifacts (full output payloads, etc.)


class StorageAdapter(ABC):
    """Key/blob object storage scoped to a :class:`DataZone`."""

    @abstractmethod
    async def put(
        self,
        key: str,
        data: bytes,
        zone: DataZone,
        *,
        content_type: str = "application/octet-stream",
        metadata: Optional[dict[str, str]] = None,
    ) -> str:
        """Store ``data`` at ``key`` within ``zone``; return the storage key/ref."""
        ...

    @abstractmethod
    async def get(self, key: str, zone: DataZone) -> bytes:
        """Return the bytes stored at ``key`` within ``zone``.

        Raises ``KeyError`` if the object does not exist.
        """
        ...

    @abstractmethod
    async def exists(self, key: str, zone: DataZone) -> bool:
        """Return whether an object exists at ``key`` within ``zone``."""
        ...

    @abstractmethod
    async def delete(self, key: str, zone: DataZone) -> None:
        """Delete the object at ``key`` within ``zone`` (no-op if absent)."""
        ...

    @abstractmethod
    async def list(self, prefix: str, zone: DataZone) -> list[str]:
        """Return keys within ``zone`` that start with ``prefix``."""
        ...
