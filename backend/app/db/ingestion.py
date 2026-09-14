"""PostgreSQL-authoritative facade for retry-safe source ingestion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge import (
    DocumentRow,
    IngestionOperationRow,
    KnowledgeChunkRow,
    SourceRow,
)
from app.db.session import Database
from app.domain.ingestion_activity import (
    IngestionCheckpoint,
    IngestionCheckpointStore,
    IngestionFailureCode,
    IngestionFailureKind,
    IngestionStage,
    IngestionStageState,
    IngestSourceInput,
    IngestSourceResult,
    ingestion_request_hash,
)
from app.domain.knowledge import DocumentRecord, DocumentStatus, KnowledgeChunk, SourceStatus
from app.ports.errors import PermanentPortError

__all__ = ["SqlAlchemyIngestionCheckpointStore"]


class SqlAlchemyIngestionCheckpointStore:
    """Open one tenant transaction per checkpoint operation; retain no session between calls."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def start(self, command: IngestSourceInput) -> IngestionCheckpoint:
        request_hash = ingestion_request_hash(command)
        async with self._database.session(command.workspace_id) as session:
            await _lock_operation(session, command.operation_id)
            row = await session.get(IngestionOperationRow, command.operation_id)
            if row is None:
                row = IngestionOperationRow(
                    id=command.operation_id,
                    workspace_id=command.workspace_id,
                    namespace_id=command.namespace_id,
                    source_id=command.source_id,
                    document_id=command.document_id,
                    request_hash=request_hash,
                    acquire_state=IngestionStageState.RUNNING.value,
                    parse_state=IngestionStageState.PENDING.value,
                    embed_state=IngestionStageState.PENDING.value,
                    index_state=IngestionStageState.PENDING.value,
                    attempt_count=1,
                )
                session.add(row)
                await session.flush()
                return _checkpoint(row)
            _assert_identity(row, command, request_hash)
            checkpoint = _checkpoint(row)
            if checkpoint.terminal:
                return checkpoint
            row.attempt_count += 1
            if checkpoint.acquire_state is not IngestionStageState.SUCCEEDED:
                row.acquire_state = IngestionStageState.RUNNING.value
                row.parse_state = IngestionStageState.PENDING.value
            else:
                row.parse_state = IngestionStageState.RUNNING.value
            row.failure_code = None
            row.failure_stage = None
            row.failure_kind = None
            row.failure_detail = None
            row.updated_at = datetime.now(UTC)
            await session.flush()
            return _checkpoint(row)

    async def acquired(self, command: IngestSourceInput, *, object_ref: str) -> None:
        async with self._database.session(command.workspace_id) as session:
            row = await _operation(session, command, lock=True)
            checkpoint = _checkpoint(row)
            if checkpoint.parse_state is IngestionStageState.SUCCEEDED:
                return
            if checkpoint.failure_kind is IngestionFailureKind.PERMANENT:
                raise PermanentPortError(
                    "source ingestion previously failed", port="ingestion_checkpoint"
                )
            existing = await session.get(SourceRow, command.source_id)
            if existing is None:
                session.add(
                    SourceRow(
                        id=command.source_id,
                        workspace_id=command.workspace_id,
                        namespace_id=command.namespace_id,
                        title=command.title,
                        citation=command.citation,
                        publisher=command.publisher,
                        url=command.url,
                        object_ref=object_ref,
                        content_hash=command.declared_content_hash,
                        media_type=command.media_type,
                        size_bytes=command.size_bytes,
                        published_at=command.published_at,
                        trust_level=command.trust_level,
                        license=command.license,
                        status=SourceStatus.PROCESSING.value,
                        uploaded_by=command.uploaded_by,
                    )
                )
            elif (
                existing.object_ref != object_ref
                or existing.content_hash != command.declared_content_hash
            ):
                raise PermanentPortError(
                    "source identity conflicts with ingestion operation",
                    port="ingestion_checkpoint",
                )
            row.acquire_state = IngestionStageState.SUCCEEDED.value
            row.parse_state = IngestionStageState.RUNNING.value
            row.object_ref = object_ref
            row.failure_code = None
            row.failure_stage = None
            row.failure_kind = None
            row.failure_detail = None
            row.updated_at = datetime.now(UTC)
            await session.flush()

    async def complete(
        self,
        command: IngestSourceInput,
        *,
        object_ref: str,
        document: DocumentRecord,
        chunks: tuple[KnowledgeChunk, ...],
        warnings: tuple[str, ...],
    ) -> IngestSourceResult:
        async with self._database.session(command.workspace_id) as session:
            row = await _operation(session, command, lock=True)
            if row.parse_state == IngestionStageState.SUCCEEDED.value:
                return await _result(session, row)
            if row.object_ref != object_ref:
                raise PermanentPortError(
                    "verified object does not match ingestion checkpoint",
                    port="ingestion_checkpoint",
                )
            if await session.get(DocumentRow, command.document_id) is not None:
                raise PermanentPortError(
                    "document identity already exists without a completed checkpoint",
                    port="ingestion_checkpoint",
                )
            session.add(_document_row(document))
            session.add_all(_chunk_row(chunk) for chunk in chunks)
            source = await session.get(SourceRow, command.source_id)
            if source is None:
                raise PermanentPortError(
                    "verified source is missing from ingestion checkpoint",
                    port="ingestion_checkpoint",
                )
            source.status = SourceStatus.READY.value
            row.acquire_state = IngestionStageState.SUCCEEDED.value
            row.parse_state = IngestionStageState.SUCCEEDED.value
            row.parse_warnings = list(warnings)
            row.failure_code = None
            row.failure_stage = None
            row.failure_kind = None
            row.failure_detail = None
            row.updated_at = datetime.now(UTC)
            await session.flush()
            return await _result(session, row)

    async def fail(
        self,
        command: IngestSourceInput,
        *,
        stage: Literal[IngestionStage.ACQUIRE, IngestionStage.PARSE],
        code: IngestionFailureCode,
        kind: IngestionFailureKind,
        detail: str,
        object_ref: str | None = None,
    ) -> None:
        async with self._database.session(command.workspace_id) as session:
            row = await _operation(session, command, lock=True)
            if row.parse_state == IngestionStageState.SUCCEEDED.value:
                return
            source = (
                await session.get(SourceRow, command.source_id)
                if stage is IngestionStage.PARSE
                else None
            )
            if stage is IngestionStage.ACQUIRE:
                row.acquire_state = IngestionStageState.FAILED.value
                row.parse_state = IngestionStageState.PENDING.value
            else:
                row.parse_state = IngestionStageState.FAILED.value
                if source is not None and kind is IngestionFailureKind.PERMANENT:
                    source.status = SourceStatus.FAILED.value
            if object_ref is not None:
                row.object_ref = object_ref
            row.failure_stage = stage.value
            row.failure_code = code.value
            row.failure_kind = kind.value
            row.failure_detail = detail[:500]
            row.updated_at = datetime.now(UTC)
            await session.flush()

    async def result(self, workspace_id: UUID, operation_id: UUID) -> IngestSourceResult:
        async with self._database.session(workspace_id) as session:
            row = await session.get(IngestionOperationRow, operation_id)
            if row is None or row.workspace_id != workspace_id:
                raise PermanentPortError(
                    "ingestion operation does not exist", port="ingestion_checkpoint"
                )
            if row.parse_state != IngestionStageState.SUCCEEDED.value:
                raise PermanentPortError(
                    "ingestion operation is not complete", port="ingestion_checkpoint"
                )
            return await _result(session, row)

    async def record_downstream_stage(
        self,
        workspace_id: UUID,
        operation_id: UUID,
        *,
        stage: Literal[IngestionStage.EMBED, IngestionStage.INDEX],
        state: IngestionStageState,
        code: IngestionFailureCode | None = None,
        kind: IngestionFailureKind | None = None,
        detail: str | None = None,
    ) -> IngestionCheckpoint:
        if state is IngestionStageState.FAILED:
            if code is None or kind is None or detail is None:
                raise ValueError("failed downstream stage requires safe failure details")
        elif code is not None or kind is not None or detail is not None:
            raise ValueError("non-failed downstream stage cannot carry failure details")
        async with self._database.session(workspace_id) as session:
            row = await session.get(IngestionOperationRow, operation_id, with_for_update=True)
            if row is None or row.workspace_id != workspace_id:
                raise PermanentPortError(
                    "ingestion operation does not exist", port="ingestion_checkpoint"
                )
            if row.parse_state != IngestionStageState.SUCCEEDED.value:
                raise PermanentPortError(
                    "downstream ingestion requires completed parsing", port="ingestion_checkpoint"
                )
            if (
                stage is IngestionStage.INDEX
                and row.embed_state != IngestionStageState.SUCCEEDED.value
            ):
                raise PermanentPortError(
                    "indexing requires completed embedding", port="ingestion_checkpoint"
                )
            current_state = IngestionStageState(getattr(row, f"{stage.value.lower()}_state"))
            if current_state is IngestionStageState.SUCCEEDED and state is not current_state:
                raise PermanentPortError(
                    "completed ingestion stage cannot move backward", port="ingestion_checkpoint"
                )
            if current_state is IngestionStageState.FAILED:
                if row.failure_kind == IngestionFailureKind.PERMANENT.value:
                    raise PermanentPortError(
                        "permanently failed ingestion stage cannot retry",
                        port="ingestion_checkpoint",
                    )
                if state is not IngestionStageState.RUNNING:
                    raise PermanentPortError(
                        "transiently failed ingestion stage must resume through RUNNING",
                        port="ingestion_checkpoint",
                    )
            if row.failure_stage is not None and row.failure_stage != stage.value:
                raise PermanentPortError(
                    "another ingestion stage has an unresolved failure",
                    port="ingestion_checkpoint",
                )
            document = await session.get(DocumentRow, row.document_id)
            source = await session.get(SourceRow, row.source_id)
            setattr(row, f"{stage.value.lower()}_state", state.value)
            if stage is IngestionStage.EMBED and state is IngestionStageState.SUCCEEDED:
                if document is not None:
                    document.status = DocumentStatus.EMBEDDED.value
            elif stage is IngestionStage.INDEX and state is IngestionStageState.SUCCEEDED:
                if document is not None:
                    document.status = DocumentStatus.READY.value
                if source is not None:
                    source.status = SourceStatus.READY.value
            row.failure_stage = stage.value if state is IngestionStageState.FAILED else None
            row.failure_code = code.value if code is not None else None
            row.failure_kind = kind.value if kind is not None else None
            row.failure_detail = detail[:500] if detail is not None else None
            row.updated_at = datetime.now(UTC)
            await session.flush()
            return _checkpoint(row)


async def _lock_operation(session: AsyncSession, operation_id: UUID) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
        {"identity": f"source-ingestion:{operation_id}"},
    )


async def _operation(
    session: AsyncSession, command: IngestSourceInput, *, lock: bool
) -> IngestionOperationRow:
    row = await session.get(IngestionOperationRow, command.operation_id, with_for_update=lock)
    if row is None:
        raise PermanentPortError("ingestion operation does not exist", port="ingestion_checkpoint")
    _assert_identity(row, command, ingestion_request_hash(command))
    return row


def _assert_identity(
    row: IngestionOperationRow, command: IngestSourceInput, request_hash: str
) -> None:
    identity = (
        row.workspace_id,
        row.namespace_id,
        row.source_id,
        row.document_id,
        row.request_hash,
    )
    expected = (
        command.workspace_id,
        command.namespace_id,
        command.source_id,
        command.document_id,
        request_hash,
    )
    if identity != expected:
        raise PermanentPortError(
            "ingestion operation replay conflicts with original input", port="ingestion_checkpoint"
        )


def _checkpoint(row: IngestionOperationRow) -> IngestionCheckpoint:
    return IngestionCheckpoint(
        operation_id=row.id,
        workspace_id=row.workspace_id,
        namespace_id=row.namespace_id,
        source_id=row.source_id,
        document_id=row.document_id,
        request_hash=row.request_hash,
        acquire_state=IngestionStageState(row.acquire_state),
        parse_state=IngestionStageState(row.parse_state),
        embed_state=IngestionStageState(row.embed_state),
        index_state=IngestionStageState(row.index_state),
        attempt_count=row.attempt_count,
        object_ref=row.object_ref,
        parse_warnings=tuple(row.parse_warnings),
        failure_stage=(IngestionStage(row.failure_stage) if row.failure_stage else None),
        failure_code=(IngestionFailureCode(row.failure_code) if row.failure_code else None),
        failure_kind=(IngestionFailureKind(row.failure_kind) if row.failure_kind else None),
        failure_detail=row.failure_detail,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _document_row(document: DocumentRecord) -> DocumentRow:
    values: dict[str, object] = {}
    if document.created_at is not None:
        values["created_at"] = document.created_at
    if document.updated_at is not None:
        values["updated_at"] = document.updated_at
    return DocumentRow(
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


def _chunk_row(chunk: KnowledgeChunk) -> KnowledgeChunkRow:
    values = {"created_at": chunk.created_at} if chunk.created_at is not None else {}
    return KnowledgeChunkRow(
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
        **values,
    )


async def _result(session: AsyncSession, row: IngestionOperationRow) -> IngestSourceResult:
    chunk_ids = tuple(
        (
            await session.scalars(
                select(KnowledgeChunkRow.id)
                .where(
                    KnowledgeChunkRow.workspace_id == row.workspace_id,
                    KnowledgeChunkRow.document_id == row.document_id,
                )
                .order_by(KnowledgeChunkRow.ordinal)
            )
        ).all()
    )
    return IngestSourceResult(
        operation_id=row.id,
        source_id=row.source_id,
        document_id=row.document_id,
        chunk_ids=chunk_ids,
        acquire_state=IngestionStageState(row.acquire_state),
        parse_state=IngestionStageState(row.parse_state),
        embed_state=IngestionStageState(row.embed_state),
        index_state=IngestionStageState(row.index_state),
        parse_warnings=tuple(row.parse_warnings),
    )


_INGESTION_STORE_PORT: type[IngestionCheckpointStore] = SqlAlchemyIngestionCheckpointStore
