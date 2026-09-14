"""Live PostgreSQL acceptance evidence for Phase 5 knowledge persistence."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.knowledge import SqlAlchemyKnowledgeRepository
from app.db.session import Database
from app.domain.knowledge import (
    DocumentRecord,
    KnowledgeChunk,
    KnowledgeNamespace,
    NamespaceCapability,
    NamespaceGrant,
    NamespaceSubjectKind,
    NamespaceTier,
    SourceRecord,
)
from tests.traceability import req

_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DATABASE_URL, reason="TEST_DATABASE_URL not configured"),
]


@req("FR-405", "FR-407", "NFR-010")
async def test_knowledge_schema_rls_composite_fk_and_immutable_identity() -> None:
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
    namespace_a, namespace_b = uuid4(), uuid4()
    async with engine.begin() as connection:
        await connection.execute(text("DROP ROLE IF EXISTS agora_t502_app"))
        await connection.execute(text("CREATE ROLE agora_t502_app NOLOGIN"))
        await connection.execute(text("GRANT USAGE ON SCHEMA public TO agora_t502_app"))
        await connection.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE ON knowledge_namespaces, "
                "knowledge_namespace_grants, sources, documents, chunks TO agora_t502_app"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO workspaces (id, slug, name) VALUES "
                "(:a, 'knowledge-a', 'Knowledge A'), (:b, 'knowledge-b', 'Knowledge B')"
            ),
            {"a": workspace_a, "b": workspace_b},
        )
        await connection.execute(
            text(
                "INSERT INTO knowledge_namespaces (id, workspace_id, tier, name) VALUES "
                "(:a, :workspace_a, 'WORKSPACE', 'a'), "
                "(:b, :workspace_b, 'WORKSPACE', 'b')"
            ),
            {
                "a": namespace_a,
                "b": namespace_b,
                "workspace_a": workspace_a,
                "workspace_b": workspace_b,
            },
        )

    repository_namespace_id = uuid4()
    repository_grant_id = uuid4()
    repository_source_id = uuid4()
    repository_document_id = uuid4()
    repository_chunk_id = uuid4()
    now = datetime(2026, 9, 6, 12, tzinfo=UTC)
    database = Database(engine)
    async with database.session(workspace_a) as session:
        repository = SqlAlchemyKnowledgeRepository(session)
        await repository.add_namespace(
            KnowledgeNamespace(
                id=repository_namespace_id,
                workspace_id=workspace_a,
                tier=NamespaceTier.WORKSPACE,
                name="repository",
            )
        )
        await repository.add_grant(
            NamespaceGrant(
                id=repository_grant_id,
                workspace_id=workspace_a,
                namespace_id=repository_namespace_id,
                subject_kind=NamespaceSubjectKind.WORKSPACE,
                subject_id=workspace_a,
                capability=NamespaceCapability.READ,
                valid_from=now,
            )
        )
        await repository.add_source(
            SourceRecord(
                id=repository_source_id,
                workspace_id=workspace_a,
                namespace_id=repository_namespace_id,
                title="Repository fixture",
                citation="Repository citation",
                object_ref="objects/repository",
                content_hash="sha256:" + "d" * 64,
                media_type="text/plain",
                size_bytes=10,
            )
        )
        await repository.add_document(
            DocumentRecord(
                id=repository_document_id,
                workspace_id=workspace_a,
                source_id=repository_source_id,
                parser="txt",
                parser_version="1",
            )
        )
        await repository.add_chunks(
            (
                KnowledgeChunk(
                    id=repository_chunk_id,
                    workspace_id=workspace_a,
                    document_id=repository_document_id,
                    ordinal=0,
                    text="repository",
                    token_count=1,
                    locator={"char_start": 0, "char_end": 10},
                    content_hash="sha256:" + "e" * 64,
                    chunker_version="agora-whitespace-v1",
                ),
            )
        )
        stored_namespace = await repository.get_namespace(workspace_a, repository_namespace_id)
        stored_grant = await repository.get_grant(workspace_a, repository_grant_id)
        stored_source = await repository.get_source(workspace_a, repository_source_id)
        stored_document = await repository.get_document(workspace_a, repository_document_id)
        stored_chunk = await repository.get_chunk(workspace_a, repository_chunk_id)
        assert stored_namespace is not None
        assert stored_namespace.tier is NamespaceTier.WORKSPACE
        assert stored_grant is not None
        assert stored_grant.capability is NamespaceCapability.READ
        assert stored_source is not None
        assert stored_source.content_hash.endswith("d" * 64)
        assert stored_document is not None
        assert stored_document.parser_version == "1"
        assert stored_chunk is not None
        assert stored_chunk.document_id == repository_document_id

    async with engine.begin() as connection:
        forced_tables = set(
            (
                await connection.execute(
                    text(
                        "SELECT relname FROM pg_class WHERE relname IN "
                        "('knowledge_namespaces','knowledge_namespace_grants','sources',"
                        "'documents','chunks') AND relrowsecurity AND relforcerowsecurity"
                    )
                )
            ).scalars()
        )
        assert forced_tables == {
            "knowledge_namespaces",
            "knowledge_namespace_grants",
            "sources",
            "documents",
            "chunks",
        }

    async with engine.begin() as connection:
        await connection.execute(text("SET LOCAL ROLE agora_t502_app"))
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(workspace_b)},
        )
        assert await connection.scalar(text("SELECT count(*) FROM sources")) == 0
        assert await connection.scalar(text("SELECT count(*) FROM knowledge_namespaces")) == 1

    async with engine.begin() as connection:
        with pytest.raises(DBAPIError, match="foreign key constraint"):
            await connection.execute(
                text(
                    "INSERT INTO sources "
                    "(id, workspace_id, namespace_id, title, citation, object_ref, content_hash, "
                    "media_type, size_bytes) VALUES "
                    "(:id, :workspace, :namespace, 'Cross', 'Cross', 'objects/cross', :hash, "
                    "'text/plain', 5)"
                ),
                {
                    "id": uuid4(),
                    "workspace": workspace_b,
                    "namespace": namespace_a,
                    "hash": "sha256:" + "b" * 64,
                },
            )

    async with engine.begin() as connection:

        async def insert_invalid_workspace_grant() -> None:
            await connection.execute(
                text(
                    "INSERT INTO knowledge_namespace_grants "
                    "(id, workspace_id, namespace_id, subject_kind, subject_id, capability, "
                    "valid_from) VALUES "
                    "(:id, :workspace, :namespace, 'WORKSPACE', :foreign_workspace, 'READ', now())"
                ),
                {
                    "id": uuid4(),
                    "workspace": workspace_a,
                    "namespace": namespace_a,
                    "foreign_workspace": workspace_b,
                },
            )
            await connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

        with pytest.raises(DBAPIError, match="workspace grant subject must equal workspace"):
            await insert_invalid_workspace_grant()

    async with engine.begin() as connection:
        with pytest.raises(DBAPIError, match="provenance identity is immutable"):
            await connection.execute(
                text("UPDATE sources SET content_hash = :hash WHERE id = :id"),
                {"hash": "sha256:" + "c" * 64, "id": repository_source_id},
            )

    await asyncio.to_thread(command.check, config)
    await engine.dispose()
