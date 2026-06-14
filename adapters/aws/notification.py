"""AWS NotificationAdapter — Amazon SNS.

Publishes the notification to an SNS topic; downstream subscriptions (Lambda,
email, chat webhooks) handle delivery. Bodies carry references, never Zone 1
data.
"""

from __future__ import annotations

import asyncio
import json
import os

from adapters.base.notification import Notification, NotificationAdapter


class AWSNotificationAdapter(NotificationAdapter):
    def __init__(self, client, topic_arn: str) -> None:
        self._client = client
        self._topic_arn = topic_arn

    async def send(self, notification: Notification) -> str:
        message = json.dumps(notification.model_dump(), ensure_ascii=False)
        attributes = {
            "channel": {"DataType": "String", "StringValue": notification.channel.value},
            "priority": {"DataType": "String", "StringValue": notification.priority},
        }
        if notification.request_id:
            attributes["request_id"] = {
                "DataType": "String",
                "StringValue": notification.request_id,
            }

        def _publish() -> str:
            response = self._client.publish(
                TopicArn=self._topic_arn,
                Subject=notification.subject[:100],
                Message=message,
                MessageAttributes=attributes,
            )
            return response["MessageId"]

        return await asyncio.to_thread(_publish)


def get_adapter() -> AWSNotificationAdapter:
    import boto3  # lazy import

    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    client = boto3.client("sns", region_name=region)
    topic_arn = os.environ["SNS_TOPIC_ARN_NOTIFICATIONS"]
    return AWSNotificationAdapter(client, topic_arn)
