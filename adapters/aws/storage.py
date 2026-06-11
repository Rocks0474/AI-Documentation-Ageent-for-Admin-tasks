"""AWS StorageAdapter — Amazon S3, partitioned by data zone."""

from __future__ import annotations

import asyncio
import os
from typing import Optional

from adapters.aws._errors import is_not_found
from adapters.base.storage import DataZone, StorageAdapter

_ENV_FOR_ZONE: dict[DataZone, str] = {
    DataZone.ZONE2: "S3_BUCKET_ZONE2",
    DataZone.ZONE3: "S3_BUCKET_ZONE3",
    DataZone.AUDIT: "S3_BUCKET_AUDIT",
}


class AWSStorageAdapter(StorageAdapter):
    def __init__(self, client, buckets: dict[DataZone, str]) -> None:
        self._client = client
        self._buckets = buckets

    def _bucket(self, zone: DataZone) -> str:
        name = self._buckets.get(zone)
        if not name:
            raise ValueError(f"No S3 bucket configured for zone {zone.value}")
        return name

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
            self._client.put_object(
                Bucket=self._bucket(zone),
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata=metadata or {},
            )

        await asyncio.to_thread(_put)
        return key

    async def get(self, key: str, zone: DataZone) -> bytes:
        def _get() -> bytes:
            try:
                response = self._client.get_object(Bucket=self._bucket(zone), Key=key)
            except Exception as exc:  # noqa: BLE001 - mapped to KeyError below
                if is_not_found(exc):
                    raise KeyError(key) from exc
                raise
            return response["Body"].read()

        return await asyncio.to_thread(_get)

    async def exists(self, key: str, zone: DataZone) -> bool:
        def _exists() -> bool:
            try:
                self._client.head_object(Bucket=self._bucket(zone), Key=key)
            except Exception as exc:  # noqa: BLE001 - not-found => False
                if is_not_found(exc):
                    return False
                raise
            return True

        return await asyncio.to_thread(_exists)

    async def delete(self, key: str, zone: DataZone) -> None:
        await asyncio.to_thread(
            lambda: self._client.delete_object(Bucket=self._bucket(zone), Key=key)
        )

    async def list(self, prefix: str, zone: DataZone) -> list[str]:
        def _list() -> list[str]:
            keys: list[str] = []
            token: Optional[str] = None
            while True:
                kwargs = {"Bucket": self._bucket(zone), "Prefix": prefix}
                if token:
                    kwargs["ContinuationToken"] = token
                response = self._client.list_objects_v2(**kwargs)
                keys.extend(obj["Key"] for obj in response.get("Contents", []))
                if not response.get("IsTruncated"):
                    break
                token = response.get("NextContinuationToken")
            return sorted(keys)

        return await asyncio.to_thread(_list)


def get_adapter() -> AWSStorageAdapter:
    import boto3  # lazy import — AWS SDK only loaded here

    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    client = boto3.client("s3", region_name=region)
    buckets = {
        zone: os.environ[env]
        for zone, env in _ENV_FOR_ZONE.items()
        if os.environ.get(env)
    }
    return AWSStorageAdapter(client, buckets)
