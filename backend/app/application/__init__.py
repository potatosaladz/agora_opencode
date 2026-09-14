"""Application layer: use cases and the deterministic coordinator.

Imports `app.domain`, `app.ports`, `app.common`. Owns retry and timeout policy,
which adapters explicitly do not (docs/PORTS.md §0).
"""
