"""Phase 5 knowledge domain, metadata, and repository mapping tests."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.knowledge import SqlAlchemyKnowledgeRepository
from app.db.models.knowledge import KnowledgeChunkRow, KnowledgeNamespaceRow, SourceRow
from app.domain.knowledge import (
    DocumentRecord,
    KnowledgeChunk,
    KnowledgeNamespace,
    KnowledgeRepository,
    NamespaceCapability,
    NamespaceGrant,
    NamespaceSubjectKind,
    NamespaceTier,
    SourceRecord,
    SourceStatus,
)
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 9))
NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)
HASH = "sha256:" + "a" * 64


@req("FR-402", "FR-405", "FR-406", "FR-407")
def test_namespace_scope_and_grant_interval_fail_closed() -> None:
    with pytest.raises(ValidationError, match="session_id"):
        KnowledgeNamespace(id=U[0], workspace_id=U[1], tier=NamespaceTier.SESSION, name="run")
    with pytest.raises(ValidationError, match="valid_until"):
        NamespaceGrant(
            id=U[0],
            workspace_id=U[1],
            namespace_id=U[2],
            subject_kind=NamespaceSubjectKind.WORKSPACE,
            subject_id=U[1],
            capability=NamespaceCapability.READ,
            valid_from=NOW,
            valid_until=NOW,
        )


@req("FR-402", "FR-405", "FR-406", "FR-407")
def test_retracted_source_requires_nonblank_reason() -> None:
    with pytest.raises(ValidationError, match="nonblank retraction_reason"):
        SourceRecord(
            id=U[2],
            workspace_id=U[1],
            namespace_id=U[0],
            title="Fixture",
            citation="Fixture citation",
            object_ref="sources/a",
            content_hash=HASH,
            media_type="text/plain",
            size_bytes=7,
            status=SourceStatus.RETRACTED,
            retracted_at=NOW,
        )


@req("FR-402", "FR-405", "FR-406", "FR-407")
def test_metadata_has_composite_tenant_foreign_keys_and_identity_constraints() -> None:
    namespace_table = cast(Table, KnowledgeNamespaceRow.__table__)
    source_table = cast(Table, SourceRow.__table__)
    chunk_table = cast(Table, KnowledgeChunkRow.__table__)
    namespace_fks = {fk.name: fk for fk in namespace_table.foreign_key_constraints}
    source_fks = {fk.name: fk for fk in source_table.foreign_key_constraints}
    chunk_fks = {fk.name: fk for fk in chunk_table.foreign_key_constraints}
    assert "fk_knowledge_namespaces_session_workspace" in namespace_fks
    assert "fk_sources_namespace_workspace" in source_fks
    assert "fk_chunks_document_workspace" in chunk_fks
    assert source_fks["fk_sources_namespace_workspace"].column_keys == [
        "workspace_id",
        "namespace_id",
    ]
    assert chunk_fks["fk_chunks_document_workspace"].column_keys == [
        "workspace_id",
        "document_id",
    ]
    assert "uq_chunks_content_identity" in {
        constraint.name for constraint in chunk_table.constraints
    }


@req("FR-402", "FR-405", "FR-406", "FR-407")
async def test_repository_maps_full_provenance_chain_without_commit() -> None:
    session = MagicMock(spec=AsyncSession)
    repository = SqlAlchemyKnowledgeRepository(session)
    assert isinstance(repository, KnowledgeRepository)
    namespace = KnowledgeNamespace(
        id=U[0], workspace_id=U[1], tier=NamespaceTier.WORKSPACE, name="workspace"
    )
    source = SourceRecord(
        id=U[2],
        workspace_id=U[1],
        namespace_id=U[0],
        title="Fixture",
        citation="Fixture citation",
        object_ref="minio://sources/a",
        content_hash=HASH,
        media_type="text/plain",
        size_bytes=7,
    )
    document = DocumentRecord(
        id=U[3],
        workspace_id=U[1],
        source_id=U[2],
        parser="txt",
        parser_version="1",
    )
    chunk = KnowledgeChunk(
        id=U[4],
        workspace_id=U[1],
        document_id=U[3],
        ordinal=0,
        text="fixture",
        token_count=1,
        locator={"char_start": 0, "char_end": 7},
        content_hash=HASH,
        chunker_version="agora-whitespace-v1",
    )

    await repository.add_namespace(namespace)
    await repository.add_grant(
        NamespaceGrant(
            id=U[5],
            workspace_id=U[1],
            namespace_id=U[0],
            subject_kind=NamespaceSubjectKind.WORKSPACE,
            subject_id=U[1],
            capability=NamespaceCapability.READ,
            valid_from=NOW,
        )
    )
    await repository.add_source(source)
    await repository.add_document(document)
    await repository.add_chunks((chunk,))

    assert session.flush.await_count == 5
    assert session.commit.call_count == 0
    rows = [call.args[0] for call in session.add.call_args_list]
    assert [row.__tablename__ for row in rows] == [
        "knowledge_namespaces",
        "knowledge_namespace_grants",
        "sources",
        "documents",
        "chunks",
    ]
