"""GCP SchedulerAdapter — Cloud Scheduler.

Creates cron jobs that publish a payload to a Pub/Sub topic. The Japan statutory
calendar is also provisioned declaratively via Terraform; this adapter covers
dynamic job management at runtime. Jobs use a Pub/Sub target so they fan into the
same routing/queue plane as the rest of the system.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

from adapters.base.scheduler import ScheduledJob, SchedulerAdapter


class GCPSchedulerAdapter(SchedulerAdapter):
    def __init__(
        self,
        client,
        project_id: str,
        region: str,
        topic_project_id: Optional[str] = None,
    ) -> None:
        self._client = client
        self._project_id = project_id
        self._region = region
        self._topic_project_id = topic_project_id or project_id

    def _parent(self) -> str:
        return f"projects/{self._project_id}/locations/{self._region}"

    def _job_name(self, job_id: str) -> str:
        return f"{self._parent()}/jobs/{job_id}"

    def _topic_name(self, topic: str) -> str:
        return f"projects/{self._topic_project_id}/topics/{topic}"

    def _to_job_dict(self, job: ScheduledJob) -> dict:
        return {
            "name": self._job_name(job.job_id),
            "schedule": job.cron_expression,
            "time_zone": job.timezone,
            "pubsub_target": {
                "topic_name": self._topic_name(job.target_topic),
                "data": json.dumps(job.payload, ensure_ascii=False).encode("utf-8"),
            },
        }

    async def create_job(self, job: ScheduledJob) -> str:
        job_dict = self._to_job_dict(job)

        def _create() -> None:
            try:
                self._client.create_job(parent=self._parent(), job=job_dict)
            except Exception as exc:  # noqa: BLE001 - upsert semantics
                if type(exc).__name__ != "AlreadyExists":
                    raise
                self._client.update_job(job=job_dict)

        await asyncio.to_thread(_create)
        return job.job_id

    async def delete_job(self, job_id: str) -> None:
        def _delete() -> None:
            try:
                self._client.delete_job(name=self._job_name(job_id))
            except Exception as exc:  # noqa: BLE001 - idempotent delete
                if type(exc).__name__ != "NotFound":
                    raise

        await asyncio.to_thread(_delete)

    async def list_jobs(self) -> list[ScheduledJob]:
        def _list() -> list[ScheduledJob]:
            jobs: list[ScheduledJob] = []
            for job in self._client.list_jobs(parent=self._parent()):
                target = getattr(job, "pubsub_target", None)
                topic = ""
                payload: dict = {}
                if target is not None:
                    topic = target.topic_name.rsplit("/", 1)[-1]
                    if getattr(target, "data", None):
                        payload = json.loads(target.data.decode("utf-8"))
                jobs.append(
                    ScheduledJob(
                        job_id=job.name.rsplit("/", 1)[-1],
                        cron_expression=job.schedule,
                        target_topic=topic,
                        payload=payload,
                        timezone=getattr(job, "time_zone", "Asia/Tokyo"),
                    )
                )
            return jobs

        return await asyncio.to_thread(_list)


def get_adapter() -> GCPSchedulerAdapter:
    from google.cloud import scheduler_v1  # lazy import

    client = scheduler_v1.CloudSchedulerClient()
    project_id = os.environ["GCP_PROJECT_ID"]
    region = os.environ.get("GCP_REGION", "asia-northeast1")
    return GCPSchedulerAdapter(client, project_id, region)
