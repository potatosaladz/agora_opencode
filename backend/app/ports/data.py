"""`VectorStore` and `Cache` ports — `docs/PORTS.md` §9 and `docs/SECURITY.md` §6.

Both carry a `namespace`. Namespace isolation is enforced at query time, not by
convention: `docs/RAG_ARCHITECTURE.md` §5.1 requires that a request without an explicit
namespace set is **rejected**, never defaulted to "all".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.ports.health import HealthStatus

__all__ = ["Cache", "VectorHit", "VectorItem", "VectorStore"]


class VectorItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    document_id: str
    source_id: str
    content_hash: str = Field(description="sha256 of the chunk text; lets a hit be verified")
    vector: Sequence[float]
    metadata: Mapping[str, Any] = Field(default_factory=dict)


class VectorHit(BaseModel):
    """A retrieval hit.

    `source_id` and `content_hash` are mandatory parts of the contract, not conveniences:
    `docs/RAG_ARCHITECTURE.md` §5.2 requires every citation to resolve to a real stored
    source, and the Phase 5 exit gate fails a chunk that cannot be traced to a digest.
    """

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    document_id: str
    source_id: str
    content_hash: str
    score: float
    metadata: Mapping[str, Any] = Field(default_factory=dict)


@runtime_checkable
class VectorStore(Protocol):
    """Embedding storage and similarity search. Adapter: `pgvector` (ADR-002)."""

    async def upsert(self, namespace: str, items: Sequence[VectorItem]) -> None: ...

    async def query(
        self,
        namespace: str,
        vector: Sequence[float],
        *,
        k: int,
        filters: Mapping[str, Any],
        min_score: float,
    ) -> Sequence[VectorHit]: ...

    async def delete_namespace(self, namespace: str) -> int: ...

    async def health(self) -> HealthStatus: ...


@runtime_checkable
class Cache(Protocol):
    """Ephemeral key/value plus fixed-window rate limiting.

    Redis is the adapter, and `docs/ARCHITECTURE.md` §2.1 states it "must never own any
    durable truth". That is a testable property, not a comment: the contract suite asserts
    that every key written here carries a TTL, so an object cannot quietly become durable
    by being left in Redis (T1-06 acceptance criterion).
    """

    async def get(self, key: str) -> bytes | None: ...

    async def set(self, key: str, value: bytes, *, ttl_s: int) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def increment(self, key: str, *, ttl_s: int) -> int: ...

    async def health(self) -> HealthStatus: ...

    async def close(self) -> None: ...
