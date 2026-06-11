"""GCP VectorDBAdapter — Vertex AI Vector Search.

Each logical index name (e.g. ``zone2`` / ``zone3``) maps to a Vertex AI index
(for upsert/remove) plus a deployed index on a *private* index endpoint (for
nearest-neighbour queries). Text is embedded via a Vertex text-embedding model.

Note: Vertex Vector Search stores vectors + datapoint ids, not document text.
Query results therefore carry id + score; ``content`` is left empty (the caller
resolves content from its own store by id if needed). This is an intentional
difference from the in-memory LOCAL adapter and is documented in the runbook.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Optional, Protocol

from adapters.base.vector_db import (
    VectorDBAdapter,
    VectorDocument,
    VectorQueryResult,
)


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


@dataclass
class VertexIndexConfig:
    index: object              # aiplatform.MatchingEngineIndex (upsert/remove)
    endpoint: object           # aiplatform.MatchingEngineIndexEndpoint (query)
    deployed_index_id: str


class GCPVectorDBAdapter(VectorDBAdapter):
    def __init__(
        self, indexes: dict[str, VertexIndexConfig], embedder: Embedder
    ) -> None:
        self._indexes = indexes
        self._embedder = embedder

    def _config(self, index: str) -> VertexIndexConfig:
        config = self._indexes.get(index)
        if config is None:
            raise ValueError(f"No Vertex index configured for {index!r}")
        return config

    async def upsert(self, index: str, documents: list[VectorDocument]) -> int:
        config = self._config(index)

        def _embed_all() -> list[dict]:
            datapoints = []
            for doc in documents:
                vector = doc.embedding or self._embedder.embed(doc.content)
                datapoints.append(
                    {"datapoint_id": doc.id, "feature_vector": list(vector)}
                )
            return datapoints

        datapoints = await asyncio.to_thread(_embed_all)
        await asyncio.to_thread(config.index.upsert_datapoints, datapoints=datapoints)
        return len(datapoints)

    async def query(
        self,
        index: str,
        query_text: str,
        top_k: int = 5,
        *,
        filter: Optional[dict] = None,
    ) -> list[VectorQueryResult]:
        config = self._config(index)

        def _query():
            vector = self._embedder.embed(query_text)
            return config.endpoint.find_neighbors(
                deployed_index_id=config.deployed_index_id,
                queries=[vector],
                num_neighbors=top_k,
            )

        neighbor_groups = await asyncio.to_thread(_query)
        results: list[VectorQueryResult] = []
        # find_neighbors returns one neighbour list per query; we sent one query.
        for neighbor in (neighbor_groups[0] if neighbor_groups else []):
            results.append(
                VectorQueryResult(
                    id=neighbor.id,
                    score=float(getattr(neighbor, "distance", 0.0)),
                    content="",
                    metadata={},
                )
            )
        return results

    async def delete(self, index: str, ids: list[str]) -> None:
        config = self._config(index)
        await asyncio.to_thread(config.index.remove_datapoints, datapoint_ids=ids)


def _default_embedder() -> Embedder:
    import vertexai  # lazy import
    from vertexai.language_models import TextEmbeddingModel

    vertexai.init(
        project=os.environ["GCP_PROJECT_ID"],
        location=os.environ.get("GCP_REGION", "asia-northeast1"),
    )
    model = TextEmbeddingModel.from_pretrained(
        os.environ.get("VERTEX_EMBEDDING_MODEL", "text-embedding-004")
    )

    class _VertexEmbedder:
        def embed(self, text: str) -> list[float]:
            return list(model.get_embeddings([text])[0].values)

    return _VertexEmbedder()


def get_adapter() -> GCPVectorDBAdapter:
    from google.cloud import aiplatform  # lazy import

    aiplatform.init(
        project=os.environ["GCP_PROJECT_ID"],
        location=os.environ.get("GCP_REGION", "asia-northeast1"),
    )
    endpoint = aiplatform.MatchingEngineIndexEndpoint(
        index_endpoint_name=os.environ["VERTEX_INDEX_ENDPOINT_ID"]
    )

    indexes: dict[str, VertexIndexConfig] = {}
    zone_to_env = {"zone2": "VERTEX_INDEX_ID_ZONE2", "zone3": "VERTEX_INDEX_ID_ZONE3"}
    for logical, env in zone_to_env.items():
        index_id = os.environ.get(env)
        if not index_id:
            continue
        indexes[logical] = VertexIndexConfig(
            index=aiplatform.MatchingEngineIndex(index_name=index_id),
            endpoint=endpoint,
            deployed_index_id=os.environ.get(
                f"VERTEX_DEPLOYED_INDEX_ID_{logical.upper()}", logical
            ),
        )
    return GCPVectorDBAdapter(indexes, _default_embedder())
