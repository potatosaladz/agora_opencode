"""Explicit memory tiers and validated semantic-promotion contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.reasoning import ActorClass

__all__ = [
    "ArtifactRef",
    "MemoryEntry",
    "MemoryError",
    "MemoryLifecycleCommand",
    "MemoryLifecycleEvent",
    "MemoryProvider",
    "MemoryQuery",
    "MemoryRef",
    "MemoryResult",
    "MemoryScope",
    "MemoryState",
    "MemoryTier",
    "PromotionCommand",
    "RetentionPolicy",
    "ValidationRecord",
]


# trace: FR-406
class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("timestamp must include an RFC 3339 offset")
    return value.astimezone(UTC) if value is not None else None


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


class MemoryError(Exception):
    """Memory operation violates tier or authoritative-state invariants."""


class MemoryTier(StrEnum):
    WORKING = "WORKING"
    EPISODIC = "EPISODIC"
    SEMANTIC = "SEMANTIC"
    PROCEDURAL = "PROCEDURAL"


class MemoryState(StrEnum):
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    ARCHIVED = "ARCHIVED"


class MemoryScope(_FrozenModel):
    workspace_id: UUID
    tier: MemoryTier
    namespace_id: UUID | None = None
    session_id: UUID | None = None
    agent_def_id: UUID | None = None

    @model_validator(mode="after")
    def _explicit_scope(self) -> MemoryScope:
        if self.tier in {MemoryTier.WORKING, MemoryTier.EPISODIC}:
            if (
                self.session_id is None
                or self.namespace_id is not None
                or self.agent_def_id is not None
            ):
                raise ValueError(f"{self.tier.value} memory requires only session_id")
        elif self.tier is MemoryTier.SEMANTIC:
            if (
                self.namespace_id is None
                or self.session_id is not None
                or self.agent_def_id is not None
            ):
                raise ValueError("SEMANTIC memory requires only namespace_id")
        elif (
            self.agent_def_id is None
            or self.namespace_id is not None
            or self.session_id is not None
        ):
            raise ValueError("PROCEDURAL memory requires only agent_def_id")
        return self


class MemoryRef(_FrozenModel):
    id: UUID
    workspace_id: UUID
    namespace_id: UUID
    version: int = Field(gt=0)


class PromotionCommand(_FrozenModel):
    entry_id: UUID
    promotion_id: UUID
    workspace_id: UUID
    source_session_id: UUID
    source_artifact_id: UUID
    target_namespace_id: UUID
    validator_class: ActorClass = ActorClass.HUMAN
    validator_id: UUID
    second_validator_id: UUID | None = None
    evidence_artifact_ids: tuple[UUID, ...] = Field(min_length=1)
    justification: str = Field(min_length=1)
    caveats: tuple[str, ...] = Field(min_length=1)
    promoted_at: datetime
    review_by: datetime | None = None
    supersedes_entry_id: UUID | None = None

    _timestamps = field_validator("promoted_at", "review_by")(_aware)
    _justification = field_validator("justification")(_not_blank)

    @field_validator("caveats")
    @classmethod
    def _caveats_not_blank(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_not_blank(value) for value in values)

    @model_validator(mode="after")
    def _validation_shape(self) -> PromotionCommand:
        if self.validator_class is not ActorClass.HUMAN:
            raise ValueError("promotion validator must be HUMAN")
        if len(set(self.evidence_artifact_ids)) != len(self.evidence_artifact_ids):
            raise ValueError("evidence_artifact_ids must be unique")
        if self.second_validator_id == self.validator_id:
            raise ValueError("second validator must be independent")
        if self.review_by is not None and self.review_by <= self.promoted_at:
            raise ValueError("review_by must be after promoted_at")
        return self


class ArtifactRef(_FrozenModel):
    entry_id: UUID
    promotion_id: UUID
    workspace_id: UUID
    session_id: UUID
    artifact_id: UUID
    supersedes_entry_id: UUID | None = None


class ValidationRecord(_FrozenModel):
    validator_class: ActorClass = ActorClass.HUMAN
    validator_id: UUID
    second_validator_id: UUID | None = None
    evidence_artifact_ids: tuple[UUID, ...] = Field(min_length=1)
    justification: str = Field(min_length=1)
    caveats: tuple[str, ...] = Field(min_length=1)
    validated_at: datetime
    review_by: datetime | None = None

    _timestamps = field_validator("validated_at", "review_by")(_aware)
    _justification = field_validator("justification")(_not_blank)

    @field_validator("caveats")
    @classmethod
    def _caveats_not_blank(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_not_blank(value) for value in values)

    @model_validator(mode="after")
    def _validation_shape(self) -> ValidationRecord:
        if self.validator_class is not ActorClass.HUMAN:
            raise ValueError("promotion validator must be HUMAN")
        if len(set(self.evidence_artifact_ids)) != len(self.evidence_artifact_ids):
            raise ValueError("evidence_artifact_ids must be unique")
        if self.second_validator_id == self.validator_id:
            raise ValueError("second validator must be independent")
        if self.review_by is not None and self.review_by <= self.validated_at:
            raise ValueError("review_by must be after validated_at")
        return self


class MemoryQuery(_FrozenModel):
    entry_id: UUID
    as_of: datetime

    _as_of = field_validator("as_of")(_aware)


class RetentionPolicy(_FrozenModel):
    event_id: UUID
    entry_id: UUID
    state: MemoryState
    actor_class: ActorClass = ActorClass.HUMAN
    actor_id: UUID
    reason: str = Field(min_length=1)
    recorded_at: datetime

    _reason = field_validator("reason")(_not_blank)
    _recorded_at = field_validator("recorded_at")(_aware)

    @model_validator(mode="after")
    def _transition_shape(self) -> RetentionPolicy:
        if self.state is MemoryState.ACTIVE:
            raise ValueError("retention cannot restore ACTIVE state")
        if self.actor_class is not ActorClass.HUMAN:
            raise ValueError("retention actor must be HUMAN")
        return self


class MemoryEntry(MemoryRef):
    source_session_id: UUID
    source_artifact_id: UUID
    source_artifact_kind: str
    source_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    supersedes_entry_id: UUID | None = None
    promotion_id: UUID
    validator_id: UUID
    second_validator_id: UUID | None = None
    evidence_artifact_ids: tuple[UUID, ...]
    justification: str
    caveats: tuple[str, ...]
    promoted_at: datetime
    review_by: datetime | None = None
    state: MemoryState

    _timestamps = field_validator("promoted_at", "review_by")(_aware)


class MemoryLifecycleCommand(_FrozenModel):
    event_id: UUID
    workspace_id: UUID
    entry_id: UUID
    state: MemoryState
    actor_class: ActorClass = ActorClass.HUMAN
    actor_id: UUID
    reason: str = Field(min_length=1)
    recorded_at: datetime

    _reason = field_validator("reason")(_not_blank)
    _recorded_at = field_validator("recorded_at")(_aware)

    @model_validator(mode="after")
    def _transition_shape(self) -> MemoryLifecycleCommand:
        if self.state is MemoryState.ACTIVE:
            raise ValueError("lifecycle event cannot restore ACTIVE state")
        if self.actor_class is not ActorClass.HUMAN:
            raise ValueError("lifecycle actor must be HUMAN")
        return self


class MemoryLifecycleEvent(_FrozenModel):
    event_id: UUID
    workspace_id: UUID
    entry_id: UUID
    state: MemoryState
    actor_id: UUID
    reason: str
    recorded_at: datetime

    _recorded_at = field_validator("recorded_at")(_aware)


class MemoryResult(_FrozenModel):
    entries: tuple[MemoryEntry, ...]


@runtime_checkable
class MemoryProvider(Protocol):
    async def write(self, scope: MemoryScope, entry: MemoryEntry) -> MemoryRef: ...

    async def promote(
        self, source: ArtifactRef, target: MemoryScope, validation: ValidationRecord
    ) -> MemoryRef: ...

    async def read(self, scope: MemoryScope, query: MemoryQuery) -> MemoryResult: ...

    async def expire(self, scope: MemoryScope, policy: RetentionPolicy) -> int: ...
