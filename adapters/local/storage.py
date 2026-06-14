"""LOCAL StorageAdapter — local filesystem, partitioned by data zone.

Objects live under ``LOCAL_STORAGE_ROOT`` (default ``./local_storage``) in a
subdirectory per :class:`DataZone`. Zone 1 (PII) is not representable, so it is
never written here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from adapters.base.storage import DataZone, StorageAdapter


class LocalStorageAdapter(StorageAdapter):
    def __init__(self, root: Optional[str] = None) -> None:
        self._root = Path(
            root or os.environ.get("LOCAL_STORAGE_ROOT", "./local_storage")
        )

    def _zone_root(self, zone: DataZone) -> Path:
        return (self._root / zone.value).resolve()

    def _path(self, key: str, zone: DataZone) -> Path:
        base = self._zone_root(zone)
        target = (base / key).resolve()
        if base != target and base not in target.parents:
            raise ValueError(f"Refusing path traversal outside zone: {key!r}")
        return target

    async def put(
        self,
        key: str,
        data: bytes,
        zone: DataZone,
        *,
        content_type: str = "application/octet-stream",
        metadata: Optional[dict[str, str]] = None,
    ) -> str:
        path = self._path(key, zone)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    async def get(self, key: str, zone: DataZone) -> bytes:
        path = self._path(key, zone)
        if not path.is_file():
            raise KeyError(key)
        return path.read_bytes()

    async def exists(self, key: str, zone: DataZone) -> bool:
        return self._path(key, zone).is_file()

    async def delete(self, key: str, zone: DataZone) -> None:
        self._path(key, zone).unlink(missing_ok=True)

    async def list(self, prefix: str, zone: DataZone) -> list[str]:
        base = self._zone_root(zone)
        if not base.exists():
            return []
        keys = [
            str(p.relative_to(base))
            for p in base.rglob("*")
            if p.is_file()
        ]
        return sorted(k for k in keys if k.startswith(prefix))


_adapter: Optional[LocalStorageAdapter] = None


def get_adapter() -> LocalStorageAdapter:
    global _adapter
    if _adapter is None:
        _adapter = LocalStorageAdapter()
    return _adapter
