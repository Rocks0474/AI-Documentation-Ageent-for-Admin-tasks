"""Layer 1 — the nine HR agents.

Cloud-agnostic by construction: nothing under ``agents/`` may import a
cloud-provider SDK (enforced in CI by ``check-layer-1-purity``). Agents depend
only on ``adapters.base.*``, ``schemas.*``, ``anthropic``, and approved
libraries.
"""
