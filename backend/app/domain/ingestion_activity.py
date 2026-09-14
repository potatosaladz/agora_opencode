"""Strict contracts for durable, retry-safe source ingestion."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.knowledge import DocumentRecord, KnowledgeChunk

__all__ = [
    "INGEST_SOURCE_ACTIVITY",
    "IngestSourceInput",
    "IngestSourceResult",
    "IngestionActivityRunner",
    "IngestionCheckpoint",
    "IngestionCheckpointStore",
    "IngestionFailureCode",
    "IngestionFailureKind",
    "IngestionStage",
    "IngestionStageState",
    "ingestion_request_hash",
]

INGEST_SOURCE_ACTIVITY = "ingest_source"


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class IngestionStageState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class IngestionStage(StrEnum):
    ACQUIRE = "ACQUIRE"
    PARSE = "PARSE"
    EMBED = "EMBED"
    INDEX = "INDEX"


class IngestionFailureCode(StrEnum):
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    EMBEDDING_FAILED = "EMBEDDING_FAILED"
    INDEX_FAILED = "INDEX_FAILED"
    OBJECT_STORE_FAILURE = "OBJECT_STORE_FAILURE"
    PARSE_FAILED = "PARSE_FAILED"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    UNEXPECTED_FAILURE = "UNEXPECTED_FAILURE"


class IngestionFailureKind(StrEnum):
    PERMANENT = "PERMANENT"
    TRANSIENT = "TRANSIENT"


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("timestamp must include an RFC 3339 offset")
    return value.astimezone(UTC) if value is not None else None


class IngestSourceInput(_Contract):
    """Complete retry-stable activity input; caller allocates every public identity."""

    protocol_version: Literal["1.0"]
    kind: Literal["source_ingestion"]
    operation_id: UUID
    workspace_id: UUID
    namespace_id: UUID
    source_id: UUID
    document_id: UUID
    title: str = Field(min_length=1)
    citation: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    declared_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    object_bucket: str = Field(min_length=1)
    object_key: str = Field(min_length=1)
    publisher: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    trust_level: str = "UNKNOWN"
    license: str | None = None
    uploaded_by: UUID | None = None
    schema_version: int = 1

    @field_validator("title", "citation", "media_type", "object_bucket", "object_key")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text values must not be blank")
        return value

    @field_validator("published_at")
    @classmethod
    def _timestamp(cls, value: datetime | None) -> datetime | None:
        return _aware(value)

    @model_validator(mode="after")
    def _supported_schema(self) -> IngestSourceInput:
        if self.schema_version != 1:
            raise ValueError("unsupported IngestSourceInput schema_version")
        expected_key = f"sources/{self.declared_content_hash.removeprefix('sha256:')}"
        if self.object_key != expected_key:
            raise ValueError("object_key must be content-addressed by declared_content_hash")
        return self


class IngestionCheckpoint(_Contract):
    operation_id: UUID
    workspace_id: UUID
    namespace_id: UUID
    source_id: UUID
    document_id: UUID
    request_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    acquire_state: IngestionStageState = IngestionStageState.PENDING
    parse_state: IngestionStageState = IngestionStageState.PENDING
    embed_state: IngestionStageState = IngestionStageState.PENDING
    index_state: IngestionStageState = IngestionStageState.PENDING
    attempt_count: int = Field(default=0, ge=0)
    object_ref: str | None = None
    parse_warnings: tuple[str, ...] = ()
    failure_stage: IngestionStage | None = None
    failure_code: IngestionFailureCode | None = None
    failure_kind: IngestionFailureKind | None = None
    failure_detail: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def _timestamps(cls, value: datetime | None) -> datetime | None:
        return _aware(value)

    @model_validator(mode="after")
    def _failure_is_complete(self) -> IngestionCheckpoint:
        states = {
            IngestionStage.ACQUIRE: self.acquire_state,
            IngestionStage.PARSE: self.parse_state,
            IngestionStage.EMBED: self.embed_state,
            IngestionStage.INDEX: self.index_state,
        }
        failed_stages = tuple(
            stage for stage, state in states.items() if state is IngestionStageState.FAILED
        )
        if bool(failed_stages) != (self.failure_code is not None):
            raise ValueError("failed checkpoint requires failure_code")
        present = (
            self.failure_stage is not None,
            self.failure_code is not None,
            self.failure_kind is not None,
            self.failure_detail is not None,
        )
        if len(set(present)) != 1:
            raise ValueError("failure stage, code, kind, and detail must be recorded together")
        if self.failure_stage is not None and failed_stages != (self.failure_stage,):
            raise ValueError("failure_stage must identify the only failed stage")
        return self

    @property
    def terminal(self) -> bool:
        return self.parse_state is IngestionStageState.SUCCEEDED or (
            self.failure_kind is IngestionFailureKind.PERMANENT
        )


class IngestSourceResult(_Contract):
    operation_id: UUID
    source_id: UUID
    document_id: UUID
    chunk_ids: tuple[UUID, ...]
    acquire_state: IngestionStageState
    parse_state: IngestionStageState
    embed_state: IngestionStageState
    index_state: IngestionStageState
    parse_warnings: tuple[str, ...] = ()
    schema_version: int = 1


def ingestion_request_hash(command: IngestSourceInput) -> str:
    """Hash the complete retry input; only this digest is stored in PostgreSQL."""
    payload = command.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@runtime_checkable
class IngestionCheckpointStore(Protocol):
    async def start(self, command: IngestSourceInput) -> IngestionCheckpoint: ...

    async def acquired(self, command: IngestSourceInput, *, object_ref: str) -> None: ...

    async def complete(
        self,
        command: IngestSourceInput,
        *,
        object_ref: str,
        document: DocumentRecord,
        chunks: tuple[KnowledgeChunk, ...],
        warnings: tuple[str, ...],
    ) -> IngestSourceResult: ...

    async def fail(
        self,
        command: IngestSourceInput,
        *,
        stage: Literal[IngestionStage.ACQUIRE, IngestionStage.PARSE],
        code: IngestionFailureCode,
        kind: IngestionFailureKind,
        detail: str,
        object_ref: str | None = None,
    ) -> None: ...

    async def result(self, workspace_id: UUID, operation_id: UUID) -> IngestSourceResult: ...

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
    ) -> IngestionCheckpoint: ...


@runtime_checkable
class IngestionActivityRunner(Protocol):
    async def run(self, command: IngestSourceInput) -> IngestSourceResult: ...
