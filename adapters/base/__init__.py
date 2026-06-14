"""Abstract adapter interfaces (Layer 2).

This is the only adapter package Layer 1 (``agents/``) may import. Nothing here
imports a cloud-provider SDK; concrete implementations live in
``adapters.local`` / ``adapters.gcp`` / ``adapters.aws`` and are selected by
``adapters.factory``.
"""

from adapters.base.audit_log import AuditEntry, AuditLogAdapter
from adapters.base.notification import (
    Notification,
    NotificationAdapter,
    NotificationChannel,
)
from adapters.base.queue import QueueAdapter, QueueMessage
from adapters.base.scheduler import ScheduledJob, SchedulerAdapter
from adapters.base.secrets import SecretNotFoundError, SecretsAdapter
from adapters.base.storage import DataZone, StorageAdapter
from adapters.base.vector_db import (
    VectorDBAdapter,
    VectorDocument,
    VectorQueryResult,
)

__all__ = [
    # audit_log
    "AuditEntry",
    "AuditLogAdapter",
    # storage
    "DataZone",
    "StorageAdapter",
    # queue
    "QueueAdapter",
    "QueueMessage",
    # secrets
    "SecretsAdapter",
    "SecretNotFoundError",
    # scheduler
    "ScheduledJob",
    "SchedulerAdapter",
    # notification
    "Notification",
    "NotificationAdapter",
    "NotificationChannel",
    # vector_db
    "VectorDBAdapter",
    "VectorDocument",
    "VectorQueryResult",
]
