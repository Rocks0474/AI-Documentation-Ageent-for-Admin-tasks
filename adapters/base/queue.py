"""QueueAdapter — message queue / pub-sub interface.

Backs Director Agent routing and inter-agent messaging. Concrete targets map
topics to GCP Pub/Sub topics, AWS SQS queues, or an in-process queue for LOCAL.
Message bodies must never contain Zone 1 (PII) data — only anonymized
references and routing metadata.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class QueueMessage(BaseModel):
    """A message pulled from a queue/topic."""

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic: str
    body: dict = Field(default_factory=dict)
    attributes: dict[str, str] = Field(default_factory=dict)
    published_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class QueueAdapter(ABC):
    """Publish/subscribe message transport."""

    @abstractmethod
    async def publish(
        self,
        topic: str,
        body: dict,
        *,
        attributes: Optional[dict[str, str]] = None,
    ) -> str:
        """Publish ``body`` to ``topic``; return the published message id."""
        ...

    @abstractmethod
    async def pull(self, topic: str, max_messages: int = 1) -> list[QueueMessage]:
        """Pull up to ``max_messages`` from ``topic`` without acknowledging them."""
        ...

    @abstractmethod
    async def ack(self, topic: str, message_id: str) -> None:
        """Acknowledge a previously pulled message, removing it from the queue."""
        ...
