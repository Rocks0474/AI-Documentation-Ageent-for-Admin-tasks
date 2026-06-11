"""GCP NotificationAdapter — publishes notifications to a Pub/Sub topic.

Rather than calling Slack/email directly, the adapter publishes the notification
to a dedicated Pub/Sub topic (default ``hr-notifications``); a downstream
delivery worker (Cloud Function) fans it out to the requested channel. This
decouples agents from delivery and keeps an auditable record of every
notification. Bodies carry references, never Zone 1 data.
"""

from __future__ import annotations

import asyncio
import json
import os

from adapters.base.notification import Notification, NotificationAdapter


class GCPNotificationAdapter(NotificationAdapter):
    def __init__(self, publisher, project_id: str, topic: str = "hr-notifications") -> None:
        self._publisher = publisher
        self._project_id = project_id
        self._topic = topic

    def _topic_path(self) -> str:
        return self._publisher.topic_path(self._project_id, self._topic)

    async def send(self, notification: Notification) -> str:
        data = json.dumps(notification.model_dump(), ensure_ascii=False).encode("utf-8")

        def _publish() -> str:
            future = self._publisher.publish(
                self._topic_path(),
                data,
                channel=notification.channel.value,
                priority=notification.priority,
                request_id=notification.request_id or "",
            )
            return future.result()

        return await asyncio.to_thread(_publish)


def get_adapter() -> GCPNotificationAdapter:
    from google.cloud import pubsub_v1  # lazy import

    publisher = pubsub_v1.PublisherClient()
    project_id = os.environ["GCP_PROJECT_ID"]
    topic = os.environ.get("PUBSUB_TOPIC_NOTIFICATIONS", "hr-notifications")
    return GCPNotificationAdapter(publisher, project_id, topic)
