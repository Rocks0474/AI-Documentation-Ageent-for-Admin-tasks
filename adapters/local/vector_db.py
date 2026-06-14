"""LOCAL VectorDBAdapter — in-memory store with token-overlap scoring.

No real embeddings: similarity is approximated with Jaccard overlap of tokens,
which is deterministic and dependency-free — enough to exercise retrieval flows
locally and in tests. Indexes are partitioned by name (zone-scoped by caller).
"""

from __future__ import annotations

import re
from typing import Optional

from adapters.base.vector_db import (
    VectorDBAdapter,
    VectorDocument,
    VectorQueryResult,
)

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text)}


class LocalVectorDBAdapter(VectorDBAdapter):
    def __init__(self) -> None:
        self._indexes: dict[str, dict[str, VectorDocument]] = {}

    async def upsert(self, index: str, documents: list[VectorDocument]) -> int:
        store = self._indexes.setdefault(index, {})
        for document in documents:
            store[document.id] = document
        return len(documents)

    async def query(
        self,
        index: str,
        query_text: str,
        top_k: int = 5,
        *,
        filter: Optional[dict] = None,
    ) -> list[VectorQueryResult]:
        store = self._indexes.get(index, {})
        query_tokens = _tokens(query_text)

        scored: list[tuple[float, VectorDocument]] = []
        for document in store.values():
            if filter and not all(
                document.metadata.get(k) == v for k, v in filter.items()
            ):
                continue
            doc_tokens = _tokens(document.content)
            union = query_tokens | doc_tokens
            score = len(query_tokens & doc_tokens) / len(union) if union else 0.0
            scored.append((score, document))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            VectorQueryResult(
                id=document.id,
                score=score,
                content=document.content,
                metadata=document.metadata,
            )
            for score, document in scored[:top_k]
        ]

    async def delete(self, index: str, ids: list[str]) -> None:
        store = self._indexes.get(index, {})
        for doc_id in ids:
            store.pop(doc_id, None)


_adapter: Optional[LocalVectorDBAdapter] = None


def get_adapter() -> LocalVectorDBAdapter:
    global _adapter
    if _adapter is None:
        _adapter = LocalVectorDBAdapter()
    return _adapter
