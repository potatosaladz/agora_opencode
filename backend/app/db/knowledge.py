"""SQLAlchemy repository for tenant-owned knowledge provenance."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge import (
    DocumentRow,
    KnowledgeChunkRow,
    KnowledgeNamespaceRow,
    NamespaceGrantRow,
    SourceRow,
)
from app.domain.knowledge import (
    DocumentRecord,
    DocumentStatus,
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

__all__ = ["SqlAlchemyKnowledgeRepository"]


class SqlAlchemyKnowledgeRepository:
    """Map immutable values inside one caller-owned RLS transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_namespace(self, namespace: KnowledgeNamespace) -> None:
        self._session.add(
            KnowledgeNamespaceRow(
                id=namespace.id,
                workspace_id=namespace.workspace_id,
                tier=namespace.tier.value,
                name=namespace.name,
                session_id=namespace.session_id,
                agent_def_id=namespace.agent_def_id,
                retention=namespace.retention,
                **({"created_at": namespace.created_at} if namespace.created_at else {}),
            )
        )
        await self._session.flush()

    async def add_grant(self, grant: NamespaceGrant) -> None:
        self._session.add(
            NamespaceGrantRow(
                id=grant.id,
                workspace_id=grant.workspace_id,
                namespace_id=grant.namespace_id,
                subject_kind=grant.subject_kind.value,
                subject_id=grant.subject_id,
                capability=grant.capability.value,
                valid_from=grant.valid_from,
                valid_until=grant.valid_until,
                **({"created_at": grant.created_at} if grant.created_at else {}),
            )
        )
        await self._session.flush()

    async def add_source(self, source: SourceRecord) -> None:
        self._session.add(
            SourceRow(
                id=source.id,
                workspace_id=source.workspace_id,
                namespace_id=source.namespace_id,
                title=source.title,
                citation=source.citation,
                publisher=source.publisher,
                url=source.url,
                object_ref=source.object_ref,
                content_hash=source.content_hash,
                media_type=source.media_type,
                size_bytes=source.size_bytes,
                published_at=source.published_at,
                trust_level=source.trust_level,
                license=source.license,
                status=source.status.value,
                retracted_at=source.retracted_at,
                retraction_reason=source.retraction_reason,
                uploaded_by=source.uploaded_by,
                **({"ingested_at": source.ingested_at} if source.ingested_at else {}),
            )
        )
        await self._session.flush()

    async def add_document(self, document: DocumentRecord) -> None:
        values: dict[str, object] = {}
        if document.created_at is not None:
            values["created_at"] = document.created_at
        if document.updated_at is not None:
            values["updated_at"] = document.updated_at
        self._session.add(
            DocumentRow(
                id=document.id,
                workspace_id=document.workspace_id,
                source_id=document.source_id,
                parent_id=document.parent_id,
                title=document.title,
                language=document.language,
                structure=document.structure,
                page_count=document.page_count,
                char_count=document.char_count,
                parser=document.parser,
                parser_version=document.parser_version,
                status=document.status.value,
                error=document.error,
                **values,
            )
        )
        await self._session.flush()

    async def add_chunks(self, chunks: tuple[KnowledgeChunk, ...]) -> None:
        for chunk in chunks:
            self._session.add(
                KnowledgeChunkRow(
                    id=chunk.id,
                    workspace_id=chunk.workspace_id,
                    document_id=chunk.document_id,
                    ordinal=chunk.ordinal,
                    text=chunk.text,
                    token_count=chunk.token_count,
                    locator=chunk.locator,
                    content_hash=chunk.content_hash,
                    chunker_version=chunk.chunker_version,
                    acl=list(chunk.acl),
                    **({"created_at": chunk.created_at} if chunk.created_at else {}),
                )
            )
        await self._session.flush()

    async def get_namespace(
        self, workspace_id: UUID, namespace_id: UUID
    ) -> KnowledgeNamespace | None:
        row = await self._session.scalar(
            select(KnowledgeNamespaceRow).where(
                KnowledgeNamespaceRow.workspace_id == workspace_id,
                KnowledgeNamespaceRow.id == namespace_id,
            )
        )
        return _namespace(row) if row is not None else None

    async def get_grant(self, workspace_id: UUID, grant_id: UUID) -> NamespaceGrant | None:
        row = await self._session.scalar(
            select(NamespaceGrantRow).where(
                NamespaceGrantRow.workspace_id == workspace_id, NamespaceGrantRow.id == grant_id
            )
        )
        return _grant(row) if row is not None else None

    async def get_source(self, workspace_id: UUID, source_id: UUID) -> SourceRecord | None:
        row = await self._session.scalar(
            select(SourceRow).where(
                SourceRow.workspace_id == workspace_id, SourceRow.id == source_id
            )
        )
        return _source(row) if row is not None else None

    async def get_document(self, workspace_id: UUID, document_id: UUID) -> DocumentRecord | None:
        row = await self._session.scalar(
            select(DocumentRow).where(
                DocumentRow.workspace_id == workspace_id, DocumentRow.id == document_id
            )
        )
        return _document(row) if row is not None else None

    async def get_chunk(self, workspace_id: UUID, chunk_id: UUID) -> KnowledgeChunk | None:
        row = await self._session.scalar(
            select(KnowledgeChunkRow).where(
                KnowledgeChunkRow.workspace_id == workspace_id, KnowledgeChunkRow.id == chunk_id
            )
        )
        return _chunk(row) if row is not None else None


def _namespace(row: KnowledgeNamespaceRow) -> KnowledgeNamespace:
    return KnowledgeNamespace(
        id=row.id,
        workspace_id=row.workspace_id,
        tier=NamespaceTier(row.tier),
        name=row.name,
        session_id=row.session_id,
        agent_def_id=row.agent_def_id,
        retention=dict(row.retention),
        created_at=row.created_at,
    )


def _source(row: SourceRow) -> SourceRecord:
    return SourceRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        namespace_id=row.namespace_id,
        title=row.title,
        citation=row.citation,
        publisher=row.publisher,
        url=row.url,
        object_ref=row.object_ref,
        content_hash=row.content_hash,
        media_type=row.media_type,
        size_bytes=row.size_bytes,
        published_at=row.published_at,
        ingested_at=row.ingested_at,
        trust_level=row.trust_level,
        license=row.license,
        status=SourceStatus(row.status),
        retracted_at=row.retracted_at,
        retraction_reason=row.retraction_reason,
        uploaded_by=row.uploaded_by,
    )


def _grant(row: NamespaceGrantRow) -> NamespaceGrant:
    return NamespaceGrant(
        id=row.id,
        workspace_id=row.workspace_id,
        namespace_id=row.namespace_id,
        subject_kind=NamespaceSubjectKind(row.subject_kind),
        subject_id=row.subject_id,
        capability=NamespaceCapability(row.capability),
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        created_at=row.created_at,
    )


def _document(row: DocumentRow) -> DocumentRecord:
    return DocumentRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        source_id=row.source_id,
        parent_id=row.parent_id,
        title=row.title,
        language=row.language,
        structure=dict(row.structure),
        page_count=row.page_count,
        char_count=row.char_count,
        parser=row.parser,
        parser_version=row.parser_version,
        status=DocumentStatus(row.status),
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _chunk(row: KnowledgeChunkRow) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=row.id,
        workspace_id=row.workspace_id,
        document_id=row.document_id,
        ordinal=row.ordinal,
        text=row.text,
        token_count=row.token_count,
        locator=dict(row.locator),
        content_hash=row.content_hash,
        chunker_version=row.chunker_version,
        acl=tuple(row.acl),
        created_at=row.created_at,
    )


_KNOWLEDGE_REPOSITORY_PORT: type[KnowledgeRepository] = SqlAlchemyKnowledgeRepository
