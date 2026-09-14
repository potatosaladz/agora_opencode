"""Live PostgreSQL evidence for durable retry-safe source ingestion."""

from __future__ import annotations

import asyncio
import hashlib
import os
from uuid import UUID, uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.adapters.ingestion import parse_document
from app.adapters.inmemory.object_store import InMemoryObjectStore
from app.application.ingestion import SourceIngestionRunner
from app.db.ingestion import SqlAlchemyIngestionCheckpointStore
from app.db.session import Database
from app.domain.ingestion_activity import (
    IngestionFailureCode,
    IngestionFailureKind,
    IngestionStage,
    IngestionStageState,
    IngestSourceInput,
)
from app.ports.errors import PermanentPortError
from tests.traceability import req

_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DATABASE_URL, reason="TEST_DATABASE_URL not configured"),
]


def _command(
    workspace_id: UUID,
    namespace_id: UUID,
    *,
    operation_id: UUID,
    source_id: UUID,
    document_id: UUID,
    media_type: str = "text/plain",
    title: str = "Durable fixture",
) -> IngestSourceInput:
    body = b"Section\n\nDurable ingestion fixture text."
    content_hash = "sha256:" + hashlib.sha256(body).hexdigest()
    return IngestSourceInput(
        protocol_version="1.0",
        kind="source_ingestion",
        operation_id=operation_id,
        workspace_id=workspace_id,
        namespace_id=namespace_id,
        source_id=source_id,
        document_id=document_id,
        title=title,
        citation="Durable fixture citation",
        media_type=media_type,
        declared_content_hash=content_hash,
        size_bytes=len(body),
        object_bucket="artifacts",
        object_key=f"sources/{content_hash.removeprefix('sha256:')}",
    )


@req("FR-401", "FR-403", "FR-406", "NFR-001")
async def test_ingestion_checkpoint_retry_rls_failure_and_downstream_lifecycle() -> None:
    assert _DATABASE_URL is not None
    engine = create_async_engine(_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", _DATABASE_URL.replace("%", "%%"))
    config.attributes["database_url_overridden"] = True
    await asyncio.to_thread(alembic_command.upgrade, config, "head")

    workspace_id, other_workspace_id = uuid4(), uuid4()
    namespace_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(text("DROP ROLE IF EXISTS agora_t503_app"))
        await connection.execute(text("CREATE ROLE agora_t503_app NOLOGIN"))
        await connection.execute(text("GRANT USAGE ON SCHEMA public TO agora_t503_app"))
        await connection.execute(
            text("GRANT SELECT ON knowledge_ingestion_operations TO agora_t503_app")
        )
        await connection.execute(
            text(
                "INSERT INTO workspaces (id, slug, name) VALUES "
                "(:workspace, 'ingestion-live', 'Ingestion Live'), "
                "(:other, 'ingestion-other', 'Ingestion Other')"
            ),
            {"workspace": workspace_id, "other": other_workspace_id},
        )
        await connection.execute(
            text(
                "INSERT INTO knowledge_namespaces (id, workspace_id, tier, name) "
                "VALUES (:id, :workspace, 'WORKSPACE', 'live')"
            ),
            {"id": namespace_id, "workspace": workspace_id},
        )

    database = Database(engine)
    store = SqlAlchemyIngestionCheckpointStore(database)
    objects = InMemoryObjectStore()
    runner = SourceIngestionRunner(store, objects, parse_document, bucket="artifacts")
    operation_id, source_id, document_id = uuid4(), uuid4(), uuid4()
    item = _command(
        workspace_id,
        namespace_id,
        operation_id=operation_id,
        source_id=source_id,
        document_id=document_id,
    )
    await objects.put(
        item.object_bucket,
        item.object_key,
        b"Section\n\nDurable ingestion fixture text.",
        content_type=item.media_type,
        metadata={"content-hash": item.declared_content_hash},
    )

    first, simultaneous_retry = await asyncio.gather(runner.run(item), runner.run(item))
    retry = await runner.run(item)
    assert simultaneous_retry == first
    assert retry == first
    assert first.chunk_ids
    assert first.embed_state is IngestionStageState.PENDING
    assert first.index_state is IngestionStageState.PENDING

    async with database.session(workspace_id) as session:
        counts = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM knowledge_ingestion_operations), "
                    "(SELECT count(*) FROM sources), (SELECT count(*) FROM documents), "
                    "(SELECT count(*) FROM chunks)"
                )
            )
        ).one()
        assert counts == (1, 1, 1, len(first.chunk_ids))
        attempt_count = await session.scalar(
            text("SELECT attempt_count FROM knowledge_ingestion_operations WHERE id = :id"),
            {"id": operation_id},
        )
        assert attempt_count == 2

    conflicting = item.model_copy(update={"title": "Conflicting retry"})
    with pytest.raises(PermanentPortError, match="conflicts"):
        await runner.run(conflicting)

    embed_failed = await store.record_downstream_stage(
        workspace_id,
        operation_id,
        stage=IngestionStage.EMBED,
        state=IngestionStageState.FAILED,
        code=IngestionFailureCode.EMBEDDING_FAILED,
        kind=IngestionFailureKind.TRANSIENT,
        detail="embedding dependency unavailable",
    )
    assert embed_failed.failure_stage is IngestionStage.EMBED
    assert embed_failed.failure_detail == "embedding dependency unavailable"
    async with database.session(workspace_id) as session:
        assert (
            await session.scalar(
                text("SELECT status FROM sources WHERE id = :id"), {"id": source_id}
            )
            == "READY"
        )
    await store.record_downstream_stage(
        workspace_id,
        operation_id,
        stage=IngestionStage.EMBED,
        state=IngestionStageState.RUNNING,
    )
    embedded = await store.record_downstream_stage(
        workspace_id,
        operation_id,
        stage=IngestionStage.EMBED,
        state=IngestionStageState.SUCCEEDED,
    )
    assert embedded.embed_state is IngestionStageState.SUCCEEDED
    indexed = await store.record_downstream_stage(
        workspace_id,
        operation_id,
        stage=IngestionStage.INDEX,
        state=IngestionStageState.SUCCEEDED,
    )
    assert indexed.index_state is IngestionStageState.SUCCEEDED
    async with database.session(workspace_id) as session:
        assert (
            await session.scalar(
                text("SELECT status FROM sources WHERE id = :id"), {"id": source_id}
            )
            == "READY"
        )
        assert (
            await session.scalar(
                text("SELECT status FROM documents WHERE id = :id"), {"id": document_id}
            )
            == "READY"
        )

    unsupported_operation, unsupported_source = uuid4(), uuid4()
    unsupported = _command(
        workspace_id,
        namespace_id,
        operation_id=unsupported_operation,
        source_id=unsupported_source,
        document_id=uuid4(),
        media_type="image/png",
    )
    await objects.put(
        unsupported.object_bucket,
        unsupported.object_key,
        b"Section\n\nDurable ingestion fixture text.",
        content_type=unsupported.media_type,
        metadata={"content-hash": unsupported.declared_content_hash},
    )
    with pytest.raises(PermanentPortError, match="unsupported"):
        await runner.run(unsupported)
    async with database.session(workspace_id) as session:
        failure = (
            await session.execute(
                text(
                    "SELECT failure_stage, failure_code, failure_kind, failure_detail "
                    "FROM knowledge_ingestion_operations WHERE id = :id"
                ),
                {"id": unsupported_operation},
            )
        ).one()
        assert failure == (
            "PARSE",
            IngestionFailureCode.UNSUPPORTED_MEDIA_TYPE.value,
            IngestionFailureKind.PERMANENT.value,
            "declared media type is not supported",
        )
        assert (
            await session.scalar(
                text("SELECT status FROM sources WHERE id = :id"), {"id": unsupported_source}
            )
            == "FAILED"
        )

    async with engine.begin() as connection:
        forced = await connection.scalar(
            text(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                "WHERE relname = 'knowledge_ingestion_operations'"
            )
        )
        assert forced is True

    async with engine.begin() as connection:
        await connection.execute(text("SET LOCAL ROLE agora_t503_app"))
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(other_workspace_id)},
        )
        other_count = await connection.scalar(
            text("SELECT count(*) FROM knowledge_ingestion_operations")
        )
        assert other_count == 0

    await asyncio.to_thread(alembic_command.check, config)
    await asyncio.to_thread(alembic_command.downgrade, config, "20260906_0010")
    async with engine.begin() as connection:
        assert (
            await connection.scalar(text("SELECT to_regclass('knowledge_ingestion_operations')"))
            is None
        )
    await asyncio.to_thread(alembic_command.upgrade, config, "head")
    await asyncio.to_thread(alembic_command.check, config)
    await objects.close()
    await database.close()
