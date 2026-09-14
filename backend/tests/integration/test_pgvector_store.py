"""PostgreSQL acceptance proof for pgvector storage, search, index, and RLS."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.adapters.pgvector.vector_store import PostgresVectorStore
from app.ports.data import VectorItem
from app.ports.health import HealthStatus
from tests.traceability import req

_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DATABASE_URL, reason="TEST_DATABASE_URL is not configured"),
]
_DIMENSIONS = 1536


def _vector(position: int) -> list[float]:
    """A deterministic unit-ish direction whose cosine decreases with position."""
    return [1.0, position / 1000.0, *([0.0] * (_DIMENSIONS - 2))]


def _item(position: int, *, topic: str = "proof") -> VectorItem:
    chunk_id = f"chunk-{position:04d}"
    return VectorItem(
        chunk_id=chunk_id,
        document_id=f"document-{position // 10:03d}",
        source_id=f"source-{position // 100:02d}",
        content_hash=f"sha256:{position:064x}",
        vector=_vector(position),
        metadata={"topic": topic, "position": position},
    )


@req("FR-404", "FR-405", "NFR-010")
async def test_pgvector_migration_and_deterministic_thousand_vector_retrieval() -> None:
    assert _DATABASE_URL is not None
    engine = create_async_engine(_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", _DATABASE_URL.replace("%", "%%"))
    config.attributes["database_url_overridden"] = True
    await asyncio.to_thread(command.upgrade, config, "head")

    workspace_a, workspace_b = uuid4(), uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO workspaces (id, slug, name) VALUES (:a, 'a', 'A'), (:b, 'b', 'B')"),
            {"a": workspace_a, "b": workspace_b},
        )
        assert await connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        )
        index_definition = await connection.scalar(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'ix_vector_items_embedding_cosine'"
            )
        )
        assert "ivfflat" in index_definition
        assert "vector_cosine_ops" in index_definition

    store_a = PostgresVectorStore(engine, workspace_a)
    store_b = PostgresVectorStore(engine, workspace_b)
    await store_a.upsert("corpus", [_item(index) for index in range(1000)])
    await store_b.upsert("corpus", [_item(0, topic="other-tenant")])

    first = await store_a.query(
        "corpus", _vector(0), k=5, filters={"topic": "proof"}, min_score=0.0
    )
    second = await store_a.query(
        "corpus", _vector(0), k=5, filters={"topic": "proof"}, min_score=0.0
    )
    expected = [f"chunk-{index:04d}" for index in range(5)]
    assert [hit.chunk_id for hit in first] == expected
    assert [hit.chunk_id for hit in second] == expected
    assert [hit.score for hit in first] == pytest.approx([hit.score for hit in second])
    assert await store_a.query("missing", _vector(0), k=5, filters={}, min_score=0.0) == []
    assert await store_a.health() is HealthStatus.OK

    replacement = _item(999)
    replacement = replacement.model_copy(update={"chunk_id": "chunk-0000"})
    await store_a.upsert("corpus", [replacement])
    replaced = await store_a.query(
        "corpus", _vector(0), k=1, filters={"topic": "proof"}, min_score=0.0
    )
    assert replaced[0].chunk_id == "chunk-0001"

    async with engine.begin() as connection:
        await connection.execute(text("DROP ROLE IF EXISTS agora_t105_app"))
        await connection.execute(text("CREATE ROLE agora_t105_app NOLOGIN"))
        await connection.execute(text("GRANT USAGE ON SCHEMA public TO agora_t105_app"))
        await connection.execute(
            text("GRANT SELECT, INSERT, UPDATE, DELETE ON vector_items TO agora_t105_app")
        )
        await connection.execute(text("SET ROLE agora_t105_app"))
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(workspace_b)},
        )
        assert await connection.scalar(text("SELECT count(*) FROM vector_items")) == 1

    assert await store_a.delete_namespace("corpus") == 1000
    assert await store_b.delete_namespace("corpus") == 1
    await engine.dispose()
