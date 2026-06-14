"""GCP adapter implementations (Layer 3).

Active when ``CLOUD_TARGET=GCP``. These modules are the *only* place
``google.cloud.*`` is imported, and even here the SDK is imported lazily inside
``get_adapter()`` / client builders — never at module import time. That keeps
the adapter classes importable and unit-testable without the GCP SDKs installed,
and keeps Layer 1 (``agents/``) free of any cloud dependency.

Each module exposes a zero-argument ``get_adapter()`` (the factory contract)
that constructs the real client from environment configuration. Blocking SDK
calls are dispatched through ``asyncio.to_thread`` so the async adapter contract
is honoured.
"""
