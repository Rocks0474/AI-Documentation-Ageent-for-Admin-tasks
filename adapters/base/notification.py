"""NotificationAdapter — outbound human-notification interface.

Primary use is HITL (human-in-the-loop) escalation: when an agent produces a
``MANDATORY`` HITL result, a notification is sent to the designated approver.
Notification bodies carry references (request ids, storage keys) rather than
inline content, and must never contain Zone 1 (PII) data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class NotificationChannel(str, Enum):
    SLACK = "SLACK"
    EMAIL = "EMAIL"
    TEAMS = "TEAMS"
    WEBHOOK = "WEBHOOK"


class Notification(BaseModel):
    """A single outbound notification."""

    channel: NotificationChannel
    recipient: str  # channel-specific: Slack channel/user, email address, URL
    subject: str
    body: str
    priority: str = "normal"  # normal | high | critical
    request_id: Optional[str] = None


class NotificationAdapter(ABC):
    """Send notifications to human recipients."""

    @abstractmethod
    async def send(self, notification: Notification) -> str:
        """Send ``notification``; return a provider message/delivery id."""
        ...
