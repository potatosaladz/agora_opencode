"""T5-03 durable source-ingestion activity tests."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import Table
from temporalio.exceptions import ApplicationError

from app.adapters.ingestion import parse_document
from app.adapters.inmemory.object_store import InMemoryObjectStore
from app.adapters.temporal.ingestion_activity import IngestionActivities
from app.application.ingestion import SourceIngestionRunner
from app.db.models.knowledge import IngestionOperationRow
from app.domain.ingestion_activity import (
    IngestionActivityRunner,
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
from app.domain.knowledge import DocumentRecord, KnowledgeChunk
from app.ports.errors import PermanentPortError, TransientPortError
from app.ports.storage import ObjectRef
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 7))
BODY = b"Heading\n\nA deterministic source paragraph."


def command(
    *, body: bytes = BODY, media_type: str = "text/plain", declared_hash: str | None = None
) -> IngestSourceInput:
    content_hash = declared_hash or "sha256:" + hashlib.sha256(body).hexdigest()
    return IngestSourceInput(
        protocol_version="1.0",
        kind="source_ingestion",
        operation_id=U[0],
        workspace_id=U[1],
        namespace_id=U[2],
        source_id=U[3],
        document_id=U[4],
        title="Fixture",
        citation="Fixture citation",
        media_type=media_type,
        declared_content_hash=content_hash,
        size_bytes=len(body),
        object_bucket="artifacts",
        object_key=f"sources/{content_hash.removeprefix('sha256:')}",
    )


class MemoryCheckpointStore:
    def __init__(self) -> None:
        self.checkpoint: IngestionCheckpoint | None = None
        self.completed: IngestSourceResult | None = None
        self.document: DocumentRecord | None = None
        self.chunks: tuple[KnowledgeChunk, ...] = ()
        self.complete_count = 0

    async def start(self, item: IngestSourceInput) -> IngestionCheckpoint:
        request_hash = ingestion_request_hash(item)
        if self.checkpoint is None:
            self.checkpoint = IngestionCheckpoint(
                operation_id=item.operation_id,
                workspace_id=item.workspace_id,
                namespace_id=item.namespace_id,
                source_id=item.source_id,
                document_id=item.document_id,
                request_hash=request_hash,
                acquire_state=IngestionStageState.RUNNING,
                attempt_count=1,
            )
        elif self.checkpoint.request_hash != request_hash:
            raise PermanentPortError("conflicting replay", port="test")
        elif not self.checkpoint.terminal:
            acquire_state = (
                IngestionStageState.RUNNING
                if self.checkpoint.acquire_state is not IngestionStageState.SUCCEEDED
                else IngestionStageState.SUCCEEDED
            )
            parse_state = (
                IngestionStageState.RUNNING
                if acquire_state is IngestionStageState.SUCCEEDED
                else IngestionStageState.PENDING
            )
            self.checkpoint = self.checkpoint.model_copy(
                update={
                    "acquire_state": acquire_state,
                    "parse_state": parse_state,
                    "attempt_count": self.checkpoint.attempt_count + 1,
                    "failure_stage": None,
                    "failure_code": None,
                    "failure_kind": None,
                    "failure_detail": None,
                }
            )
        return self.checkpoint

    async def acquired(self, item: IngestSourceInput, *, object_ref: str) -> None:
        assert self.checkpoint is not None
        self.checkpoint = self.checkpoint.model_copy(
            update={
                "acquire_state": IngestionStageState.SUCCEEDED,
                "parse_state": IngestionStageState.RUNNING,
                "object_ref": object_ref,
            }
        )

    async def complete(
        self,
        item: IngestSourceInput,
        *,
        object_ref: str,
        document: DocumentRecord,
        chunks: tuple[KnowledgeChunk, ...],
        warnings: tuple[str, ...],
    ) -> IngestSourceResult:
        assert self.checkpoint is not None
        self.complete_count += 1
        self.document, self.chunks = document, chunks
        self.checkpoint = self.checkpoint.model_copy(
            update={
                "acquire_state": IngestionStageState.SUCCEEDED,
                "parse_state": IngestionStageState.SUCCEEDED,
                "object_ref": object_ref,
                "parse_warnings": warnings,
            }
        )
        self.completed = IngestSourceResult(
            operation_id=item.operation_id,
            source_id=item.source_id,
            document_id=item.document_id,
            chunk_ids=tuple(chunk.id for chunk in chunks),
            acquire_state=IngestionStageState.SUCCEEDED,
            parse_state=IngestionStageState.SUCCEEDED,
            embed_state=IngestionStageState.PENDING,
            index_state=IngestionStageState.PENDING,
            parse_warnings=warnings,
        )
        return self.completed

    async def fail(
        self,
        item: IngestSourceInput,
        *,
        stage: IngestionStage,
        code: IngestionFailureCode,
        kind: IngestionFailureKind,
        detail: str,
        object_ref: str | None = None,
    ) -> None:
        assert self.checkpoint is not None
        updates: dict[str, object] = {
            f"{stage.value.lower()}_state": IngestionStageState.FAILED,
            "failure_stage": stage,
            "failure_code": code,
            "failure_kind": kind,
            "failure_detail": detail,
        }
        if object_ref is not None:
            updates["object_ref"] = object_ref
        self.checkpoint = self.checkpoint.model_copy(update=updates)

    async def result(self, workspace_id: UUID, operation_id: UUID) -> IngestSourceResult:
        assert workspace_id == U[1]
        assert operation_id == U[0]
        assert self.completed is not None
        return self.completed

    async def record_downstream_stage(
        self,
        workspace_id: UUID,
        operation_id: UUID,
        *,
        stage: IngestionStage,
        state: IngestionStageState,
        code: IngestionFailureCode | None = None,
        kind: IngestionFailureKind | None = None,
        detail: str | None = None,
    ) -> IngestionCheckpoint:
        del workspace_id, operation_id, stage, state, code, kind, detail
        assert self.checkpoint is not None
        return self.checkpoint


class CountingObjectStore(InMemoryObjectStore):
    def __init__(self, *, fail_once: bool = False) -> None:
        super().__init__()
        self.get_count = 0
        self.fail_once = fail_once

    async def put(
        self,
        bucket: str,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> ObjectRef:
        return await super().put(bucket, key, body, content_type=content_type, metadata=metadata)

    async def get(self, ref: ObjectRef) -> bytes:
        self.get_count += 1
        if self.fail_once:
            self.fail_once = False
            raise TransientPortError("temporary store outage SECRET", port="object_store")
        return await super().get(ref)


async def stage(objects: InMemoryObjectStore, item: IngestSourceInput, body: bytes = BODY) -> None:
    await objects.put(
        item.object_bucket,
        item.object_key,
        body,
        content_type=item.media_type,
        metadata={"content-hash": item.declared_content_hash},
    )


@req("FR-401", "NFR-001", "NFR-020")
async def test_success_is_digest_verified_and_exact_retry_has_no_duplicate_effects() -> None:
    checkpoints = MemoryCheckpointStore()
    objects = CountingObjectStore()
    runner = SourceIngestionRunner(checkpoints, objects, parse_document, bucket="artifacts")
    await stage(objects, command())

    first = await runner.run(command())
    second = await runner.run(command())

    assert first == second
    assert first.acquire_state is IngestionStageState.SUCCEEDED
    assert first.parse_state is IngestionStageState.SUCCEEDED
    assert first.embed_state is IngestionStageState.PENDING
    assert first.index_state is IngestionStageState.PENDING
    assert objects.get_count == 1
    assert checkpoints.complete_count == 1
    assert checkpoints.document is not None
    assert checkpoints.document.status.value == "CHUNKED"
    assert checkpoints.chunks
    assert [chunk.ordinal for chunk in checkpoints.chunks] == list(range(len(checkpoints.chunks)))


@req("FR-401", "NFR-001", "NFR-020")
async def test_transient_object_failure_is_durable_redacted_and_retryable() -> None:
    checkpoints = MemoryCheckpointStore()
    objects = CountingObjectStore(fail_once=True)
    runner = SourceIngestionRunner(checkpoints, objects, parse_document, bucket="artifacts")
    await stage(objects, command())

    with pytest.raises(TransientPortError):
        await runner.run(command())
    assert checkpoints.checkpoint is not None
    assert checkpoints.checkpoint.failure_kind is IngestionFailureKind.TRANSIENT
    assert checkpoints.checkpoint.failure_detail == "source object could not be stored and verified"
    assert "SECRET" not in checkpoints.checkpoint.failure_detail

    result = await runner.run(command())
    assert result.parse_state is IngestionStageState.SUCCEEDED
    assert checkpoints.checkpoint.attempt_count == 2


@req("FR-401", "NFR-001", "NFR-020")
@pytest.mark.parametrize(
    ("item", "code", "failure_stage", "object_exists"),
    [
        (
            command(declared_hash="sha256:" + "0" * 64),
            IngestionFailureCode.DIGEST_MISMATCH,
            IngestionStage.ACQUIRE,
            True,
        ),
        (
            command(media_type="image/png"),
            IngestionFailureCode.UNSUPPORTED_MEDIA_TYPE,
            IngestionStage.PARSE,
            True,
        ),
    ],
)
async def test_permanent_acquisition_failures_are_explicit_and_safe(
    item: IngestSourceInput,
    code: IngestionFailureCode,
    failure_stage: IngestionStage,
    object_exists: bool,
) -> None:
    checkpoints = MemoryCheckpointStore()
    objects = CountingObjectStore()
    await stage(objects, item)

    with pytest.raises(PermanentPortError):
        await SourceIngestionRunner(checkpoints, objects, parse_document, bucket="artifacts").run(
            item
        )

    assert checkpoints.checkpoint is not None
    assert checkpoints.checkpoint.failure_code is code
    assert checkpoints.checkpoint.failure_stage is failure_stage
    assert checkpoints.checkpoint.failure_kind is IngestionFailureKind.PERMANENT
    assert (objects.get_count > 0) is object_exists


@req("FR-401", "NFR-001", "NFR-020")
def test_command_hash_and_checkpoint_validation_are_strict() -> None:
    item = command()
    assert ingestion_request_hash(item) == ingestion_request_hash(item)
    assert ingestion_request_hash(item) != ingestion_request_hash(
        item.model_copy(update={"title": "B"})
    )
    with pytest.raises(ValidationError, match="content-addressed"):
        IngestSourceInput.model_validate(
            {**command().model_dump(), "object_key": "sources/not-the-digest"}, strict=True
        )
    with pytest.raises(ValidationError, match="failure_code"):
        IngestionCheckpoint(
            operation_id=U[0],
            workspace_id=U[1],
            namespace_id=U[2],
            source_id=U[3],
            document_id=U[4],
            request_hash="sha256:" + "a" * 64,
            parse_state=IngestionStageState.FAILED,
        )
    with pytest.raises(ValidationError, match="only failed stage"):
        IngestionCheckpoint(
            operation_id=U[0],
            workspace_id=U[1],
            namespace_id=U[2],
            source_id=U[3],
            document_id=U[4],
            request_hash="sha256:" + "a" * 64,
            acquire_state=IngestionStageState.FAILED,
            parse_state=IngestionStageState.FAILED,
            failure_stage=IngestionStage.PARSE,
            failure_code=IngestionFailureCode.PARSE_FAILED,
            failure_kind=IngestionFailureKind.PERMANENT,
            failure_detail="safe",
        )


@req("FR-401", "NFR-001", "NFR-020")
def test_ingestion_operation_metadata_is_tenant_safe_and_constrained() -> None:
    table = cast(Table, IngestionOperationRow.__table__)
    foreign_keys = {fk.name: fk for fk in table.foreign_key_constraints}
    constraints = {constraint.name for constraint in table.constraints}

    assert "fk_ingestion_operations_namespace_workspace" in foreign_keys
    assert foreign_keys["fk_ingestion_operations_namespace_workspace"].column_keys == [
        "workspace_id",
        "namespace_id",
    ]
    assert "ck_knowledge_ingestion_operations_failure_matches_state" in constraints
    assert "ck_knowledge_ingestion_operations_failed_has_failure" in constraints
    assert "uq_ingestion_operations_source_id" in constraints
    assert isinstance(MemoryCheckpointStore(), IngestionCheckpointStore)


@req("FR-401", "NFR-001", "NFR-020")
async def test_temporal_activity_rejects_malformed_payload_without_raw_detail() -> None:
    class UnusedRunner:
        async def run(self, item: IngestSourceInput) -> IngestSourceResult:
            raise AssertionError(item)

    with pytest.raises(ApplicationError) as captured:
        await IngestionActivities(cast(IngestionActivityRunner, UnusedRunner())).ingest_source(
            {"kind": "source_ingestion"}
        )

    assert captured.value.non_retryable is True
    assert captured.value.message == "activity rejected permanent input or state"
