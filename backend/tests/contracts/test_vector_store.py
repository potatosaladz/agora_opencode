"""Offline behavioral contract for every `VectorStore` implementation."""

from __future__ import annotations

import pytest

from app.adapters.inmemory.vector_store import InMemoryVectorStore
from app.ports.data import VectorItem
from app.ports.errors import PermanentPortError
from tests.traceability import req

pytestmark = pytest.mark.contract


def _item(chunk_id: str, vector: list[float], *, topic: str = "a") -> VectorItem:
    return VectorItem(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        source_id=f"source-{chunk_id}",
        content_hash=f"sha256:{chunk_id}",
        vector=vector,
        metadata={"topic": topic},
    )


@req("FR-404", "FR-405")
async def test_exact_cosine_filtering_upsert_and_deterministic_ties() -> None:
    store = InMemoryVectorStore()
    await store.upsert(
        "alpha",
        [_item("b", [1.0, 0.0]), _item("a", [1.0, 0.0]), _item("c", [0.0, 1.0], topic="b")],
    )
    await store.upsert("alpha", [_item("b", [0.0, 1.0])])

    hits = await store.query("alpha", [1.0, 0.0], k=10, filters={"topic": "a"}, min_score=0.5)

    assert [hit.chunk_id for hit in hits] == ["a"]
    assert hits[0].score == pytest.approx(1.0)


@req("FR-404", "FR-405")
async def test_namespace_isolation_delete_and_invalid_arguments() -> None:
    store = InMemoryVectorStore()
    await store.upsert("alpha", [_item("a", [1.0, 0.0])])
    await store.upsert("beta", [_item("b", [1.0, 0.0])])

    assert await store.delete_namespace("alpha") == 1
    assert await store.query("alpha", [1.0, 0.0], k=1, filters={}, min_score=-1.0) == []
    assert [
        hit.chunk_id
        for hit in await store.query("beta", [1.0, 0.0], k=1, filters={}, min_score=-1.0)
    ] == ["b"]
    with pytest.raises(PermanentPortError):
        await store.query("", [1.0, 0.0], k=1, filters={}, min_score=0.0)
    with pytest.raises(PermanentPortError):
        await store.query("beta", [1.0, 0.0], k=0, filters={}, min_score=0.0)
