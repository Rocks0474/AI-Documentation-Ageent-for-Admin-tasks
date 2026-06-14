"""LOCAL adapter implementations (Layer 3, development target).

These back the system when ``CLOUD_TARGET=LOCAL`` — used for local development,
docker-compose, and the unit/integration test suites. They are in-memory or
local-filesystem only and import no cloud-provider SDK.

Each module exposes a zero-argument ``get_adapter()`` returning a process-wide
singleton, which is the contract ``adapters.factory`` relies on.
"""
