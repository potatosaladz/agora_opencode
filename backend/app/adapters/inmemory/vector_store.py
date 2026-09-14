"""In-memory `VectorStore` with exact cosine search.

Two properties are load-bearing here, because this adapter is what the pgvector adapter's
tests are compared against (`tests/contracts/test_vector_store.py` runs one suite over both):

* **Namespace isolation fails closed.** A query for an unknown or empty namespace returns
  nothing rather than "everything that looked similar". `docs/RAG_ARCHITECTURE.md` §5.1 makes
  an implicit all-namespaces read a security defect, so the default has to be the empty set.
* **Ordering is total and deterministic.** Ties break on `chunk_id`, never on insertion order
  or dict iteration, so two runs over the same vectors return the same list. Phase 5's
  reproducibility gate depends on this being true of the *port*, not merely of Postgres.

Exact search is O(n·d) and unindexed on purpose: correctness of the contract is what is
being tested, not recall at scale.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.ports.data import VectorHit, VectorItem, VectorStore
from app.ports.errors import PermanentPortError
from app.ports.health import HealthStatus

__all__ = ["InMemoryVectorStore", "cosine_similarity"]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine of the angle between two equal-length vectors, in [-1, 1].

    Zero-magnitude vectors score 0.0 rather than raising: an embedding of an empty chunk is
    a real occurrence, and "no similarity" is the right answer for it.
    """
    if len(a) != len(b):
        raise PermanentPortError(
            f"vector dimensions differ: {len(a)} vs {len(b)}", port="vector_store"
        )
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass(frozen=True)
class _Row:
    item: VectorItem
    digest: str


class InMemoryVectorStore:
    """Exact cosine search over a namespace-partitioned mapping."""

    def __init__(self) -> None:
        self._namespaces: dict[str, dict[str, _Row]] = {}
        self._dimensions: dict[str, int] = {}

    async def upsert(self, namespace: str, items: Sequence[VectorItem]) -> None:
        self._require_namespace(namespace)
        if not items:
            return
        bucket = self._namespaces.setdefault(namespace, {})
        for item in items:
            dims = len(item.vector)
            if dims == 0:
                raise PermanentPortError(
                    "zero-length vectors are not storable", port="vector_store"
                )
            expected = self._dimensions.setdefault(namespace, dims)
            if dims != expected:
                raise PermanentPortError(
                    f"namespace {namespace!r} holds {expected}-d vectors, "
                    f"chunk {item.chunk_id!r} has {dims}",
                    port="vector_store",
                )
            # Re-upserting a chunk_id replaces it: a re-indexed document must not leave two
            # vectors behind, and the record of what was retrieved lives in Postgres anyway.
            bucket[item.chunk_id] = _Row(item=item, digest=item.content_hash)

    async def query(
        self,
        namespace: str,
        vector: Sequence[float],
        *,
        k: int,
        filters: Mapping[str, Any],
        min_score: float,
    ) -> Sequence[VectorHit]:
        self._require_namespace(namespace)
        if k <= 0:
            raise PermanentPortError(f"k must be positive, got {k}", port="vector_store")
        bucket = self._namespaces.get(namespace, {})
        if not bucket:
            return []
        expected = self._dimensions.get(namespace)
        if expected is not None and len(vector) != expected:
            raise PermanentPortError(
                f"query vector has {len(vector)} dims, namespace {namespace!r} "
                f"is indexed at {expected}",
                port="vector_store",
            )

        scored: list[tuple[float, VectorHit]] = []
        for row in bucket.values():
            if not _matches(row.item.metadata, filters):
                continue
            score = cosine_similarity(vector, row.item.vector)
            if score < min_score:
                continue
            scored.append(
                (
                    score,
                    VectorHit(
                        chunk_id=row.item.chunk_id,
                        document_id=row.item.document_id,
                        source_id=row.item.source_id,
                        content_hash=row.digest,
                        score=score,
                        metadata=row.item.metadata,
                    ),
                )
            )
        # -score first, then chunk_id, so equal scores never depend on iteration order.
        scored.sort(key=lambda pair: (-pair[0], pair[1].chunk_id))
        return [hit for _, hit in scored[:k]]

    async def delete_namespace(self, namespace: str) -> int:
        bucket = self._namespaces.pop(namespace, None)
        self._dimensions.pop(namespace, None)
        return len(bucket or {})

    async def health(self) -> HealthStatus:
        return HealthStatus.OK

    async def close(self) -> None:
        self._namespaces.clear()
        self._dimensions.clear()

    def _require_namespace(self, namespace: str) -> None:
        if not namespace or not namespace.strip():
            raise PermanentPortError(
                "an explicit namespace is required; retrieval never defaults to all "
                "namespaces (docs/RAG_ARCHITECTURE.md §5.1)",
                port="vector_store",
            )


def _matches(metadata: Mapping[str, Any], filters: Mapping[str, Any]) -> bool:
    """Exact-equality metadata filtering: the subset of pgvector's `@>` both adapters share."""
    return all(metadata.get(key) == value for key, value in filters.items())


#: mypy-checked structural conformance; see `cache.py` for why this is a type alias.
_VECTOR_STORE_PORT: type[VectorStore] = InMemoryVectorStore
