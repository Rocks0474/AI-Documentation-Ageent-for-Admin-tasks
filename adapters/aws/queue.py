"""AWS QueueAdapter — Amazon SQS.

Logical topic names map to SQS queue URLs. Message bodies are JSON; attributes
are carried as SQS message attributes. Bodies hold only anonymized references.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

from adapters.base.queue import QueueAdapter, QueueMessage


class AWSQueueAdapter(QueueAdapter):
    def __init__(self, client, queue_urls: dict[str, str]) -> None:
        self._client = client
        self._queue_urls = queue_urls
        # message_id -> receipt handle, captured at receive time for ack().
        self._receipts: dict[str, str] = {}

    def _queue_url(self, topic: str) -> str:
        url = self._queue_urls.get(topic)
        if not url:
            raise ValueError(f"No SQS queue configured for topic {topic!r}")
        return url

    async def publish(
        self,
        topic: str,
        body: dict,
        *,
        attributes: Optional[dict[str, str]] = None,
    ) -> str:
        message_attributes = {
            k: {"DataType": "String", "StringValue": v}
            for k, v in (attributes or {}).items()
        }

        def _send() -> str:
            response = self._client.send_message(
                QueueUrl=self._queue_url(topic),
                MessageBody=json.dumps(body, ensure_ascii=False),
                MessageAttributes=message_attributes,
            )
            return response["MessageId"]

        return await asyncio.to_thread(_send)

    async def pull(self, topic: str, max_messages: int = 1) -> list[QueueMessage]:
        def _receive():
            return self._client.receive_message(
                QueueUrl=self._queue_url(topic),
                MaxNumberOfMessages=max_messages,
                MessageAttributeNames=["All"],
            )

        response = await asyncio.to_thread(_receive)
        messages: list[QueueMessage] = []
        for raw in response.get("Messages", []):
            body = json.loads(raw["Body"]) if raw.get("Body") else {}
            attributes = {
                k: v.get("StringValue", "")
                for k, v in raw.get("MessageAttributes", {}).items()
            }
            message_id = raw["MessageId"]
            self._receipts[message_id] = raw["ReceiptHandle"]
            messages.append(
                QueueMessage(
                    message_id=message_id,
                    topic=topic,
                    body=body,
                    attributes=attributes,
                )
            )
        return messages

    async def ack(self, topic: str, message_id: str) -> None:
        receipt = self._receipts.pop(message_id, None)
        if receipt is None:
            return
        await asyncio.to_thread(
            lambda: self._client.delete_message(
                QueueUrl=self._queue_url(topic), ReceiptHandle=receipt
            )
        )


def get_adapter() -> AWSQueueAdapter:
    import boto3  # lazy import

    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    client = boto3.client("sqs", region_name=region)
    queue_urls: dict[str, str] = {}
    routing_url = os.environ.get("SQS_QUEUE_URL_ROUTING")
    if routing_url:
        queue_urls["routing"] = routing_url
    return AWSQueueAdapter(client, queue_urls)
