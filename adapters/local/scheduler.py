"""LOCAL SchedulerAdapter — in-memory job registry.

Stores job definitions but does not actually fire them on a schedule; local
and test environments trigger workflows directly. Useful for verifying that the
Japan statutory calendar seeds correctly via :meth:`create_job`.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from adapters.base.scheduler import ScheduledJob, SchedulerAdapter


class LocalSchedulerAdapter(SchedulerAdapter):
    def __init__(self) -> None:
        self._jobs: dict[str, ScheduledJob] = {}
        self._lock = asyncio.Lock()

    async def create_job(self, job: ScheduledJob) -> str:
        async with self._lock:
            self._jobs[job.job_id] = job
        return job.job_id

    async def delete_job(self, job_id: str) -> None:
        async with self._lock:
            self._jobs.pop(job_id, None)

    async def list_jobs(self) -> list[ScheduledJob]:
        return list(self._jobs.values())


_adapter: Optional[LocalSchedulerAdapter] = None


def get_adapter() -> LocalSchedulerAdapter:
    global _adapter
    if _adapter is None:
        _adapter = LocalSchedulerAdapter()
    return _adapter
