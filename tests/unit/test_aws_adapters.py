"""Unit tests for the AWS adapters — boto3 calls are mocked.

No live AWS calls and no boto3 installed: adapters are exercised against
in-memory fakes that mimic the relevant client surfaces, including a
ClientError-shaped exception (``exc.response['Error']['Code']``). Also verifies
the factory dispatches to the AWS package when CLOUD_TARGET=AWS, and that
switching CLOUD_TARGET alone repoints the same code at GCP vs AWS.
"""

from __future__ import annotations

import json

import pytest

from adapters.aws.audit_log import AWSAuditLogAdapter
from adapters.aws.notification import AWSNotificationAdapter
from adapters.aws.queue import AWSQueueAdapter
from adapters.aws.scheduler import AWSSchedulerAdapter, to_eventbridge_cron
from adapters.aws.secrets import AWSSecretsAdapter
from adapters.aws.storage import AWSStorageAdapter
from adapters.aws.vector_db import AWSVectorDBAdapter
from adapters.base.audit_log import AuditEntry
from adapters.base.notification import Notification, NotificationChannel
from adapters.base.scheduler import ScheduledJob
from adapters.base.secrets import SecretNotFoundError
from adapters.base.storage import DataZone
from adapters.base.vector_db import VectorDocument


class ClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _FakeS3:
    def __init__(self):
        self.store: dict[tuple[str, str], bytes] = {}

    def put_object(self, Bucket, Key, Body, ContentType=None, Metadata=None):
        self.store[(Bucket, Key)] = Body if isinstance(Body, (bytes, bytearray)) else Body.encode()

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.store:
            raise ClientError("NoSuchKey")
        return {"Body": _Body(self.store[(Bucket, Key)])}

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.store:
            raise ClientError("404")
        return {}

    def delete_object(self, Bucket, Key):
        self.store.pop((Bucket, Key), None)

    def list_objects_v2(self, Bucket, Prefix="", ContinuationToken=None):
        keys = [k for (b, k) in self.store if b == Bucket and k.startswith(Prefix)]
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _storage():
    return AWSStorageAdapter(
        _FakeS3(),
        {DataZone.ZONE2: "z2", DataZone.ZONE3: "z3", DataZone.AUDIT: "audit"},
    )


async def test_aws_storage_roundtrip():
    storage = _storage()
    await storage.put("a/b.txt", b"hi", DataZone.ZONE2)
    assert await storage.exists("a/b.txt", DataZone.ZONE2)
    assert await storage.get("a/b.txt", DataZone.ZONE2) == b"hi"
    assert await storage.list("a/", DataZone.ZONE2) == ["a/b.txt"]
    await storage.delete("a/b.txt", DataZone.ZONE2)
    assert not await storage.exists("a/b.txt", DataZone.ZONE2)


async def test_aws_storage_missing_raises_keyerror():
    storage = _storage()
    with pytest.raises(KeyError):
        await storage.get("nope", DataZone.ZONE3)


# ---------------------------------------------------------------------------
# Queue (SQS)
# ---------------------------------------------------------------------------

class _FakeSQS:
    def __init__(self, queued=None):
        self.sent = []
        self.queued = list(queued or [])
        self.deleted = []

    def send_message(self, QueueUrl, MessageBody, MessageAttributes=None):
        self.sent.append((QueueUrl, MessageBody, MessageAttributes))
        return {"MessageId": "m1"}

    def receive_message(self, QueueUrl, MaxNumberOfMessages, MessageAttributeNames=None):
        take, self.queued = self.queued[:MaxNumberOfMessages], self.queued[MaxNumberOfMessages:]
        return {"Messages": take}

    def delete_message(self, QueueUrl, ReceiptHandle):
        self.deleted.append(ReceiptHandle)


async def test_aws_queue_publish_pull_ack():
    msg = {
        "MessageId": "m1",
        "Body": json.dumps({"x": 1}),
        "ReceiptHandle": "rh-1",
        "MessageAttributes": {"a": {"DataType": "String", "StringValue": "b"}},
    }
    sqs = _FakeSQS([msg])
    queue = AWSQueueAdapter(sqs, {"routing": "http://q/routing"})
    mid = await queue.publish("routing", {"k": "v"}, attributes={"a": "b"})
    assert mid == "m1"

    messages = await queue.pull("routing", max_messages=5)
    assert messages[0].body == {"x": 1}
    assert messages[0].attributes == {"a": "b"}
    await queue.ack("routing", "m1")
    assert sqs.deleted == ["rh-1"]


async def test_aws_queue_unconfigured_topic_raises():
    queue = AWSQueueAdapter(_FakeSQS(), {})
    with pytest.raises(ValueError, match="No SQS queue"):
        await queue.publish("nope", {})


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

class _FakeSecrets:
    def __init__(self, secrets):
        self._secrets = secrets

    def get_secret_value(self, SecretId):
        if SecretId not in self._secrets:
            raise ClientError("ResourceNotFoundException")
        return {"SecretString": self._secrets[SecretId]}


async def test_aws_secrets_get_and_missing():
    secrets = AWSSecretsAdapter(_FakeSecrets({"hris-api-key": "v"}))
    assert await secrets.get_secret("hris-api-key") == "v"
    assert await secrets.exists("hris-api-key") is True
    with pytest.raises(SecretNotFoundError):
        await secrets.get_secret("absent")
    assert await secrets.exists("absent") is False


# ---------------------------------------------------------------------------
# Audit log (S3 + CloudWatch Logs)
# ---------------------------------------------------------------------------

class _FakeLogs:
    def __init__(self):
        self.events = []

    def put_log_events(self, logGroupName, logStreamName, logEvents):
        self.events.extend(logEvents)


async def test_aws_audit_append_query_approval_and_worm_log():
    logs = _FakeLogs()
    audit = AWSAuditLogAdapter(
        _FakeS3(), "audit", logs_client=logs, log_group="g", log_stream="s"
    )
    eid = await audit.append(AuditEntry(event_type="REQUEST_RECEIVED", request_id="r1"))
    assert len(logs.events) == 1  # mirrored to the immutable log group

    assert (await audit.get(eid)).event_type == "REQUEST_RECEIVED"
    assert [e.event_type for e in await audit.query("r1")] == ["REQUEST_RECEIVED"]

    updated = await audit.record_approval(eid, approver_id="chro@corp")
    assert updated.approver_id == "chro@corp"
    assert (await audit.get(eid)).approver_id == "chro@corp"
    assert len(logs.events) == 2  # approval also recorded immutably


async def test_aws_audit_record_approval_missing_raises():
    audit = AWSAuditLogAdapter(_FakeS3(), "audit")
    with pytest.raises(KeyError):
        await audit.record_approval("nope", approver_id="x")


# ---------------------------------------------------------------------------
# Scheduler (EventBridge Scheduler)
# ---------------------------------------------------------------------------

def test_to_eventbridge_cron_translates_dow_and_dom():
    assert to_eventbridge_cron("0 9 1 7 *") == "cron(0 9 1 7 ? *)"
    assert to_eventbridge_cron("0 9 1 * *") == "cron(0 9 1 * ? *)"
    assert to_eventbridge_cron("0 9 * * 1") == "cron(0 9 ? * 1 *)"


class _FakeSchedulerClient:
    def __init__(self):
        self.schedules: dict[str, dict] = {}

    def create_schedule(self, Name, **kwargs):
        if Name in self.schedules:
            raise ClientError("ConflictException")
        self.schedules[Name] = {"Name": Name, **kwargs}

    def update_schedule(self, Name, **kwargs):
        self.schedules[Name] = {"Name": Name, **kwargs}

    def delete_schedule(self, Name):
        if Name not in self.schedules:
            raise ClientError("ResourceNotFoundException")
        del self.schedules[Name]

    def list_schedules(self):
        return {"Schedules": [{"Name": n} for n in self.schedules]}

    def get_schedule(self, Name):
        return self.schedules[Name]


def _scheduler():
    return AWSSchedulerAdapter(
        _FakeSchedulerClient(),
        {"statutory-filing-alerts": "arn:aws:sns:statutory"},
        role_arn="arn:aws:iam::role",
    )


def _job():
    return ScheduledJob(
        job_id="jp_santei_kiso_todoke",
        cron_expression="0 9 1 7 *",
        target_topic="statutory-filing-alerts",
        payload={"filing_type": "算定基礎届", "deadline_days": 10},
    )


async def test_aws_scheduler_create_list_delete():
    scheduler = _scheduler()
    await scheduler.create_job(_job())
    jobs = await scheduler.list_jobs()
    assert [j.job_id for j in jobs] == ["jp_santei_kiso_todoke"]
    assert jobs[0].target_topic == "statutory-filing-alerts"
    assert jobs[0].payload == {"filing_type": "算定基礎届", "deadline_days": 10}
    await scheduler.delete_job("jp_santei_kiso_todoke")
    assert await scheduler.list_jobs() == []


async def test_aws_scheduler_create_is_idempotent():
    scheduler = _scheduler()
    await scheduler.create_job(_job())
    await scheduler.create_job(_job())  # ConflictException -> update_schedule
    assert len(await scheduler.list_jobs()) == 1


# ---------------------------------------------------------------------------
# Notification (SNS)
# ---------------------------------------------------------------------------

class _FakeSNS:
    def __init__(self):
        self.published = []

    def publish(self, TopicArn, Subject, Message, MessageAttributes):
        self.published.append((TopicArn, Subject, Message, MessageAttributes))
        return {"MessageId": "m1"}


async def test_aws_notification_publishes():
    sns = _FakeSNS()
    notifier = AWSNotificationAdapter(sns, "arn:aws:sns:notifications")
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
    assert mid == "m1"
    _, _, _, attrs = sns.published[0]
    assert attrs["channel"]["StringValue"] == "SLACK"
    assert attrs["priority"]["StringValue"] == "critical"


# ---------------------------------------------------------------------------
# Vector DB (OpenSearch)
# ---------------------------------------------------------------------------

class _FakeEmbedder:
    def embed(self, text):
        return [float(len(text)), 1.0]


class _FakeOpenSearch:
    def __init__(self, hits=None):
        self.docs = {}
        self._hits = hits or []
        self.deleted = []

    def index(self, index, id, body):
        self.docs[(index, id)] = body

    def search(self, index, body):
        return {"hits": {"hits": self._hits}}

    def delete(self, index, id, ignore=None):
        self.deleted.append(id)


async def test_aws_vector_upsert_and_delete():
    client = _FakeOpenSearch()
    adapter = AWSVectorDBAdapter(client, _FakeEmbedder())
    count = await adapter.upsert(
        "zone3", [VectorDocument(id="d1", content="hello world")]
    )
    assert count == 1
    body = client.docs[("zone3", "d1")]
    assert body["content"] == "hello world" and body["vector"]
    await adapter.delete("zone3", ["d1"])
    assert client.deleted == ["d1"]


async def test_aws_vector_query_returns_content():
    hits = [{"_id": "d7", "_score": 1.5, "_source": {"content": "txt", "metadata": {"z": "3"}}}]
    adapter = AWSVectorDBAdapter(_FakeOpenSearch(hits), _FakeEmbedder())
    results = await adapter.query("zone3", "find", top_k=1)
    assert results[0].id == "d7"
    assert results[0].content == "txt"
    assert results[0].score == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# Factory dispatch + single-image / env-only switch
# ---------------------------------------------------------------------------

def test_factory_dispatches_to_aws(monkeypatch):
    import adapters.aws.storage as aws_storage
    import adapters.factory as factory

    sentinel = object()
    monkeypatch.setenv("CLOUD_TARGET", "AWS")
    monkeypatch.setattr(aws_storage, "get_adapter", lambda: sentinel)
    factory.reset_factory()
    try:
        assert factory.get_storage() is sentinel
    finally:
        factory.reset_factory()


def test_same_code_switches_clouds_by_env_only(monkeypatch):
    """The same code path repoints at GCP vs AWS purely via CLOUD_TARGET."""
    import adapters.aws.storage as aws_storage
    import adapters.factory as factory
    import adapters.gcp.storage as gcp_storage

    gcp_sentinel, aws_sentinel = object(), object()
    monkeypatch.setattr(gcp_storage, "get_adapter", lambda: gcp_sentinel)
    monkeypatch.setattr(aws_storage, "get_adapter", lambda: aws_sentinel)

    monkeypatch.setenv("CLOUD_TARGET", "GCP")
    factory.reset_factory()
    assert factory.get_storage() is gcp_sentinel

    monkeypatch.setenv("CLOUD_TARGET", "AWS")
    factory.reset_factory()
    assert factory.get_storage() is aws_sentinel
    factory.reset_factory()
