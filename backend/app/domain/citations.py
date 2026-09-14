"""Resolvable evidence citations and additive source-retraction contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.knowledge import JsonObject, SourceStatus
from app.domain.reasoning import ActorClass

__all__ = [
    "CitationError",
    "CitationRepository",
    "CitationResolution",
    "CitationSnapshot",
    "EvidenceCitation",
    "ManualEvidenceCitation",
    "SourceRetraction",
    "SourceRetractionCommand",
]


# trace: FR-403, FR-407, FR-408
class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an RFC 3339 offset")
    return value.astimezone(UTC)


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


def _locator_span(value: JsonObject) -> JsonObject:
    start, end = value.get("char_start"), value.get("char_end")
    if not isinstance(start, int) or isinstance(start, bool) or start < 0:
        raise ValueError("locator char_start must be a nonnegative integer")
    if not isinstance(end, int) or isinstance(end, bool) or end <= start:
        raise ValueError("locator char_end must be greater than char_start")
    return value


class CitationError(Exception):
    """Citation or retraction input does not resolve to authoritative tenant state."""


class CitationSnapshot(_FrozenModel):
    """Immutable provenance as observed when evidence was attached."""

    namespace_id: UUID
    source_id: UUID
    document_id: UUID
    chunk_id: UUID
    citation: str = Field(min_length=1)
    locator: JsonObject
    source_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    chunk_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    chunker_version: str = Field(min_length=1)
    source_timestamp: datetime
    document_timestamp: datetime
    retrieved_at: datetime
    trust_level: str = Field(min_length=1)
    source_status: SourceStatus

    _timestamps = field_validator("source_timestamp", "document_timestamp", "retrieved_at")(_aware)
    _strings = field_validator("citation", "chunker_version", "trust_level")(_not_blank)

    @field_validator("locator")
    @classmethod
    def _locator_not_empty(cls, value: JsonObject) -> JsonObject:
        return _locator_span(value)


class ManualEvidenceCitation(_FrozenModel):
    """Human-attributed request to resolve one evidence artifact to one exact chunk."""

    citation_id: UUID
    workspace_id: UUID
    session_id: UUID
    evidence_artifact_id: UUID
    actor_class: Literal[ActorClass.HUMAN] = ActorClass.HUMAN
    actor_id: UUID
    namespace_id: UUID
    source_id: UUID
    document_id: UUID
    chunk_id: UUID
    source_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    chunk_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    locator: JsonObject
    retrieved_at: datetime

    _retrieved_at = field_validator("retrieved_at")(_aware)

    @field_validator("locator")
    @classmethod
    def _locator_not_empty(cls, value: JsonObject) -> JsonObject:
        return _locator_span(value)


class EvidenceCitation(_FrozenModel):
    citation_id: UUID
    workspace_id: UUID
    session_id: UUID
    evidence_artifact_id: UUID
    claim_artifact_id: UUID
    actor_id: UUID
    attached_at: datetime
    snapshot: CitationSnapshot

    _attached_at = field_validator("attached_at")(_aware)


class CitationResolution(_FrozenModel):
    citation: EvidenceCitation
    current_source_status: SourceStatus
    retracted_at: datetime | None = None
    retraction_reason: str | None = None

    @field_validator("retracted_at")
    @classmethod
    def _retracted_at_aware(cls, value: datetime | None) -> datetime | None:
        return _aware(value) if value is not None else None


class SourceRetractionCommand(_FrozenModel):
    retraction_id: UUID
    workspace_id: UUID
    source_id: UUID
    actor_class: Literal[ActorClass.HUMAN] = ActorClass.HUMAN
    actor_id: UUID
    reason: str = Field(min_length=1)
    retracted_at: datetime

    _reason = field_validator("reason")(_not_blank)
    _retracted_at = field_validator("retracted_at")(_aware)


class SourceRetraction(_FrozenModel):
    retraction_id: UUID
    workspace_id: UUID
    source_id: UUID
    actor_id: UUID
    reason: str
    retracted_at: datetime
    dependent_evidence_ids: tuple[UUID, ...]
    dependent_claim_ids: tuple[UUID, ...]

    _reason = field_validator("reason")(_not_blank)
    _retracted_at = field_validator("retracted_at")(_aware)


@runtime_checkable
class CitationRepository(Protocol):
    """Caller-transaction-scoped citation and retraction persistence."""

    async def attach_manual(self, command: ManualEvidenceCitation) -> EvidenceCitation: ...

    async def resolve(self, workspace_id: UUID, citation_id: UUID) -> CitationResolution | None: ...

    async def citations_for_evidence(
        self, workspace_id: UUID, evidence_artifact_id: UUID
    ) -> tuple[CitationResolution, ...]: ...

    async def retract_source(self, command: SourceRetractionCommand) -> SourceRetraction: ...

    async def dependencies(
        self, workspace_id: UUID, source_id: UUID
    ) -> tuple[EvidenceCitation, ...]: ...
