"""Japan statutory filing calendar — seed data for the SchedulerAdapter.

Seed these jobs via the SchedulerAdapter on first deploy for JP clients. All
timezones: Asia/Tokyo. Use :func:`seed_japan_statutory_jobs` to register them.
"""

from __future__ import annotations

from adapters.base.scheduler import ScheduledJob, SchedulerAdapter

JAPAN_STATUTORY_JOBS: list[dict] = [
    # 雇用保険 年度更新 (Labor Insurance Annual Renewal)
    {
        "job_id": "jp_rodo_hoken_renewal",
        "cron_expression": "0 9 1 6 *",  # June 1 annually
        "target_topic": "statutory-filing-alerts",
        "payload": {"filing_type": "労働保険年度更新", "deadline_days": 50},
        "timezone": "Asia/Tokyo",
    },
    # 社会保険 算定基礎届 (Social Insurance Standard Remuneration Declaration)
    {
        "job_id": "jp_santei_kiso_todoke",
        "cron_expression": "0 9 1 7 *",  # July 1 annually
        "target_topic": "statutory-filing-alerts",
        "payload": {"filing_type": "算定基礎届", "deadline_days": 10},
        "timezone": "Asia/Tokyo",
    },
    # 年末調整 preparation trigger
    {
        "job_id": "jp_nenmatsuchosei_prep",
        "cron_expression": "0 9 1 11 *",  # November 1 annually
        "target_topic": "statutory-filing-alerts",
        "payload": {"filing_type": "年末調整", "deadline_days": 60},
        "timezone": "Asia/Tokyo",
    },
    # 36協定 renewal check — monthly
    {
        "job_id": "jp_36kyotei_check",
        "cron_expression": "0 9 1 * *",  # 1st of every month
        "target_topic": "statutory-filing-alerts",
        "payload": {"filing_type": "36協定更新確認", "deadline_days": 30},
        "timezone": "Asia/Tokyo",
    },
    # Merit cycle trigger — Japan fiscal year start
    {
        "job_id": "jp_merit_cycle_trigger",
        "cron_expression": "0 9 1 2 *",  # February 1 — prep for April cycle
        "target_topic": "hr-workflow-triggers",
        "payload": {"workflow_type": "MERIT_CYCLE_PREP", "jurisdiction": "JP"},
        "timezone": "Asia/Tokyo",
    },
]


def statutory_jobs() -> list[ScheduledJob]:
    """Return the seed jobs as validated :class:`ScheduledJob` models."""
    return [ScheduledJob(**job) for job in JAPAN_STATUTORY_JOBS]


async def seed_japan_statutory_jobs(scheduler: SchedulerAdapter) -> list[str]:
    """Register every Japan statutory job; return the created job ids."""
    created: list[str] = []
    for job in statutory_jobs():
        created.append(await scheduler.create_job(job))
    return created
