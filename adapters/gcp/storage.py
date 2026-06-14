"""GCP StorageAdapter — Google Cloud Storage, partitioned by data zone.

Each :class:`DataZone` maps to a GCS bucket (``GCS_BUCKET_ZONE2`` /
``GCS_BUCKET_ZONE3`` / ``GCS_BUCKET_AUDIT``). Zone 1 (PII) is not representable.
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

from adapters.base.storage import DataZone, StorageAdapter

_ENV_FOR_ZONE: dict[DataZone, str] = {
    DataZone.ZONE2: "GCS_BUCKET_ZONE2",
    DataZone.ZONE3: "GCS_BUCKET_ZONE3",
    DataZone.AUDIT: "GCS_BUCKET_AUDIT",
}


class GCPStorageAdapter(StorageAdapter):
    def __init__(self, client, buckets: dict[DataZone, str]) -> None:
        # `client` is a google.cloud.storage.Client (duck-typed for testing).
        self._client = client
        self._buckets = buckets

    def _bucket_name(self, zone: DataZone) -> str:
        name = self._buckets.get(zone)
        if not name:
            raise ValueError(f"No GCS bucket configured for zone {zone.value}")
        return name

    def _blob(self, key: str, zone: DataZone):
        return self._client.bucket(self._bucket_name(zone)).blob(key)

    async def put(
        self,
        key: str,
        data: bytes,
        zone: DataZone,
        *,
        content_type: str = "application/octet-stream",
        metadata: Optional[dict[str, str]] = None,
    ) -> str:
        def _put() -> None:
            blob = self._blob(key, zone)
            if metadata:
                blob.metadata = metadata
            blob.upload_from_string(data, content_type=content_type)

        await asyncio.to_thread(_put)
        return key

    async def get(self, key: str, zone: DataZone) -> bytes:
        def _get() -> bytes:
            blob = self._blob(key, zone)
            if not blob.exists():
                raise KeyError(key)
            return blob.download_as_bytes()

        return await asyncio.to_thread(_get)

    async def exists(self, key: str, zone: DataZone) -> bool:
        return await asyncio.to_thread(lambda: self._blob(key, zone).exists())

    async def delete(self, key: str, zone: DataZone) -> None:
        def _delete() -> None:
            blob = self._blob(key, zone)
            if blob.exists():
                blob.delete()

        await asyncio.to_thread(_delete)

    async def list(self, prefix: str, zone: DataZone) -> list[str]:
        def _list() -> list[str]:
            blobs = self._client.list_blobs(self._bucket_name(zone), prefix=prefix)
            return sorted(b.name for b in blobs)

        return await asyncio.to_thread(_list)


def get_adapter() -> GCPStorageAdapter:
    from google.cloud import storage  # lazy import — GCP SDK only loaded here

    client = storage.Client()
    buckets = {
        zone: os.environ[env]
        for zone, env in _ENV_FOR_ZONE.items()
        if os.environ.get(env)
    }
    return GCPStorageAdapter(client, buckets)
