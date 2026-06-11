"""LOCAL QueueAdapter — in-process pub/sub backed by per-topic deques."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import Optional

from adapters.base.queue import QueueAdapter, QueueMessage


class LocalQueueAdapter(QueueAdapter):
    def __init__(self) -> None:
        self._topics: dict[str, deque[QueueMessage]] = defaultdict(deque)
        self._inflight: dict[str, QueueMessage] = {}
        self._lock = asyncio.Lock()

    async def publish(
        self,
        topic: str,
        body: dict,
        *,
        attributes: Optional[dict[str, str]] = None,
    ) -> str:
        message = QueueMessage(topic=topic, body=body, attributes=attributes or {})
        async with self._lock:
            self._topics[topic].append(message)
        return message.message_id

    async def pull(self, topic: str, max_messages: int = 1) -> list[QueueMessage]:
        pulled: list[QueueMessage] = []
        async with self._lock:
            queue = self._topics[topic]
            for _ in range(max_messages):
                if not queue:
                    break
                message = queue.popleft()
                self._inflight[message.message_id] = message
                pulled.append(message)
        return pulled

    async def ack(self, topic: str, message_id: str) -> None:
        async with self._lock:
            self._inflight.pop(message_id, None)


_adapter: Optional[LocalQueueAdapter] = None


def get_adapter() -> LocalQueueAdapter:
    global _adapter
    if _adapter is None:
        _adapter = LocalQueueAdapter()
    return _adapter
