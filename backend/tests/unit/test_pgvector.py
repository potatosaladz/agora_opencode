"""Static and validation checks for the pgvector migration and adapter."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import MetaData
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.adapters.pgvector.vector_store import (
    PostgresKnowledgeVectorIndex,
    PostgresVectorStore,
    _is_transient_database_error,
    register_pgvector_metadata,
)
from app.db.base import Base
from app.domain.knowledge import KnowledgeVectorIndex
from app.ports.data import VectorItem
from app.ports.errors import PermanentPortError
from tests.traceability import req


@req("NFR-016")
async def test_adapter_rejects_invalid_input_before_database_access() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    store = PostgresVectorStore(engine, uuid4())
    item = VectorItem(
        chunk_id="chunk",
        document_id="document",
        source_id="source",
        content_hash="sha256:test",
        vector=[1.0, 0.0],
    )

    with pytest.raises(PermanentPortError, match="1536 dimensions"):
        await store.upsert("namespace", [item])
    with pytest.raises(PermanentPortError, match="explicit namespace"):
        await store.query("", [0.0] * 1536, k=1, filters={}, min_score=0.0)
    await engine.dispose()


@req("NFR-016")
def test_migration_creates_cosine_ivfflat_and_forced_rls() -> None:
    migration = (
        Path(__file__).parents[2] / "alembic" / "versions" / "20260904_0002_pgvector.py"
    ).read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration
    assert 'postgresql_using="ivfflat"' in migration
    assert '"embedding": "vector_cosine_ops"' in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "current_setting('app.workspace_id', true)" in migration


@req("NFR-016")
def test_knowledge_vector_metadata_has_typed_chain_and_adapter_contract() -> None:
    engine = create_async_engine("postgresql+asyncpg://unused:unused@localhost/unused")
    index = PostgresKnowledgeVectorIndex(engine, UUID(int=1))
    assert isinstance(index, KnowledgeVectorIndex)

    metadata = MetaData()
    for source_table in Base.metadata.tables.values():
        source_table.to_metadata(metadata)
    table = register_pgvector_metadata(metadata)
    foreign_keys = {fk.name: fk for fk in table.foreign_key_constraints}
    assert foreign_keys["fk_vector_items_chunk_document"].column_keys == [
        "workspace_id",
        "chunk_uuid",
        "document_uuid",
    ]
    assert foreign_keys["fk_vector_items_document_source"].column_keys == [
        "workspace_id",
        "document_uuid",
        "source_uuid",
    ]
    assert foreign_keys["fk_vector_items_source_namespace"].column_keys == [
        "workspace_id",
        "source_uuid",
        "namespace_id",
    ]
    assert "knowledge_identity_complete" in {constraint.name for constraint in table.constraints}


@req("NFR-016")
@pytest.mark.parametrize("sqlstate", ["40001", "40P01"])
def test_concurrency_database_errors_are_transient(sqlstate: str) -> None:
    error = cast(
        DBAPIError,
        SimpleNamespace(
            connection_invalidated=False,
            orig=SimpleNamespace(sqlstate=sqlstate),
        ),
    )

    assert _is_transient_database_error(error)
