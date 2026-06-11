"""Unit tests for settings, the Japan statutory calendar, and startup."""

from __future__ import annotations

from adapters import factory
from adapters.local.scheduler import LocalSchedulerAdapter
from config.japan_statutory_calendar import (
    JAPAN_STATUTORY_JOBS,
    seed_japan_statutory_jobs,
    statutory_jobs,
)
from config.settings import CloudTarget, Settings, get_settings

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def test_settings_defaults():
    settings = Settings(_env_file=None)
    assert settings.cloud_target == CloudTarget.LOCAL
    assert settings.minimum_cohort_size == 10
    assert settings.hris_system == "SMARTHR"
    assert settings.gcp_region == "asia-northeast1"
    assert settings.aws_region == "ap-northeast-1"


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("CLOUD_TARGET", "GCP")
    monkeypatch.setenv("MINIMUM_COHORT_SIZE", "25")
    monkeypatch.setenv("GREENHOUSE_CONNECTED", "true")
    settings = Settings(_env_file=None)
    assert settings.cloud_target == CloudTarget.GCP
    assert settings.minimum_cohort_size == 25  # coerced to int
    assert settings.greenhouse_connected is True  # coerced to bool


def test_get_settings_is_cached():
    get_settings.cache_clear()
    assert get_settings() is get_settings()


# ---------------------------------------------------------------------------
# Japan statutory calendar
# ---------------------------------------------------------------------------

def test_statutory_jobs_parse_and_are_unique():
    jobs = statutory_jobs()
    assert len(jobs) == len(JAPAN_STATUTORY_JOBS) == 5
    job_ids = [j.job_id for j in jobs]
    assert len(set(job_ids)) == len(job_ids)  # unique ids
    assert all(j.timezone == "Asia/Tokyo" for j in jobs)


async def test_seed_japan_statutory_jobs_registers_all():
    scheduler = LocalSchedulerAdapter()
    created = await seed_japan_statutory_jobs(scheduler)
    assert len(created) == 5
    assert len(await scheduler.list_jobs()) == 5


# ---------------------------------------------------------------------------
# Startup self-check (what docker-compose runs)
# ---------------------------------------------------------------------------

async def test_startup_self_check_local(monkeypatch):
    monkeypatch.setenv("CLOUD_TARGET", "LOCAL")
    get_settings.cache_clear()
    factory.reset_factory()
    try:
        import main

        await main.startup()  # must complete without raising
        # JP is the default jurisdiction, so the statutory calendar is seeded.
        scheduler = factory.get_scheduler()
        assert len(await scheduler.list_jobs()) == 5
    finally:
        get_settings.cache_clear()
        factory.reset_factory()
