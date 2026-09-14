"""Redis acceptance proof: every write is ephemeral and rate windows are fixed."""

from __future__ import annotations

import asyncio
import os

import pytest
import redis.asyncio as aioredis

from app.adapters.redis.cache import RedisCache
from app.ports.errors import PermanentPortError
from app.ports.health import HealthStatus
from tests.traceability import req

_REDIS_URL = os.getenv("TEST_REDIS_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _REDIS_URL, reason="TEST_REDIS_URL is not configured"),
]


@req("NFR-016")
async def test_redis_cache_never_writes_durable_keys() -> None:
    assert _REDIS_URL is not None
    inspector = aioredis.from_url(_REDIS_URL, decode_responses=False)
    await inspector.flushdb()
    assert await inspector.config_get("appendonly") == {"appendonly": "no"}
    assert await inspector.config_get("save") == {"save": ""}
    cache = RedisCache(_REDIS_URL)

    await cache.set("cache:value", b"payload", ttl_s=2)
    assert await cache.get("cache:value") == b"payload"
    value_ttl = await inspector.ttl("cache:value")
    assert 0 < value_ttl <= 2

    assert await cache.increment("rate:actor", ttl_s=3) == 1
    first_ttl = await inspector.pttl("rate:actor")
    await asyncio.sleep(0.05)
    assert await cache.increment("rate:actor", ttl_s=30) == 2
    second_ttl = await inspector.pttl("rate:actor")
    assert 0 < second_ttl <= first_ttl

    for key in await inspector.keys("*"):
        assert await inspector.ttl(key) > 0

    with pytest.raises(PermanentPortError, match="TTL from 1 to 86400"):
        await cache.set("durable:value", b"forbidden", ttl_s=0)
    with pytest.raises(PermanentPortError, match="TTL from 1 to 86400"):
        await cache.increment("durable:counter", ttl_s=0)
    assert not await inspector.exists("durable:value", "durable:counter")

    await cache.set("expires", b"soon", ttl_s=1)
    await asyncio.sleep(1.1)
    assert await cache.get("expires") is None
    assert await cache.health() is HealthStatus.OK

    await cache.delete("cache:value")
    assert await cache.get("cache:value") is None
    await cache.close()
    await inspector.aclose()
