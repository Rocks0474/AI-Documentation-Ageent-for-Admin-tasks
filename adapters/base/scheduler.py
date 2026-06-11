"""SchedulerAdapter — cron-style job scheduling interface.

Drives recurring statutory triggers such as the Japan statutory filing
calendar (see ``config/japan_statutory_calendar.py``). Each job publishes a
payload to a target topic on a cron schedule. Concrete targets map to GCP Cloud
Scheduler, AWS EventBridge Scheduler, or an in-memory registry for LOCAL.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class ScheduledJob(BaseModel):
    """A recurring job definition.

    Field shape matches the seed records in ``JAPAN_STATUTORY_JOBS`` so the
    statutory calendar can be loaded directly through :meth:`create_job`.
    """

    job_id: str
    cron_expression: str  # standard 5-field cron
    target_topic: str  # topic the payload is published to when the job fires
    payload: dict = Field(default_factory=dict)
    timezone: str = "Asia/Tokyo"


class SchedulerAdapter(ABC):
    """Create and manage recurring scheduled jobs."""

    @abstractmethod
    async def create_job(self, job: ScheduledJob) -> str:
        """Create (or replace) ``job``; return its ``job_id``."""
        ...

    @abstractmethod
    async def delete_job(self, job_id: str) -> None:
        """Delete the job with ``job_id`` (no-op if absent)."""
        ...

    @abstractmethod
    async def list_jobs(self) -> list[ScheduledJob]:
        """Return all currently registered jobs."""
        ...
