"""AWS VectorDBAdapter — Amazon OpenSearch Serverless (k-NN).

Each logical index name maps to an OpenSearch index that stores the document
content, metadata, and a knn_vector field. Text is embedded via Amazon Bedrock
(Titan embeddings) by default. Unlike Vertex, OpenSearch stores the document
content, so query results carry it back.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Optional, Protocol

from adapters.base.vector_db import (
    VectorDBAdapter,
    VectorDocument,
    VectorQueryResult,
)


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class AWSVectorDBAdapter(VectorDBAdapter):
    def __init__(
        self,
        client,
        embedder: Embedder,
        index_map: Optional[dict[str, str]] = None,
    ) -> None:
        # `client` is an opensearchpy.OpenSearch instance (duck-typed).
        self._client = client
        self._embedder = embedder
        self._index_map = index_map or {"zone2": "zone2", "zone3": "zone3"}

    def _index(self, index: str) -> str:
        name = self._index_map.get(index)
        if not name:
            raise ValueError(f"No OpenSearch index configured for {index!r}")
        return name

    async def upsert(self, index: str, documents: list[VectorDocument]) -> int:
        name = self._index(index)

        def _upsert() -> int:
            for doc in documents:
                vector = doc.embedding or self._embedder.embed(doc.content)
                self._client.index(
                    index=name,
                    id=doc.id,
                    body={
                        "content": doc.content,
                        "metadata": doc.metadata,
                        "vector": list(vector),
                    },
                )
            return len(documents)

        return await asyncio.to_thread(_upsert)

    async def query(
        self,
        index: str,
        query_text: str,
        top_k: int = 5,
        *,
        filter: Optional[dict] = None,
    ) -> list[VectorQueryResult]:
        name = self._index(index)

        def _query():
            vector = self._embedder.embed(query_text)
            body = {
                "size": top_k,
                "query": {"knn": {"vector": {"vector": list(vector), "k": top_k}}},
            }
            if filter:
                body["query"] = {
                    "bool": {
                        "must": [body["query"]],
                        "filter": [
                            {"term": {f"metadata.{k}": v}} for k, v in filter.items()
                        ],
                    }
                }
            return self._client.search(index=name, body=body)

        response = await asyncio.to_thread(_query)
        results: list[VectorQueryResult] = []
        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            results.append(
                VectorQueryResult(
                    id=hit["_id"],
                    score=float(hit.get("_score", 0.0)),
                    content=source.get("content", ""),
                    metadata=source.get("metadata", {}),
                )
            )
        return results

    async def delete(self, index: str, ids: list[str]) -> None:
        name = self._index(index)

        def _delete() -> None:
            for doc_id in ids:
                self._client.delete(index=name, id=doc_id, ignore=[404])

        await asyncio.to_thread(_delete)


def _default_embedder() -> Embedder:
    import boto3  # lazy import

    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    model_id = os.environ.get("BEDROCK_EMBEDDING_MODEL", "amazon.titan-embed-text-v2:0")
    runtime = boto3.client("bedrock-runtime", region_name=region)

    class _BedrockEmbedder:
        def embed(self, text: str) -> list[float]:
            response = runtime.invoke_model(
                modelId=model_id,
                body=json.dumps({"inputText": text}),
                contentType="application/json",
                accept="application/json",
            )
            return json.loads(response["body"].read())["embedding"]

    return _BedrockEmbedder()


def _build_opensearch_client():
    import boto3  # lazy import
    from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    host = os.environ["OPENSEARCH_ENDPOINT_ZONE2"].replace("https://", "")
    credentials = boto3.Session().get_credentials()
    auth = AWSV4SignerAuth(credentials, region, "aoss")
    return OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
    )


def get_adapter() -> AWSVectorDBAdapter:
    client = _build_opensearch_client()
    return AWSVectorDBAdapter(client, _default_embedder())
