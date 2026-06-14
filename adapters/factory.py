"""Adapter factory — the single point of cloud-target selection.

Architectural Constraint #6: ``CLOUD_TARGET`` controls everything.

    CLOUD_TARGET = os.environ.get("CLOUD_TARGET", "LOCAL")
    # Valid values: "LOCAL" | "GCP" | "AWS"

Every adapter instance in the system is obtained through one of the ``get_*``
functions here. No agent hard-codes a cloud target, and no agent imports a
concrete implementation directly.

Concrete implementations are imported lazily, inside the getters, so that:
  - importing this module never pulls in a cloud-provider SDK, and
  - selecting LOCAL never requires the GCP/AWS SDKs to be installed.

Each concrete implementation module (e.g. ``adapters.local.storage``) exposes a
zero-argument ``get_adapter()`` factory returning the adapter instance. This
keeps the factory decoupled from per-target class names.

Instances are cached per process (adapters are stateless handles). Tests can
clear the cache with :func:`reset_factory`.
"""

from __future__ import annotations

import importlib
import os
from functools import lru_cache

from adapters.base.audit_log import AuditLogAdapter
from adapters.base.notification import NotificationAdapter
from adapters.base.queue import QueueAdapter
from adapters.base.scheduler import SchedulerAdapter
from adapters.base.secrets import SecretsAdapter
from adapters.base.storage import StorageAdapter
from adapters.base.vector_db import VectorDBAdapter

VALID_TARGETS: frozenset[str] = frozenset({"LOCAL", "GCP", "AWS"})

# Maps the validated CLOUD_TARGET to its implementation subpackage.
_TARGET_PACKAGE: dict[str, str] = {
    "LOCAL": "local",
    "GCP": "gcp",
    "AWS": "aws",
}


def cloud_target() -> str:
    """Return the validated active cloud target (defaults to ``LOCAL``)."""
    target = os.environ.get("CLOUD_TARGET", "LOCAL").upper()
    if target not in VALID_TARGETS:
        raise ValueError(
            f"Invalid CLOUD_TARGET={target!r}. "
            f"Valid values: {', '.join(sorted(VALID_TARGETS))}."
        )
    return target


def _build(component: str):
    """Import ``adapters.<target>.<component>`` and call its ``get_adapter()``."""
    package = _TARGET_PACKAGE[cloud_target()]
    module = importlib.import_module(f"adapters.{package}.{component}")
    try:
        builder = module.get_adapter
    except AttributeError as exc:  # pragma: no cover - implementation contract
        raise AttributeError(
            f"adapters.{package}.{component} must expose a get_adapter() factory."
        ) from exc
    return builder()


@lru_cache(maxsize=None)
def get_storage() -> StorageAdapter:
    return _build("storage")


@lru_cache(maxsize=None)
def get_queue() -> QueueAdapter:
    return _build("queue")


@lru_cache(maxsize=None)
def get_secrets() -> SecretsAdapter:
    return _build("secrets")


@lru_cache(maxsize=None)
def get_audit_log() -> AuditLogAdapter:
    return _build("audit_log")


@lru_cache(maxsize=None)
def get_scheduler() -> SchedulerAdapter:
    return _build("scheduler")


@lru_cache(maxsize=None)
def get_notification() -> NotificationAdapter:
    return _build("notification")


@lru_cache(maxsize=None)
def get_vector_db() -> VectorDBAdapter:
    return _build("vector_db")


def reset_factory() -> None:
    """Clear all cached adapter instances.

    Intended for tests that change ``CLOUD_TARGET`` between cases.
    """
    for getter in (
        get_storage,
        get_queue,
        get_secrets,
        get_audit_log,
        get_scheduler,
        get_notification,
        get_vector_db,
    ):
        getter.cache_clear()
