"""AWS adapter implementations (Layer 3).

Active when ``CLOUD_TARGET=AWS``. ``boto3`` is imported lazily inside
``get_adapter()`` / client builders only — never at module top — so the adapter
classes import and unit-test without ``boto3`` installed, and Layer 1
(``agents/``) stays cloud-agnostic.

The same Docker image runs here as on GCP; only ``CLOUD_TARGET`` (and the
target-specific env vars) differ. Each module exposes a zero-argument
``get_adapter()`` (the factory contract). Blocking SDK calls run through
``asyncio.to_thread``.
"""
