"""Offline behavioral contract for cache adapters."""

from __future__ import annotations

import pytest

from app.adapters.inmemory.cache import InMemoryCache
from app.ports.errors import PermanentPortError
from tests.traceability import req

pytestmark = pytest.mark.contract


@req("NFR-016")
async def test_cache_round_trip_and_delete() -> None:
    cache = InMemoryCache()
    await cache.set("key", b"value", ttl_s=30)

    assert await cache.get("key") == b"value"
    await cache.delete("key")
    assert await cache.get("key") is None


@req("NFR-016")
@pytest.mark.parametrize("ttl_s", [-1, 0, 86_401])
async def test_all_write_paths_reject_ttl_outside_ephemeral_range(ttl_s: int) -> None:
    cache = InMemoryCache()

    with pytest.raises(PermanentPortError, match="TTL from 1 to 86400"):
        await cache.set("value", b"data", ttl_s=ttl_s)
    with pytest.raises(PermanentPortError, match="TTL from 1 to 86400"):
        await cache.increment("counter", ttl_s=ttl_s)
    assert cache.keys() == []


@req("NFR-016")
async def test_increment_uses_a_fixed_window() -> None:
    cache = InMemoryCache()
    now = 100.0
    cache._clock = lambda: now

    assert await cache.increment("counter", ttl_s=10) == 1
    deadline = cache._entries["counter"].expires_at
    now = 105.0
    assert await cache.increment("counter", ttl_s=10) == 2
    assert cache._entries["counter"].expires_at == deadline
    now = 111.0
    assert await cache.increment("counter", ttl_s=10) == 1
    assert cache._entries["counter"].expires_at == 121.0
