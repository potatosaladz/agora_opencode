"""Immutable Phase 3 reasoning-ledger contract and hash identity."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, cast, runtime_checkable
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.domain.reasoning import ActorClass, FrozenModel, _frozen_json, content_hash

__all__ = [
    "GENESIS_HASH",
    "AgentProposalLedger",
    "LedgerAppend",
    "LedgerEvent",
    "LedgerIntegrityError",
    "LedgerVerification",
    "ReasoningLedger",
    "ledger_event_hash",
    "ledger_payload_hash",
]

GENESIS_HASH = "sha256:" + "0" * 64


class LedgerIntegrityError(Exception):
    """An event id was reused with different content or ledger state is inconsistent."""


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an RFC 3339 offset")
    return value.astimezone(UTC)


def _json_payload(value: dict[str, Any]) -> dict[str, Any]:
    content_hash(value)
    return cast(dict[str, Any], _frozen_json(value))


class LedgerAppend(FrozenModel):
    """Caller-supplied immutable values for one idempotent append."""

    id: UUID
    workspace_id: UUID
    session_id: UUID
    event_type: str = Field(min_length=1)
    payload_schema_version: int = Field(gt=0)
    causation_id: UUID | None = None
    correlation_id: UUID
    actor_class: ActorClass
    actor_id: UUID
    round: int = Field(default=0, ge=0)
    payload: dict[str, Any]
    recorded_at: datetime

    _payload_json = field_validator("payload")(_json_payload)
    _recorded_at_utc = field_validator("recorded_at")(_aware_utc)

    @field_validator("event_type")
    @classmethod
    def event_type_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("event_type must not be blank")
        return value


class LedgerEvent(LedgerAppend):
    """Persisted event with ledger-assigned order and chain identity."""

    ledger_seq: int = Field(gt=0)
    payload_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    prev_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    event_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class LedgerVerification(FrozenModel):
    """Complete verification result; first failure identifies corrupt position."""

    valid: bool
    event_count: int = Field(ge=0)
    head_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    first_invalid_seq: int | None = Field(default=None, gt=0)
    reason: str | None = None

    @model_validator(mode="after")
    def failure_shape(self) -> LedgerVerification:
        if self.valid and (self.first_invalid_seq is not None or self.reason is not None):
            raise ValueError("valid verification cannot describe a failure")
        if not self.valid and self.reason is None:
            raise ValueError("invalid verification requires a reason")
        return self


def ledger_payload_hash(payload: dict[str, Any]) -> str:
    return content_hash(payload)


def _timestamp(value: datetime) -> str:
    return _aware_utc(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def ledger_event_hash(event: LedgerEvent) -> str:
    """Hash exact frozen DATA_MODEL §11.0 event preimage."""
    return content_hash(
        {
            "actor_class": event.actor_class.value,
            "actor_id": str(event.actor_id),
            "causation_id": str(event.causation_id) if event.causation_id is not None else None,
            "correlation_id": str(event.correlation_id),
            "event_type": event.event_type,
            "id": str(event.id),
            "ledger_seq": event.ledger_seq,
            "payload_hash": event.payload_hash,
            "payload_schema_version": event.payload_schema_version,
            "prev_hash": event.prev_hash,
            "recorded_at": _timestamp(event.recorded_at),
            "round": event.round,
            "session_id": str(event.session_id),
            "workspace_id": str(event.workspace_id),
        }
    )


@runtime_checkable
class ReasoningLedger(Protocol):
    """Caller-transaction-scoped append, ordered read, and verification boundary."""

    async def append(self, event: LedgerAppend) -> LedgerEvent: ...

    async def read(
        self, workspace_id: UUID, session_id: UUID, *, from_seq: int = 1, limit: int = 1000
    ) -> Sequence[LedgerEvent]: ...

    async def verify(self, workspace_id: UUID, session_id: UUID) -> LedgerVerification: ...


@runtime_checkable
class AgentProposalLedger(ReasoningLedger, Protocol):
    """Ledger operations required for idempotent logical-turn commits."""

    async def get_by_id(
        self, workspace_id: UUID, session_id: UUID, event_id: UUID
    ) -> LedgerEvent | None: ...
