"""Application entrypoint.

Phase 1 has no LLM calls and no HTTP server yet; this entrypoint performs a
startup self-check — it validates configuration, wires up every adapter through
the factory for the active ``CLOUD_TARGET``, and (for JP clients) seeds the
Japan statutory filing calendar. It is what ``docker-compose up`` runs to prove
the full stack boots locally with ``CLOUD_TARGET=LOCAL``.

Run modes (``RUN_MODE`` env):
  - ``server`` (default) — self-check, then idle so the container stays up.
  - ``check``            — self-check, then exit 0. Useful in CI/healthchecks.
"""

from __future__ import annotations

import asyncio
import logging
import os

import structlog

from adapters.factory import (
    cloud_target,
    get_audit_log,
    get_notification,
    get_queue,
    get_scheduler,
    get_secrets,
    get_storage,
    get_vector_db,
)
from config.japan_statutory_calendar import seed_japan_statutory_jobs
from config.settings import get_settings

logger = structlog.get_logger()


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )


async def startup() -> None:
    """Validate config and wire up all adapters for the active CLOUD_TARGET."""
    settings = get_settings()
    _configure_logging(settings.log_level)

    target = cloud_target()
    logger.info(
        "startup.begin",
        cloud_target=target,
        default_jurisdiction=settings.default_jurisdiction,
        hris_system=settings.hris_system,
    )

    # Instantiate every adapter — fails fast if a target is misconfigured.
    adapters = {
        "storage": get_storage(),
        "queue": get_queue(),
        "secrets": get_secrets(),
        "audit_log": get_audit_log(),
        "scheduler": get_scheduler(),
        "notification": get_notification(),
        "vector_db": get_vector_db(),
    }
    logger.info(
        "startup.adapters_ready",
        adapters={name: type(impl).__name__ for name, impl in adapters.items()},
    )

    # Seed the Japan statutory filing calendar for JP clients.
    if settings.default_jurisdiction.upper() == "JP":
        job_ids = await seed_japan_statutory_jobs(adapters["scheduler"])
        logger.info("startup.statutory_calendar_seeded", job_ids=job_ids)

    logger.info("startup.ready", cloud_target=target)


async def main() -> None:
    await startup()
    if os.environ.get("RUN_MODE", "server").lower() == "check":
        logger.info("run_mode.check_complete")
        return
    logger.info("run_mode.server_idle")
    await asyncio.Event().wait()  # idle forever — keeps the container alive


if __name__ == "__main__":
    asyncio.run(main())
