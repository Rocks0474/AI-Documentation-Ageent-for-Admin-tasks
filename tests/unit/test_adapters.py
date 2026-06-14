"""Unit tests for the LOCAL adapters and the CLOUD_TARGET factory."""

from __future__ import annotations

import pytest

from adapters import factory
from adapters.base.audit_log import (
    AuditEntry,
    AuditLogAdapter,
)
from adapters.base.notification import (
    Notification,
    NotificationAdapter,
    NotificationChannel,
)
from adapters.base.queue import QueueAdapter
from adapters.base.scheduler import ScheduledJob, SchedulerAdapter
from adapters.base.secrets import SecretNotFoundError, SecretsAdapter
from adapters.base.storage import DataZone, StorageAdapter
from adapters.base.vector_db import (
    VectorDBAdapter,
    VectorDocument,
)
from adapters.local.audit_log import LocalAuditLogAdapter
from adapters.local.notification import LocalNotificationAdapter
from adapters.local.queue import LocalQueueAdapter
from adapters.local.scheduler import LocalSchedulerAdapter
from adapters.local.secrets import LocalSecretsAdapter
from adapters.local.storage import LocalStorageAdapter
from adapters.local.vector_db import LocalVectorDBAdapter

# ---------------------------------------------------------------------------
# Factory — Constraint #6
# ---------------------------------------------------------------------------

def test_factory_defaults_to_local(monkeypatch):
    monkeypatch.delenv("CLOUD_TARGET", raising=False)
    assert factory.cloud_target() == "LOCAL"


def test_factory_validates_cloud_target(monkeypatch):
    monkeypatch.setenv("CLOUD_TARGET", "AZURE")
    with pytest.raises(ValueError, match="Invalid CLOUD_TARGET"):
        factory.cloud_target()


def test_factory_instantiates_local_adapters(monkeypatch):
    monkeypatch.setenv("CLOUD_TARGET", "LOCAL")
    factory.reset_factory()
    try:
        assert isinstance(factory.get_storage(), StorageAdapter)
        assert isinstance(factory.get_queue(), QueueAdapter)
        assert isinstance(factory.get_secrets(), SecretsAdapter)
        assert isinstance(factory.get_audit_log(), AuditLogAdapter)
        assert isinstance(factory.get_scheduler(), SchedulerAdapter)
        assert isinstance(factory.get_notification(), NotificationAdapter)
        assert isinstance(factory.get_vector_db(), VectorDBAdapter)
        # Cached: same instance across calls.
        assert factory.get_storage() is factory.get_storage()
    finally:
        factory.reset_factory()


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

async def test_storage_roundtrip(tmp_path):
    storage = LocalStorageAdapter(root=str(tmp_path))
    await storage.put("reports/r1.txt", b"hello", DataZone.ZONE3)
    assert await storage.exists("reports/r1.txt", DataZone.ZONE3)
    assert await storage.get("reports/r1.txt", DataZone.ZONE3) == b"hello"
    assert "reports/r1.txt" in await storage.list("reports/", DataZone.ZONE3)
    await storage.delete("reports/r1.txt", DataZone.ZONE3)
    assert not await storage.exists("reports/r1.txt", DataZone.ZONE3)


async def test_storage_missing_key_raises(tmp_path):
    storage = LocalStorageAdapter(root=str(tmp_path))
    with pytest.raises(KeyError):
        await storage.get("nope", DataZone.ZONE2)


async def test_storage_blocks_path_traversal(tmp_path):
    storage = LocalStorageAdapter(root=str(tmp_path))
    with pytest.raises(ValueError, match="traversal"):
        await storage.put("../escape", b"x", DataZone.ZONE2)


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

async def test_queue_publish_pull_ack():
    queue = LocalQueueAdapter()
    mid = await queue.publish("routing", {"k": "v"}, attributes={"a": "b"})
    messages = await queue.pull("routing", max_messages=5)
    assert len(messages) == 1
    assert messages[0].message_id == mid
    assert messages[0].body == {"k": "v"}
    assert messages[0].attributes == {"a": "b"}
    await queue.ack("routing", mid)
    # Drained.
    assert await queue.pull("routing") == []


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

async def test_secrets_from_file(tmp_path):
    secrets_file = tmp_path / "secrets.local.json"
    secrets_file.write_text('{"hris-api-key": "abc123"}', encoding="utf-8")
    secrets = LocalSecretsAdapter(path=str(secrets_file))
    assert await secrets.exists("hris-api-key")
    assert await secrets.get_secret("hris-api-key") == "abc123"


async def test_secrets_missing_raises(tmp_path):
    secrets = LocalSecretsAdapter(path=str(tmp_path / "absent.json"))
    with pytest.raises(SecretNotFoundError):
        await secrets.get_secret("nope")


async def test_secrets_env_fallback(tmp_path, monkeypatch):
    secrets = LocalSecretsAdapter(path=str(tmp_path / "absent.json"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert await secrets.get_secret("ANTHROPIC_API_KEY") == "sk-test"


# ---------------------------------------------------------------------------
# Audit log — Constraints #3 and #5
# ---------------------------------------------------------------------------

async def test_audit_append_and_query():
    audit = LocalAuditLogAdapter()
    eid = await audit.append(
        AuditEntry(event_type="REQUEST_RECEIVED", request_id="req-1")
    )
    assert eid
    fetched = await audit.get(eid)
    assert fetched is not None and fetched.event_type == "REQUEST_RECEIVED"
    assert [e.event_type for e in await audit.query("req-1")] == ["REQUEST_RECEIVED"]


async def test_audit_approval_provenance_set_only_via_record_approval():
    audit = LocalAuditLogAdapter()
    eid = await audit.append(
        AuditEntry(event_type="RESPONSE_GENERATED", request_id="req-2")
    )
    # Agents never set these; they start empty.
    assert (await audit.get(eid)).approver_id is None
    updated = await audit.record_approval(eid, approver_id="chro@corp")
    assert updated.approver_id == "chro@corp"
    assert updated.approved_at is not None


# ---------------------------------------------------------------------------
# Scheduler — seeds the Japan statutory calendar shape
# ---------------------------------------------------------------------------

async def test_scheduler_create_list_delete():
    scheduler = LocalSchedulerAdapter()
    job = ScheduledJob(
        job_id="jp_santei_kiso_todoke",
        cron_expression="0 9 1 7 *",
        target_topic="statutory-filing-alerts",
        payload={"filing_type": "算定基礎届", "deadline_days": 10},
    )
    await scheduler.create_job(job)
    jobs = await scheduler.list_jobs()
    assert [j.job_id for j in jobs] == ["jp_santei_kiso_todoke"]
    await scheduler.delete_job("jp_santei_kiso_todoke")
    assert await scheduler.list_jobs() == []


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------

async def test_notification_records_sent():
    notifier = LocalNotificationAdapter()
    mid = await notifier.send(
        Notification(
            channel=NotificationChannel.SLACK,
            recipient="#hr-hitl",
            subject="HITL",
            body="review",
            priority="critical",
            request_id="req-3",
        )
    )
    assert mid
    assert len(notifier.sent) == 1
    assert notifier.sent[0].recipient == "#hr-hitl"


# ---------------------------------------------------------------------------
# Vector DB
# ---------------------------------------------------------------------------

async def test_vector_db_upsert_and_query():
    vdb = LocalVectorDBAdapter()
    count = await vdb.upsert(
        "zone3",
        [
            VectorDocument(id="d1", content="remote work policy guidance"),
            VectorDocument(id="d2", content="overtime 36 agreement statute"),
        ],
    )
    assert count == 2
    results = await vdb.query("zone3", "remote work policy", top_k=1)
    assert results[0].id == "d1"
    assert results[0].score > 0
    await vdb.delete("zone3", ["d1"])
    assert all(r.id != "d1" for r in await vdb.query("zone3", "remote", top_k=5))
