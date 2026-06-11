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
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

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


class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal health endpoint so the container passes Cloud Run / ECS checks."""

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args) -> None:  # silence default stderr logging
        return


def build_health_server(port: int = 8080) -> HTTPServer:
    """Build (but do not start) the health HTTP server bound to ``port``."""
    # Binding all interfaces is required so the platform health check can reach
    # the container (Cloud Run / ECS route to the task IP).
    return HTTPServer(("0.0.0.0", port), _HealthHandler)  # noqa: S104


async def main() -> None:
    await startup()
    run_mode = os.environ.get("RUN_MODE", "server").lower()
    if run_mode == "check":
        logger.info("run_mode.check_complete")
        return

    # Serve a health endpoint on $PORT (Cloud Run / ECS expect HTTP).
    port = int(os.environ.get("PORT", "8080"))
    server = build_health_server(port)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    if run_mode == "worker":
        # Consume the ingress queue and drive the orchestration graph.
        from orchestration.worker import build_default_worker

        worker = build_default_worker(
            topic=os.environ.get("WORKER_QUEUE_TOPIC", "routing")
        )
        logger.info("run_mode.worker_listening", port=port)
        await worker.run_forever()
        return

    logger.info("run_mode.server_listening", port=port)
    await asyncio.Event().wait()  # idle forever — keeps the container alive


if __name__ == "__main__":
    asyncio.run(main())
