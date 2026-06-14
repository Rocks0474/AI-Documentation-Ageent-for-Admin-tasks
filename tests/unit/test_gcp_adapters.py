"""Unit tests for the GCP adapters — google.cloud.* calls are mocked.

No live GCP calls and no GCP SDK installed: the adapter classes are exercised
against in-memory fakes that mimic the relevant client surfaces. Also verifies
the factory dispatches to the GCP package when CLOUD_TARGET=GCP.
"""

from __future__ import annotations

import json

import pytest

from adapters.base.audit_log import AuditEntry
from adapters.base.notification import Notification, NotificationChannel
from adapters.base.scheduler import ScheduledJob
from adapters.base.secrets import SecretNotFoundError
from adapters.base.storage import DataZone
from adapters.base.vector_db import VectorDocument
from adapters.gcp.audit_log import GCPAuditLogAdapter
from adapters.gcp.notification import GCPNotificationAdapter
from adapters.gcp.queue import GCPQueueAdapter
from adapters.gcp.scheduler import GCPSchedulerAdapter
from adapters.gcp.secrets import GCPSecretsAdapter
from adapters.gcp.storage import GCPStorageAdapter
from adapters.gcp.vector_db import GCPVectorDBAdapter, VertexIndexConfig

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeBlob:
    def __init__(self, store, key):
        self._store = store
        self._key = key
        self.metadata = None

    def upload_from_string(self, data, content_type=None):
        self._store[self._key] = data if isinstance(data, (bytes, bytearray)) else data.encode()

    def download_as_bytes(self):
        return self._store[self._key]

    def exists(self):
        return self._key in self._store

    def delete(self):
        self._store.pop(self._key, None)


class _FakeBucket:
    def __init__(self, store):
        self._store = store

    def blob(self, key):
        return _FakeBlob(self._store, key)


class _FakeGCSClient:
    def __init__(self):
        self.buckets: dict[str, dict] = {}

    def _store(self, name):
        return self.buckets.setdefault(name, {})

    def bucket(self, name):
        return _FakeBucket(self._store(name))

    def list_blobs(self, name, prefix=""):
        return [
            type("B", (), {"name": k})()
            for k in self._store(name)
            if k.startswith(prefix)
        ]


class _FakeFuture:
    def __init__(self, mid):
        self._mid = mid

    def result(self):
        return self._mid


class _FakePublisher:
    def __init__(self):
        self.published = []

    def topic_path(self, project, topic):
        return f"projects/{project}/topics/{topic}"

    def publish(self, path, data, **attrs):
        self.published.append((path, data, attrs))
        return _FakeFuture("mid-1")


class _FakeReceived:
    def __init__(self, mid, data, attrs, ack_id):
        self.ack_id = ack_id
        self.message = type(
            "M", (), {"message_id": mid, "data": data, "attributes": attrs}
        )()


class _FakeSubscriber:
    def __init__(self, queued=None):
        self.queued = list(queued or [])
        self.acked: list[str] = []

    def subscription_path(self, project, sub):
        return f"projects/{project}/subscriptions/{sub}"

    def pull(self, request):
        n = request["max_messages"]
        take, self.queued = self.queued[:n], self.queued[n:]
        return type("R", (), {"received_messages": take})()

    def acknowledge(self, request):
        self.acked.extend(request["ack_ids"])


class NotFound(Exception):
    pass


class AlreadyExists(Exception):
    pass


class _FakeSecretClient:
    def __init__(self, secrets):
        self._secrets = secrets

    def access_secret_version(self, name):
        secret = name.split("/secrets/")[1].split("/")[0]
        if secret not in self._secrets:
            raise NotFound(secret)
        return type(
            "R", (), {"payload": type("P", (), {"data": self._secrets[secret].encode()})()}
        )()


class _FakeSchedulerClient:
    def __init__(self):
        self.jobs: dict[str, dict] = {}

    def create_job(self, parent, job):
        if job["name"] in self.jobs:
            raise AlreadyExists()
        self.jobs[job["name"]] = job

    def update_job(self, job):
        self.jobs[job["name"]] = job

    def delete_job(self, name):
        if name not in self.jobs:
            raise NotFound()
        del self.jobs[name]

    def list_jobs(self, parent):
        out = []
        for name, job in self.jobs.items():
            pt = job["pubsub_target"]
            target = type("T", (), {"topic_name": pt["topic_name"], "data": pt["data"]})()
            out.append(
                type(
                    "J",
                    (),
                    {
                        "name": name,
                        "schedule": job["schedule"],
                        "time_zone": job["time_zone"],
                        "pubsub_target": target,
                    },
                )()
            )
        return out


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _storage():
    return GCPStorageAdapter(
        _FakeGCSClient(),
        {DataZone.ZONE2: "bkt-z2", DataZone.ZONE3: "bkt-z3", DataZone.AUDIT: "bkt-audit"},
    )


async def test_gcp_storage_roundtrip():
    storage = _storage()
    await storage.put("a/b.txt", b"hi", DataZone.ZONE2)
    assert await storage.exists("a/b.txt", DataZone.ZONE2)
    assert await storage.get("a/b.txt", DataZone.ZONE2) == b"hi"
    assert await storage.list("a/", DataZone.ZONE2) == ["a/b.txt"]
    await storage.delete("a/b.txt", DataZone.ZONE2)
    assert not await storage.exists("a/b.txt", DataZone.ZONE2)


async def test_gcp_storage_get_missing_raises():
    storage = _storage()
    with pytest.raises(KeyError):
        await storage.get("nope", DataZone.ZONE3)


async def test_gcp_storage_unconfigured_zone_raises():
    storage = GCPStorageAdapter(_FakeGCSClient(), {DataZone.ZONE2: "bkt-z2"})
    with pytest.raises(ValueError, match="No GCS bucket"):
        await storage.put("k", b"x", DataZone.AUDIT)


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

async def test_gcp_queue_publish():
    pub = _FakePublisher()
    queue = GCPQueueAdapter(pub, _FakeSubscriber(), project_id="proj")
    mid = await queue.publish("routing", {"k": "v"}, attributes={"a": "b"})
    assert mid == "mid-1"
    path, data, attrs = pub.published[0]
    assert path == "projects/proj/topics/routing"
    assert json.loads(data) == {"k": "v"}
    assert attrs == {"a": "b"}


async def test_gcp_queue_pull_and_ack():
    received = _FakeReceived("m1", json.dumps({"x": 1}).encode(), {"a": "b"}, "ack-1")
    sub = _FakeSubscriber([received])
    queue = GCPQueueAdapter(_FakePublisher(), sub, project_id="proj")
    messages = await queue.pull("routing", max_messages=5)
    assert len(messages) == 1
    assert messages[0].body == {"x": 1}
    await queue.ack("routing", "m1")
    assert sub.acked == ["ack-1"]


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

async def test_gcp_secrets_get_and_exists():
    secrets = GCPSecretsAdapter(_FakeSecretClient({"hris-api-key": "v"}), "proj")
    assert await secrets.get_secret("hris-api-key") == "v"
    assert await secrets.exists("hris-api-key") is True


async def test_gcp_secrets_missing_raises():
    secrets = GCPSecretsAdapter(_FakeSecretClient({}), "proj")
    with pytest.raises(SecretNotFoundError):
        await secrets.get_secret("absent")
    assert await secrets.exists("absent") is False


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

async def test_gcp_audit_append_query_and_approval():
    audit = GCPAuditLogAdapter(_FakeGCSClient(), "bkt-audit")
    eid = await audit.append(
        AuditEntry(event_type="REQUEST_RECEIVED", request_id="r1")
    )
    fetched = await audit.get(eid)
    assert fetched is not None and fetched.event_type == "REQUEST_RECEIVED"
    assert [e.event_type for e in await audit.query("r1")] == ["REQUEST_RECEIVED"]

    updated = await audit.record_approval(eid, approver_id="chro@corp")
    assert updated.approver_id == "chro@corp"
    assert (await audit.get(eid)).approver_id == "chro@corp"


async def test_gcp_audit_record_approval_missing_raises():
    audit = GCPAuditLogAdapter(_FakeGCSClient(), "bkt-audit")
    with pytest.raises(KeyError):
        await audit.record_approval("nope", approver_id="x")


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def _job():
    return ScheduledJob(
        job_id="jp_santei_kiso_todoke",
        cron_expression="0 9 1 7 *",
        target_topic="statutory-filing-alerts",
        payload={"filing_type": "算定基礎届", "deadline_days": 10},
    )


async def test_gcp_scheduler_create_list_delete():
    scheduler = GCPSchedulerAdapter(_FakeSchedulerClient(), "proj", "asia-northeast1")
    await scheduler.create_job(_job())
    jobs = await scheduler.list_jobs()
    assert [j.job_id for j in jobs] == ["jp_santei_kiso_todoke"]
    assert jobs[0].target_topic == "statutory-filing-alerts"
    assert jobs[0].payload == {"filing_type": "算定基礎届", "deadline_days": 10}
    await scheduler.delete_job("jp_santei_kiso_todoke")
    assert await scheduler.list_jobs() == []


async def test_gcp_scheduler_create_is_idempotent():
    scheduler = GCPSchedulerAdapter(_FakeSchedulerClient(), "proj", "asia-northeast1")
    await scheduler.create_job(_job())
    # Second create triggers AlreadyExists -> update_job, no error.
    await scheduler.create_job(_job())
    assert len(await scheduler.list_jobs()) == 1


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------

async def test_gcp_notification_publishes():
    pub = _FakePublisher()
    notifier = GCPNotificationAdapter(pub, "proj", topic="hr-notifications")
    mid = await notifier.send(
        Notification(
            channel=NotificationChannel.SLACK,
            recipient="#hr",
            subject="HITL",
            body="review",
            priority="critical",
            request_id="r1",
        )
    )
    assert mid == "mid-1"
    path, _, attrs = pub.published[0]
    assert path == "projects/proj/topics/hr-notifications"
    assert attrs["channel"] == "SLACK" and attrs["priority"] == "critical"


# ---------------------------------------------------------------------------
# Vector DB
# ---------------------------------------------------------------------------

class _FakeEmbedder:
    def embed(self, text):
        return [float(len(text)), 1.0]


class _FakeIndex:
    def __init__(self):
        self.upserted = []
        self.removed = []

    def upsert_datapoints(self, datapoints):
        self.upserted.extend(datapoints)

    def remove_datapoints(self, datapoint_ids):
        self.removed.extend(datapoint_ids)


class _FakeEndpoint:
    def __init__(self, neighbors):
        self._neighbors = neighbors

    def find_neighbors(self, deployed_index_id, queries, num_neighbors):
        return [self._neighbors[:num_neighbors]]


def _vector_adapter(neighbors):
    index = _FakeIndex()
    endpoint = _FakeEndpoint(neighbors)
    config = VertexIndexConfig(index=index, endpoint=endpoint, deployed_index_id="d1")
    adapter = GCPVectorDBAdapter({"zone3": config}, _FakeEmbedder())
    return adapter, index


async def test_gcp_vector_upsert_and_delete():
    adapter, index = _vector_adapter([])
    count = await adapter.upsert(
        "zone3", [VectorDocument(id="d1", content="hello world")]
    )
    assert count == 1
    assert index.upserted[0]["datapoint_id"] == "d1"
    assert index.upserted[0]["feature_vector"]  # embedded
    await adapter.delete("zone3", ["d1"])
    assert index.removed == ["d1"]


async def test_gcp_vector_query_maps_neighbors():
    neighbor = type("N", (), {"id": "d7", "distance": 0.42})()
    adapter, _ = _vector_adapter([neighbor])
    results = await adapter.query("zone3", "find this", top_k=1)
    assert len(results) == 1
    assert results[0].id == "d7"
    assert results[0].score == pytest.approx(0.42)


async def test_gcp_vector_unknown_index_raises():
    adapter, _ = _vector_adapter([])
    with pytest.raises(ValueError, match="No Vertex index"):
        await adapter.query("zoneX", "q")


# ---------------------------------------------------------------------------
# Factory dispatch (Constraint #6) — routes to the GCP package without the SDK
# ---------------------------------------------------------------------------

def test_factory_dispatches_to_gcp(monkeypatch):
    import adapters.factory as factory
    import adapters.gcp.storage as gcp_storage

    sentinel = object()
    monkeypatch.setenv("CLOUD_TARGET", "GCP")
    monkeypatch.setattr(gcp_storage, "get_adapter", lambda: sentinel)
    factory.reset_factory()
    try:
        assert factory.get_storage() is sentinel
    finally:
        factory.reset_factory()
