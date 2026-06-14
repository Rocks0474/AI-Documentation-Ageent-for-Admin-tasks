"""External integration stubs.

Per the architecture spec, external integrations (Panalyt, Greenhouse, GoodTime,
Deel, Arize, ...) are stubbed as no-ops first so agents can be tested
end-to-end before real API keys exist. Each stub implements the same interface
the real integration will, returning deterministic fake data, and carries a
``connected`` flag so agents can degrade gracefully when an integration is
absent. Real implementations replace these in Phase 4 (GCP) / Phase 5 (AWS).

These modules are pure Python — no cloud SDKs — so agents may import them
without violating Layer 1 purity.
"""
