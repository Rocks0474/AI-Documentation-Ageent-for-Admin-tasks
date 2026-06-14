"""GCP QueueAdapter — Cloud Pub/Sub.

Logical topic names map directly to Pub/Sub topics; pulls read from a
subscription named ``<topic>-sub`` by default. Message bodies are JSON-encoded
and carry only anonymized references and routing metadata (never Zone 1 data).
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

from adapters.base.queue import QueueAdapter, QueueMessage


class GCPQueueAdapter(QueueAdapter):
    def __init__(
        self,
        publisher,
        subscriber,
        project_id: str,
        subscription_suffix: str = "-sub",
    ) -> None:
        self._publisher = publisher
        self._subscriber = subscriber
        self._project_id = project_id
        self._subscription_suffix = subscription_suffix
        # message_id -> ack_id, captured at pull time for ack().
        self._ack_ids: dict[str, str] = {}

    def _topic_path(self, topic: str) -> str:
        return self._publisher.topic_path(self._project_id, topic)

    def _subscription_path(self, topic: str) -> str:
        return self._subscriber.subscription_path(
            self._project_id, f"{topic}{self._subscription_suffix}"
        )

    async def publish(
        self,
        topic: str,
        body: dict,
        *,
        attributes: Optional[dict[str, str]] = None,
    ) -> str:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

        def _publish() -> str:
            future = self._publisher.publish(
                self._topic_path(topic), data, **(attributes or {})
            )
            return future.result()

        return await asyncio.to_thread(_publish)

    async def pull(self, topic: str, max_messages: int = 1) -> list[QueueMessage]:
        def _pull():
            return self._subscriber.pull(
                request={
                    "subscription": self._subscription_path(topic),
                    "max_messages": max_messages,
                }
            )

        response = await asyncio.to_thread(_pull)
        messages: list[QueueMessage] = []
        for received in response.received_messages:
            message = received.message
            body = json.loads(message.data.decode("utf-8")) if message.data else {}
            queue_message = QueueMessage(
                message_id=message.message_id,
                topic=topic,
                body=body,
                attributes=dict(message.attributes),
            )
            self._ack_ids[message.message_id] = received.ack_id
            messages.append(queue_message)
        return messages

    async def ack(self, topic: str, message_id: str) -> None:
        ack_id = self._ack_ids.pop(message_id, None)
        if ack_id is None:
            return

        def _ack() -> None:
            self._subscriber.acknowledge(
                request={
                    "subscription": self._subscription_path(topic),
                    "ack_ids": [ack_id],
                }
            )

        await asyncio.to_thread(_ack)


def get_adapter() -> GCPQueueAdapter:
    from google.cloud import pubsub_v1  # lazy import

    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()
    project_id = os.environ["GCP_PROJECT_ID"]
    return GCPQueueAdapter(publisher, subscriber, project_id)
