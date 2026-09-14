"""Durable source ingestion orchestration outside deterministic workflow code."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from app.domain.ingestion import DocumentFormat, ParsedDocument, chunk_document
from app.domain.ingestion_activity import (
    IngestionCheckpointStore,
    IngestionFailureCode,
    IngestionFailureKind,
    IngestionStage,
    IngestionStageState,
    IngestSourceInput,
    IngestSourceResult,
)
from app.domain.knowledge import DocumentRecord, DocumentStatus, JsonObject, KnowledgeChunk
from app.ports.errors import IntegrityObjectError, PermanentPortError, PortError, TransientPortError
from app.ports.storage import ObjectRef, ObjectStore

__all__ = ["SourceIngestionRunner"]

_MEDIA_FORMATS = {
    "application/pdf": DocumentFormat.PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocumentFormat.DOCX,
    "text/plain": DocumentFormat.TXT,
    "text/markdown": DocumentFormat.MARKDOWN,
    "text/csv": DocumentFormat.CSV,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": DocumentFormat.XLSX,
    "application/json": DocumentFormat.JSON,
    "text/html": DocumentFormat.HTML,
}


# trace: FR-401
class SourceIngestionRunner:
    def __init__(
        self,
        store: IngestionCheckpointStore,
        object_store: ObjectStore,
        parser: Callable[[DocumentFormat, bytes], ParsedDocument],
        *,
        bucket: str,
    ) -> None:
        if not bucket.strip():
            raise ValueError("bucket must not be blank")
        self._store = store
        self._object_store = object_store
        self._parser = parser
        self._bucket = bucket

    async def run(self, command: IngestSourceInput) -> IngestSourceResult:
        checkpoint = await self._store.start(command)
        if checkpoint.parse_state is IngestionStageState.SUCCEEDED:
            return await self._store.result(command.workspace_id, command.operation_id)
        if checkpoint.terminal:
            raise PermanentPortError("source ingestion previously failed", port="source_ingestion")

        if command.object_bucket != self._bucket:
            await self._store.fail(
                command,
                stage=IngestionStage.ACQUIRE,
                code=IngestionFailureCode.OBJECT_STORE_FAILURE,
                kind=IngestionFailureKind.PERMANENT,
                detail="source object is outside the configured artifact bucket",
            )
            raise PermanentPortError("source object bucket is not allowed", port="source_ingestion")
        ref = ObjectRef(
            bucket=command.object_bucket,
            key=command.object_key,
            digest=command.declared_content_hash,
            content_type=command.media_type,
            size=command.size_bytes,
        )
        object_ref = f"minio://{ref.bucket}/{ref.key}"
        try:
            verified = await self._object_store.get(ref)
            _verify_size(verified, expected=command.size_bytes)
        except IntegrityObjectError as exc:
            await self._store.fail(
                command,
                stage=IngestionStage.ACQUIRE,
                code=IngestionFailureCode.DIGEST_MISMATCH,
                kind=IngestionFailureKind.PERMANENT,
                detail="stored source bytes do not match declared identity",
            )
            raise PermanentPortError("source digest mismatch", port="source_ingestion") from exc
        except PortError as exc:
            failure_kind = (
                IngestionFailureKind.TRANSIENT
                if isinstance(exc, TransientPortError)
                else IngestionFailureKind.PERMANENT
            )
            await self._store.fail(
                command,
                stage=IngestionStage.ACQUIRE,
                code=IngestionFailureCode.OBJECT_STORE_FAILURE,
                kind=failure_kind,
                detail="source object could not be stored and verified",
            )
            if isinstance(exc, TransientPortError):
                raise
            raise PermanentPortError(
                "source object verification failed", port="source_ingestion"
            ) from exc

        except Exception as exc:
            await self._store.fail(
                command,
                stage=IngestionStage.ACQUIRE,
                code=IngestionFailureCode.UNEXPECTED_FAILURE,
                kind=IngestionFailureKind.TRANSIENT,
                detail="source object dependency failed unexpectedly",
            )
            raise TransientPortError(
                "source object dependency failed unexpectedly", port="source_ingestion", cause=exc
            ) from exc
        await self._store.acquired(command, object_ref=object_ref)
        format_ = _MEDIA_FORMATS.get(command.media_type.lower().split(";", 1)[0].strip())
        if format_ is None:
            await self._store.fail(
                command,
                stage=IngestionStage.PARSE,
                code=IngestionFailureCode.UNSUPPORTED_MEDIA_TYPE,
                kind=IngestionFailureKind.PERMANENT,
                detail="declared media type is not supported",
                object_ref=object_ref,
            )
            raise PermanentPortError("unsupported source media type", port="source_ingestion")

        try:
            parsed = self._parser(format_, verified)
            chunks = chunk_document(parsed)
        except PermanentPortError as exc:
            await self._store.fail(
                command,
                stage=IngestionStage.PARSE,
                code=IngestionFailureCode.PARSE_FAILED,
                kind=IngestionFailureKind.PERMANENT,
                detail="source document could not be parsed",
                object_ref=object_ref,
            )
            raise PermanentPortError(
                "source document parsing failed", port="source_ingestion"
            ) from exc

        except Exception as exc:
            await self._store.fail(
                command,
                stage=IngestionStage.PARSE,
                code=IngestionFailureCode.UNEXPECTED_FAILURE,
                kind=IngestionFailureKind.TRANSIENT,
                detail="source document parser failed unexpectedly",
                object_ref=object_ref,
            )
            raise TransientPortError(
                "source document parser failed unexpectedly", port="source_ingestion", cause=exc
            ) from exc
        chunk_rows = tuple(
            KnowledgeChunk(
                id=uuid5(
                    NAMESPACE_URL, f"{command.document_id}:{chunk.ordinal}:{chunk.content_hash}"
                ),
                workspace_id=command.workspace_id,
                document_id=command.document_id,
                ordinal=chunk.ordinal,
                text=chunk.text,
                token_count=chunk.token_count,
                locator=chunk.locator.model_dump(mode="json"),
                content_hash=chunk.content_hash,
                chunker_version=chunk.chunker_version,
            )
            for chunk in chunks
        )
        structure = cast(
            JsonObject,
            {
                "format": parsed.format.value,
                "blocks": [block.model_dump(mode="json") for block in parsed.blocks],
            },
        )
        pages = [block.locator.page for block in parsed.blocks if block.locator.page is not None]
        document = DocumentRecord(
            id=command.document_id,
            workspace_id=command.workspace_id,
            source_id=command.source_id,
            title=command.title,
            structure=structure,
            page_count=max(pages) if pages else None,
            char_count=sum(len(block.text) for block in parsed.blocks),
            parser=parsed.parser,
            parser_version=parsed.parser_version,
            status=DocumentStatus.CHUNKED,
        )
        return await self._store.complete(
            command,
            object_ref=object_ref,
            document=document,
            chunks=chunk_rows,
            warnings=parsed.warnings,
        )


def _verify_size(body: bytes, *, expected: int) -> None:
    if len(body) != expected:
        raise IntegrityObjectError("stored source size differs", port="object_store")
