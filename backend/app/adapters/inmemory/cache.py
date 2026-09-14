"""In-memory `Cache`. Used by tests and by `CACHE=inmemory` for offline development.

The one behaviour worth stating: a key without a TTL is rejected. `docs/ARCHITECTURE.md`
§2.1 says Redis "must never own any durable truth", and the way that actually fails in
practice is someone calling `set(key, value)` with no expiry and quietly making the cache
a database. Making the argument mandatory — and rejecting `ttl_s <= 0` — is the enforcement.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.ports.data import Cache
from app.ports.errors import PermanentPortError
from app.ports.health import HealthStatus

__all__ = ["InMemoryCache"]

_MAX_TTL_S = 24 * 60 * 60


@dataclass(frozen=True)
class _Entry:
    value: bytes
    expires_at: float


class InMemoryCache:
    """A cache that forgets, on schedule."""

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._clock = time.monotonic

    async def get(self, key: str) -> bytes | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            self._entries.pop(key, None)
            return None
        return entry.value

    async def set(self, key: str, value: bytes, *, ttl_s: int) -> None:
        if not 0 < ttl_s <= _MAX_TTL_S:
            raise PermanentPortError(
                f"cache entries require a TTL from 1 to {_MAX_TTL_S}s, got {ttl_s}s "
                f"for {key!r}; the cache must never become durable storage",
                port="cache",
            )
        self._entries[key] = _Entry(value=bytes(value), expires_at=self._clock() + ttl_s)

    async def delete(self, key: str) -> None:
        self._entries.pop(key, None)

    async def increment(self, key: str, *, ttl_s: int) -> int:
        """Fixed-window counter for rate limiting.

        The TTL starts on the first increment of a window and is never extended, or a
        client that keeps hitting the endpoint would push its own window boundary out
        forever and the limit would never trip.
        """
        if not 0 < ttl_s <= _MAX_TTL_S:
            raise PermanentPortError(
                f"rate-limit windows require a TTL from 1 to {_MAX_TTL_S}s, "
                f"got {ttl_s}s for {key!r}",
                port="cache",
            )
        current = self._entries.get(key)
        now = self._clock()
        if current is None or current.expires_at <= now:
            self._entries[key] = _Entry(value=b"1", expires_at=now + ttl_s)
            return 1
        nxt = int(current.value or b"0") + 1
        self._entries[key] = _Entry(value=str(nxt).encode(), expires_at=current.expires_at)
        return nxt

    async def health(self) -> HealthStatus:
        return HealthStatus.OK

    async def close(self) -> None:
        self._entries.clear()

    def keys(self) -> list[str]:
        """Live keys only. Exists so a test can assert nothing was stored without a TTL."""
        now = self._clock()
        return [k for k, e in self._entries.items() if e.expires_at > now]


#: Structural conformance, checked by mypy at `mypy` time rather than at runtime. Assigning
#: the class to `type[Cache]` makes "this adapter implements the port" a compile-time fact;
#: the contract suite in `tests/contracts/` makes it an observed one.
_CACHE_PORT: type[Cache] = InMemoryCache
