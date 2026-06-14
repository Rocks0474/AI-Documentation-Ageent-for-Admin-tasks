"""LOCAL NotificationAdapter — records and logs notifications.

Does not deliver to a real channel; instead it appends each notification to an
inspectable ``sent`` list and emits a structured log line. Tests assert on
``sent`` to verify HITL escalation behaviour.
"""

from __future__ import annotations

import uuid
from typing import Optional

import structlog

from adapters.base.notification import Notification, NotificationAdapter

logger = structlog.get_logger()


class LocalNotificationAdapter(NotificationAdapter):
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    async def send(self, notification: Notification) -> str:
        message_id = str(uuid.uuid4())
        self.sent.append(notification)
        logger.info(
            "notification.send",
            channel=notification.channel.value,
            recipient=notification.recipient,
            subject=notification.subject,
            priority=notification.priority,
            request_id=notification.request_id,
            message_id=message_id,
        )
        return message_id


_adapter: Optional[LocalNotificationAdapter] = None


def get_adapter() -> LocalNotificationAdapter:
    global _adapter
    if _adapter is None:
        _adapter = LocalNotificationAdapter()
    return _adapter
