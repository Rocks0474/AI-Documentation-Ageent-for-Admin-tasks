"""AWS SchedulerAdapter — Amazon EventBridge Scheduler.

Schedules publish a JSON payload to a target (SNS topic / SQS queue) on a cron.
The Japan statutory calendar is provisioned declaratively via Terraform; this
adapter manages dynamic schedules at runtime. Standard 5-field cron expressions
are translated to EventBridge's 6-field ``cron(...)`` form.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

from adapters.aws._errors import is_conflict, is_not_found
from adapters.base.scheduler import ScheduledJob, SchedulerAdapter


def to_eventbridge_cron(expression: str) -> str:
    """Translate a 5-field cron (m h dom mon dow) to EventBridge cron(...).

    EventBridge requires exactly one of day-of-month / day-of-week to be ``?``.
    """
    parts = expression.split()
    if len(parts) != 5:
        # Already an EventBridge expression or unknown form — pass through.
        return f"cron({expression})"
    minute, hour, dom, month, dow = parts
    if dow == "*":
        dow = "?"
    elif dom == "*":
        dom = "?"
    return f"cron({minute} {hour} {dom} {month} {dow} *)"


class AWSSchedulerAdapter(SchedulerAdapter):
    def __init__(
        self,
        client,
        target_arns: dict[str, str],
        role_arn: str,
    ) -> None:
        self._client = client
        self._target_arns = target_arns
        self._role_arn = role_arn

    def _target_arn(self, topic: str) -> str:
        arn = self._target_arns.get(topic)
        if not arn:
            raise ValueError(f"No EventBridge target ARN configured for {topic!r}")
        return arn

    async def create_job(self, job: ScheduledJob) -> str:
        kwargs = {
            "Name": job.job_id,
            "ScheduleExpression": to_eventbridge_cron(job.cron_expression),
            "ScheduleExpressionTimezone": job.timezone,
            "FlexibleTimeWindow": {"Mode": "OFF"},
            "Target": {
                "Arn": self._target_arn(job.target_topic),
                "RoleArn": self._role_arn,
                "Input": json.dumps(job.payload, ensure_ascii=False),
            },
        }

        def _create() -> None:
            try:
                self._client.create_schedule(**kwargs)
            except Exception as exc:  # noqa: BLE001 - upsert semantics
                if not is_conflict(exc):
                    raise
                self._client.update_schedule(**kwargs)

        await asyncio.to_thread(_create)
        return job.job_id

    async def delete_job(self, job_id: str) -> None:
        def _delete() -> None:
            try:
                self._client.delete_schedule(Name=job_id)
            except Exception as exc:  # noqa: BLE001 - idempotent delete
                if not is_not_found(exc):
                    raise

        await asyncio.to_thread(_delete)

    async def list_jobs(self) -> list[ScheduledJob]:
        def _list() -> list[ScheduledJob]:
            arn_to_topic = {v: k for k, v in self._target_arns.items()}
            summaries = self._client.list_schedules().get("Schedules", [])
            jobs: list[ScheduledJob] = []
            for summary in summaries:
                detail = self._client.get_schedule(Name=summary["Name"])
                target = detail.get("Target", {})
                payload = (
                    json.loads(detail["Target"]["Input"])
                    if target.get("Input")
                    else {}
                )
                jobs.append(
                    ScheduledJob(
                        job_id=detail["Name"],
                        cron_expression=detail.get("ScheduleExpression", ""),
                        target_topic=arn_to_topic.get(target.get("Arn", ""), ""),
                        payload=payload,
                        timezone=detail.get("ScheduleExpressionTimezone", "Asia/Tokyo"),
                    )
                )
            return jobs

        return await asyncio.to_thread(_list)


def get_adapter() -> AWSSchedulerAdapter:
    import boto3  # lazy import

    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    client = boto3.client("scheduler", region_name=region)
    role_arn = os.environ["EVENTBRIDGE_SCHEDULER_ROLE_ARN"]
    target_arns: dict[str, str] = {}
    for topic, env in {
        "statutory-filing-alerts": "SNS_TOPIC_ARN_STATUTORY",
        "hr-workflow-triggers": "SNS_TOPIC_ARN_WORKFLOW",
        "hr-notifications": "SNS_TOPIC_ARN_NOTIFICATIONS",
    }.items():
        arn: Optional[str] = os.environ.get(env)
        if arn:
            target_arns[topic] = arn
    return AWSSchedulerAdapter(client, target_arns, role_arn)
