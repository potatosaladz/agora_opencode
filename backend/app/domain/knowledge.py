"""Strict Phase 5 knowledge provenance values and repository contract."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "DocumentRecord",
    "DocumentStatus",
    "KnowledgeChunk",
    "KnowledgeEmbedding",
    "KnowledgeNamespace",
    "KnowledgeRepository",
    "KnowledgeVectorHit",
    "KnowledgeVectorIndex",
    "NamespaceCapability",
    "NamespaceGrant",
    "NamespaceSubjectKind",
    "NamespaceTier",
    "SourceRecord",
    "SourceStatus",
]


# trace: FR-405
class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


class NamespaceTier(StrEnum):
    GLOBAL = "GLOBAL"
    WORKSPACE = "WORKSPACE"
    DOMAIN = "DOMAIN"
    AGENT = "AGENT"
    SESSION = "SESSION"
    HISTORICAL = "HISTORICAL"


class NamespaceSubjectKind(StrEnum):
    WORKSPACE = "WORKSPACE"
    USER = "USER"
    AGENT_DEFINITION = "AGENT_DEFINITION"
    SESSION = "SESSION"


class NamespaceCapability(StrEnum):
    READ = "READ"
    WRITE = "WRITE"


class SourceStatus(StrEnum):
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
    RETRACTED = "RETRACTED"


class DocumentStatus(StrEnum):
    PENDING = "PENDING"
    PARSING = "PARSING"
    CHUNKED = "CHUNKED"
    EMBEDDED = "EMBEDDED"
    READY = "READY"
    FAILED = "FAILED"


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("timestamp must include an RFC 3339 offset")
    return value.astimezone(UTC) if value is not None else None


class KnowledgeNamespace(_FrozenModel):
    id: UUID
    workspace_id: UUID
    tier: NamespaceTier
    name: str = Field(min_length=1)
    session_id: UUID | None = None
    agent_def_id: UUID | None = None
    retention: JsonObject = Field(default_factory=dict)
    created_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value

    @field_validator("created_at")
    @classmethod
    def _timestamp(cls, value: datetime | None) -> datetime | None:
        return _aware(value)

    @model_validator(mode="after")
    def _scope_matches_tier(self) -> KnowledgeNamespace:
        if (self.tier is NamespaceTier.SESSION) != (self.session_id is not None):
            raise ValueError("SESSION tier requires exactly one session_id")
        if (self.tier is NamespaceTier.AGENT) != (self.agent_def_id is not None):
            raise ValueError("AGENT tier requires exactly one agent_def_id")
        return self


class NamespaceGrant(_FrozenModel):
    id: UUID
    workspace_id: UUID
    namespace_id: UUID
    subject_kind: NamespaceSubjectKind
    subject_id: UUID
    capability: NamespaceCapability
    valid_from: datetime
    valid_until: datetime | None = None
    created_at: datetime | None = None

    @field_validator("valid_from", "valid_until", "created_at")
    @classmethod
    def _timestamps(cls, value: datetime | None) -> datetime | None:
        return _aware(value)

    @model_validator(mode="after")
    def _valid_interval(self) -> NamespaceGrant:
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        return self


class SourceRecord(_FrozenModel):
    id: UUID
    workspace_id: UUID
    namespace_id: UUID
    title: str = Field(min_length=1)
    citation: str = Field(min_length=1)
    publisher: str | None = None
    url: str | None = None
    object_ref: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    media_type: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    published_at: datetime | None = None
    ingested_at: datetime | None = None
    trust_level: str = "UNKNOWN"
    license: str | None = None
    status: SourceStatus = SourceStatus.READY
    retracted_at: datetime | None = None
    retraction_reason: str | None = None
    uploaded_by: UUID | None = None

    @field_validator("published_at", "ingested_at", "retracted_at")
    @classmethod
    def _timestamps(cls, value: datetime | None) -> datetime | None:
        return _aware(value)

    @model_validator(mode="after")
    def _retraction_complete(self) -> SourceRecord:
        retracted = self.status is SourceStatus.RETRACTED
        if retracted != (self.retracted_at is not None):
            raise ValueError("RETRACTED status requires retracted_at")
        if (self.retraction_reason is not None) and not retracted:
            raise ValueError("retraction_reason requires RETRACTED status")
        if retracted and (self.retraction_reason is None or not self.retraction_reason.strip()):
            raise ValueError("RETRACTED sources require a nonblank retraction_reason")
        return self


class DocumentRecord(_FrozenModel):
    id: UUID
    workspace_id: UUID
    source_id: UUID
    parent_id: UUID | None = None
    title: str | None = None
    language: str = "und"
    structure: JsonObject = Field(default_factory=dict)
    page_count: int | None = Field(default=None, ge=0)
    char_count: int | None = Field(default=None, ge=0)
    parser: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    status: DocumentStatus = DocumentStatus.PENDING
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def _timestamps(cls, value: datetime | None) -> datetime | None:
        return _aware(value)


class KnowledgeChunk(_FrozenModel):
    id: UUID
    workspace_id: UUID
    document_id: UUID
    ordinal: int = Field(ge=0)
    text: str = Field(min_length=1)
    token_count: int = Field(gt=0)
    locator: JsonObject
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    chunker_version: str = Field(min_length=1)
    acl: tuple[UUID, ...] = ()
    created_at: datetime | None = None

    @field_validator("created_at")
    @classmethod
    def _timestamp(cls, value: datetime | None) -> datetime | None:
        return _aware(value)


class KnowledgeEmbedding(_FrozenModel):
    namespace_id: UUID
    chunk_id: UUID
    document_id: UUID
    source_id: UUID
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    embedding_model: str = Field(min_length=1)
    embedding_version: str = Field(min_length=1)
    vector: Sequence[float]

    @field_validator("embedding_model", "embedding_version")
    @classmethod
    def _identity_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("embedding identity must not be blank")
        return value


class KnowledgeVectorHit(_FrozenModel):
    namespace_id: UUID
    chunk_id: UUID
    document_id: UUID
    source_id: UUID
    content_hash: str
    embedding_model: str
    embedding_version: str
    chunker_version: str
    locator: JsonObject
    score: float


@runtime_checkable
class KnowledgeVectorIndex(Protocol):
    """Replaceable vector index over PostgreSQL-authoritative knowledge rows."""

    async def upsert(self, items: Sequence[KnowledgeEmbedding]) -> None: ...

    async def query(
        self,
        namespace_id: UUID,
        vector: Sequence[float],
        *,
        embedding_model: str,
        embedding_version: str,
        k: int,
        min_score: float,
    ) -> Sequence[KnowledgeVectorHit]: ...

    async def delete_namespace(self, namespace_id: UUID) -> int: ...


@runtime_checkable
class KnowledgeRepository(Protocol):
    async def add_namespace(self, namespace: KnowledgeNamespace) -> None: ...
    async def add_grant(self, grant: NamespaceGrant) -> None: ...
    async def add_source(self, source: SourceRecord) -> None: ...
    async def add_document(self, document: DocumentRecord) -> None: ...
    async def add_chunks(self, chunks: tuple[KnowledgeChunk, ...]) -> None: ...
    async def get_namespace(
        self, workspace_id: UUID, namespace_id: UUID
    ) -> KnowledgeNamespace | None: ...
    async def get_grant(self, workspace_id: UUID, grant_id: UUID) -> NamespaceGrant | None: ...
    async def get_source(self, workspace_id: UUID, source_id: UUID) -> SourceRecord | None: ...
    async def get_document(
        self, workspace_id: UUID, document_id: UUID
    ) -> DocumentRecord | None: ...
    async def get_chunk(self, workspace_id: UUID, chunk_id: UUID) -> KnowledgeChunk | None: ...
