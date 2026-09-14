"""Redis `Cache` adapter. ADR-009: Redis is ephemeral and holds **no durable truth**.

The adapter enforces that boundary rather than merely agreeing to it:

* `set` refuses `ttl_s <= 0`. Redis has no "no expiry" path through this class, so an
  object cannot become accidentally durable.
* `increment` creates the window with `SET ... NX EX`, never with a bare `INCR` followed by
  an `EXPIRE`. The two-command version has a crash window that leaves a key with no TTL —
  exactly the durable-state accident ADR-009 forbids, and one that only appears under a
  failure, which is the worst time to discover your cache is a database.
* Every driver exception is mapped: connection and timeout faults are `TransientPortError`,
  everything the server rejected on the merits is `PermanentPortError`. No `redis.exceptions.*`
  escapes this module (`docs/PORTS.md` §0).

Timeouts are carried on the client (`socket_timeout`), so no call can wait unboundedly.
"""

from __future__ import annotations

from typing import Any, cast

import redis.asyncio as aioredis
from redis.exceptions import AuthenticationError, RedisError, ResponseError
from redis.exceptions import ConnectionError as RedisConnError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.ports.data import Cache
from app.ports.errors import PermanentPortError, TransientPortError
from app.ports.health import HealthStatus

__all__ = ["RedisCache"]

_PORT = "cache"
_MAX_TTL_S = 24 * 60 * 60


class RedisCache:
    """`Cache` over a Redis connection pool."""

    def __init__(
        self,
        url: str,
        *,
        socket_timeout_s: float = 2.0,
        socket_connect_timeout_s: float = 2.0,
        max_connections: int = 25,
    ) -> None:
        self._url = url
        self._client: Any = aioredis.from_url(
            url,
            socket_timeout=socket_timeout_s,
            socket_connect_timeout=socket_connect_timeout_s,
            health_check_interval=30,
            decode_responses=False,
            max_connections=max_connections,
        )

    async def get(self, key: str) -> bytes | None:
        return cast(bytes | None, await self._call(self._client.get(key)))

    async def set(self, key: str, value: bytes, *, ttl_s: int) -> None:
        if not 0 < ttl_s <= _MAX_TTL_S:
            raise PermanentPortError(
                f"cache entries require a TTL from 1 to {_MAX_TTL_S}s, got {ttl_s}s "
                f"for {key!r}; Redis must never become durable storage (ADR-009)",
                port=_PORT,
            )
        await self._call(self._client.set(key, bytes(value), ex=ttl_s))

    async def delete(self, key: str) -> None:
        await self._call(self._client.delete(key))

    async def increment(self, key: str, *, ttl_s: int) -> int:
        if not 0 < ttl_s <= _MAX_TTL_S:
            raise PermanentPortError(
                f"rate-limit windows require a TTL from 1 to {_MAX_TTL_S}s, "
                f"got {ttl_s}s for {key!r}",
                port=_PORT,
            )
        # NX + EX in one command: the window's deadline is established atomically with the
        # window's existence, and a later increment never extends it.
        await self._call(self._client.set(key, 0, ex=ttl_s, nx=True))
        return int(await self._call(self._client.incr(key)))

    async def health(self) -> HealthStatus:
        try:
            await self._client.ping()
        except RedisError:
            # Any fault is "not ready", never "not live": restarting this process cannot fix
            # Redis, so a dependency failure must not make the orchestrator kill us (ADR-020).
            return HealthStatus.DOWN
        return HealthStatus.OK

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, coro: Any) -> Any:
        """Await one command, translating driver faults into port faults."""
        try:
            return await coro
        except (RedisConnError, RedisTimeoutError, TimeoutError) as exc:
            raise TransientPortError(f"redis unreachable: {exc}", port=_PORT, cause=exc) from exc
        except (AuthenticationError, ResponseError) as exc:
            # Wrong password and malformed command will fail identically on the next attempt.
            raise PermanentPortError(
                f"redis rejected the command: {exc}", port=_PORT, cause=exc
            ) from exc
        except RedisError as exc:
            raise TransientPortError(f"redis fault: {exc}", port=_PORT, cause=exc) from exc


#: mypy-checked structural conformance; see `inmemory/cache.py`.
_CACHE_PORT: type[Cache] = RedisCache
