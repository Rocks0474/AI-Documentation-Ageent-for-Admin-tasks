"""AWS AuditLogAdapter — S3 (queryable state) + CloudWatch Logs (immutable WORM).

The S3 audit bucket holds the queryable, versioned trail (one JSON object per
entry plus a per-request marker), backing get/query/record_approval the same way
the GCP adapter uses GCS. Every appended event is *also* mirrored to a CloudWatch
Logs stream when configured — an append-only, immutable group (queryable via
Athena / Logs Insights) that satisfies the WORM compliance requirement. The S3
object is rewritten on approval (bucket versioning retains all prior versions);
CloudWatch Logs is never mutated.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Optional

from adapters.base.audit_log import AuditEntry, AuditLogAdapter


class AWSAuditLogAdapter(AuditLogAdapter):
    def __init__(
        self,
        s3_client,
        bucket_name: str,
        logs_client=None,
        log_group: Optional[str] = None,
        log_stream: Optional[str] = None,
    ) -> None:
        self._s3 = s3_client
        self._bucket = bucket_name
        self._logs = logs_client
        self._log_group = log_group
        self._log_stream = log_stream

    @staticmethod
    def _entry_key(entry_id: str) -> str:
        return f"entries/{entry_id}.json"

    @staticmethod
    def _marker_key(request_id: str, entry_id: str) -> str:
        return f"by_request/{request_id}/{entry_id}.json"

    def _emit_to_logs(self, entry: AuditEntry) -> None:
        if not (self._logs and self._log_group and self._log_stream):
            return
        self._logs.put_log_events(
            logGroupName=self._log_group,
            logStreamName=self._log_stream,
            logEvents=[
                {
                    "timestamp": int(entry.timestamp.timestamp() * 1000),
                    "message": entry.model_dump_json(),
                }
            ],
        )

    async def append(self, entry: AuditEntry) -> str:
        payload = entry.model_dump_json().encode("utf-8")

        def _write() -> None:
            self._s3.put_object(
                Bucket=self._bucket,
                Key=self._entry_key(entry.entry_id),
                Body=payload,
                ContentType="application/json",
            )
            if entry.request_id:
                self._s3.put_object(
                    Bucket=self._bucket,
                    Key=self._marker_key(entry.request_id, entry.entry_id),
                    Body=b"",
                    ContentType="application/json",
                )
            self._emit_to_logs(entry)

        await asyncio.to_thread(_write)
        return entry.entry_id

    async def get(self, entry_id: str) -> Optional[AuditEntry]:
        def _get() -> Optional[AuditEntry]:
            try:
                response = self._s3.get_object(
                    Bucket=self._bucket, Key=self._entry_key(entry_id)
                )
            except Exception as exc:  # noqa: BLE001 - missing => None
                from adapters.aws._errors import is_not_found

                if is_not_found(exc):
                    return None
                raise
            return AuditEntry.model_validate_json(response["Body"].read())

        return await asyncio.to_thread(_get)

    async def query(self, request_id: str) -> list[AuditEntry]:
        def _query() -> list[AuditEntry]:
            prefix = f"by_request/{request_id}/"
            entry_ids: list[str] = []
            token: Optional[str] = None
            while True:
                kwargs = {"Bucket": self._bucket, "Prefix": prefix}
                if token:
                    kwargs["ContinuationToken"] = token
                response = self._s3.list_objects_v2(**kwargs)
                for obj in response.get("Contents", []):
                    entry_ids.append(obj["Key"].rsplit("/", 1)[-1][: -len(".json")])
                if not response.get("IsTruncated"):
                    break
                token = response.get("NextContinuationToken")

            entries: list[AuditEntry] = []
            for entry_id in entry_ids:
                obj = self._s3.get_object(
                    Bucket=self._bucket, Key=self._entry_key(entry_id)
                )
                entries.append(AuditEntry.model_validate_json(obj["Body"].read()))
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
            from adapters.aws._errors import is_not_found

            try:
                response = self._s3.get_object(
                    Bucket=self._bucket, Key=self._entry_key(entry_id)
                )
            except Exception as exc:  # noqa: BLE001 - missing => KeyError
                if is_not_found(exc):
                    raise KeyError(entry_id) from exc
                raise
            entry = AuditEntry.model_validate_json(response["Body"].read())
            updated = entry.model_copy(
                update={
                    "approver_id": approver_id,
                    "approved_at": approved_at or datetime.now(timezone.utc),
                }
            )
            self._s3.put_object(
                Bucket=self._bucket,
                Key=self._entry_key(entry_id),
                Body=updated.model_dump_json().encode("utf-8"),
                ContentType="application/json",
            )
            # The approval is also recorded as a new immutable log event.
            self._emit_to_logs(updated)
            return updated

        return await asyncio.to_thread(_record)


def get_adapter() -> AWSAuditLogAdapter:
    import boto3  # lazy import

    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    s3_client = boto3.client("s3", region_name=region)
    bucket = os.environ["S3_BUCKET_AUDIT"]

    log_group = os.environ.get("CLOUDWATCH_AUDIT_LOG_GROUP")
    log_stream = os.environ.get("CLOUDWATCH_AUDIT_LOG_STREAM")
    logs_client = (
        boto3.client("logs", region_name=region) if log_group and log_stream else None
    )
    return AWSAuditLogAdapter(s3_client, bucket, logs_client, log_group, log_stream)
