"""GCP AuditLogAdapter — append-only audit trail on a GCS audit bucket.

Each entry is stored as a JSON object at ``entries/{entry_id}.json`` with a
per-request marker at ``by_request/{request_id}/{entry_id}.json`` so a request's
trail can be listed efficiently. The audit bucket is configured with object
versioning (see Terraform), so ``record_approval`` re-writes the entry as a new
version while every prior version is retained — append-only history with a
mutable-looking surface for the approval provenance (Constraint #5).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Optional

from adapters.base.audit_log import AuditEntry, AuditLogAdapter


class GCPAuditLogAdapter(AuditLogAdapter):
    def __init__(self, client, bucket_name: str) -> None:
        self._client = client
        self._bucket_name = bucket_name

    def _bucket(self):
        return self._client.bucket(self._bucket_name)

    @staticmethod
    def _entry_key(entry_id: str) -> str:
        return f"entries/{entry_id}.json"

    @staticmethod
    def _marker_key(request_id: str, entry_id: str) -> str:
        return f"by_request/{request_id}/{entry_id}.json"

    async def append(self, entry: AuditEntry) -> str:
        payload = entry.model_dump_json().encode("utf-8")

        def _write() -> None:
            bucket = self._bucket()
            bucket.blob(self._entry_key(entry.entry_id)).upload_from_string(
                payload, content_type="application/json"
            )
            if entry.request_id:
                bucket.blob(
                    self._marker_key(entry.request_id, entry.entry_id)
                ).upload_from_string(b"", content_type="application/json")

        await asyncio.to_thread(_write)
        return entry.entry_id

    async def get(self, entry_id: str) -> Optional[AuditEntry]:
        def _read() -> Optional[AuditEntry]:
            blob = self._bucket().blob(self._entry_key(entry_id))
            if not blob.exists():
                return None
            return AuditEntry.model_validate_json(blob.download_as_bytes())

        return await asyncio.to_thread(_read)

    async def query(self, request_id: str) -> list[AuditEntry]:
        def _query() -> list[AuditEntry]:
            bucket = self._bucket()
            prefix = f"by_request/{request_id}/"
            entry_ids = [
                blob.name.rsplit("/", 1)[-1][: -len(".json")]
                for blob in self._client.list_blobs(self._bucket_name, prefix=prefix)
            ]
            entries: list[AuditEntry] = []
            for entry_id in entry_ids:
                blob = bucket.blob(self._entry_key(entry_id))
                if blob.exists():
                    entries.append(
                        AuditEntry.model_validate_json(blob.download_as_bytes())
                    )
            entries.sort(key=lambda e: (e.timestamp, e.entry_id))
            return entries

        return await asyncio.to_thread(_query)

    async def record_approval(
        self,
        entry_id: str,
        approver_id: str,
        approved_at: Optional[datetime] = None,
    ) -> AuditEntry:
        def _record() -> AuditEntry:
            blob = self._bucket().blob(self._entry_key(entry_id))
            if not blob.exists():
                raise KeyError(entry_id)
            entry = AuditEntry.model_validate_json(blob.download_as_bytes())
            updated = entry.model_copy(
                update={
                    "approver_id": approver_id,
                    "approved_at": approved_at or datetime.now(timezone.utc),
                }
            )
            blob.upload_from_string(
                updated.model_dump_json().encode("utf-8"),
                content_type="application/json",
            )
            return updated

        return await asyncio.to_thread(_record)


def get_adapter() -> GCPAuditLogAdapter:
    from google.cloud import storage  # lazy import

    client = storage.Client()
    bucket_name = os.environ["GCS_BUCKET_AUDIT"]
    return GCPAuditLogAdapter(client, bucket_name)
