"""VectorDBAdapter — vector similarity search interface.

Backs retrieval over anonymized organizational context (Zone 2) and public
knowledge (Zone 3): regulatory content, published benchmarks, HR frameworks.
Indexes are partitioned by zone (e.g. ``VERTEX_INDEX_ID_ZONE2``,
``OPENSEARCH_ENDPOINT_ZONE3``). Zone 1 (PII) is never indexed. Concrete targets
map to Vertex AI Vector Search, OpenSearch, or an in-memory store for LOCAL.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, Field


class VectorDocument(BaseModel):
    """A document to upsert into a vector index."""

    id: str
    content: str
    metadata: dict = Field(default_factory=dict)
    # Optional precomputed embedding; implementations may embed `content` if absent.
    embedding: Optional[list[float]] = None


class VectorQueryResult(BaseModel):
    """A single similarity-search hit."""

    id: str
    score: float
    content: str
    metadata: dict = Field(default_factory=dict)


class VectorDBAdapter(ABC):
    """Upsert and similarity-query over a named, zone-scoped index."""

    @abstractmethod
    async def upsert(self, index: str, documents: list[VectorDocument]) -> int:
        """Upsert ``documents`` into ``index``; return the count written."""
        ...

    @abstractmethod
    async def query(
        self,
        index: str,
        query_text: str,
        top_k: int = 5,
        *,
        filter: Optional[dict] = None,
    ) -> list[VectorQueryResult]:
        """Return up to ``top_k`` most-similar documents from ``index``."""
        ...

    @abstractmethod
    async def delete(self, index: str, ids: list[str]) -> None:
        """Delete documents with the given ``ids`` from ``index``."""
        ...
