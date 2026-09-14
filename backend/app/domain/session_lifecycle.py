"""Authoritative Phase 4 session lifecycle and transactional persistence boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.reasoning_ledger import LedgerAppend

__all__ = [
    "InvalidSessionTransition",
    "SessionLifecycle",
    "SessionLifecycleState",
    "SessionLifecycleStore",
    "SessionTransition",
    "validate_session_transition",
]


class InvalidSessionTransition(ValueError):
    """A lifecycle command does not follow the complete coordinator state graph."""


class SessionLifecycleState(StrEnum):
    DRAFT = "DRAFT"
    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    WAITING_FOR_AGENT = "WAITING_FOR_AGENT"
    WAITING_FOR_EVIDENCE = "WAITING_FOR_EVIDENCE"
    WAITING_FOR_CRITIQUE = "WAITING_FOR_CRITIQUE"
    WAITING_FOR_SIMULATION = "WAITING_FOR_SIMULATION"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    EVALUATING_CONSENSUS = "EVALUATING_CONSENSUS"
    PAUSED = "PAUSED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    COMPLETED = "COMPLETED"
    PARTIAL_CONSENSUS_STATE = "PARTIAL_CONSENSUS_STATE"
    NO_CONSENSUS = "NO_CONSENSUS"
    DEADLOCK = "DEADLOCK"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_TRANSITIONS: dict[SessionLifecycleState, frozenset[SessionLifecycleState]] = {
    SessionLifecycleState.DRAFT: frozenset(
        {SessionLifecycleState.INITIALIZING, SessionLifecycleState.FAILED}
    ),
    SessionLifecycleState.INITIALIZING: frozenset(
        {
            SessionLifecycleState.RUNNING,
            SessionLifecycleState.FAILED_RETRYABLE,
            SessionLifecycleState.FAILED,
            SessionLifecycleState.CANCELLED,
        }
    ),
    SessionLifecycleState.RUNNING: frozenset(
        {
            SessionLifecycleState.WAITING_FOR_AGENT,
            SessionLifecycleState.WAITING_FOR_EVIDENCE,
            SessionLifecycleState.WAITING_FOR_CRITIQUE,
            SessionLifecycleState.WAITING_FOR_SIMULATION,
            SessionLifecycleState.WAITING_FOR_HUMAN,
            SessionLifecycleState.EVALUATING_CONSENSUS,
            SessionLifecycleState.PAUSED,
            SessionLifecycleState.FAILED_RETRYABLE,
            SessionLifecycleState.FAILED,
            SessionLifecycleState.CANCELLED,
        }
    ),
    SessionLifecycleState.WAITING_FOR_AGENT: frozenset(
        {
            SessionLifecycleState.RUNNING,
            SessionLifecycleState.FAILED_RETRYABLE,
            SessionLifecycleState.FAILED,
            SessionLifecycleState.CANCELLED,
        }
    ),
    SessionLifecycleState.WAITING_FOR_EVIDENCE: frozenset(
        {
            SessionLifecycleState.RUNNING,
            SessionLifecycleState.FAILED_RETRYABLE,
            SessionLifecycleState.FAILED,
            SessionLifecycleState.CANCELLED,
        }
    ),
    SessionLifecycleState.WAITING_FOR_CRITIQUE: frozenset(
        {
            SessionLifecycleState.RUNNING,
            SessionLifecycleState.FAILED_RETRYABLE,
            SessionLifecycleState.FAILED,
            SessionLifecycleState.CANCELLED,
        }
    ),
    SessionLifecycleState.WAITING_FOR_SIMULATION: frozenset(
        {
            SessionLifecycleState.RUNNING,
            SessionLifecycleState.FAILED_RETRYABLE,
            SessionLifecycleState.FAILED,
            SessionLifecycleState.CANCELLED,
        }
    ),
    SessionLifecycleState.WAITING_FOR_HUMAN: frozenset(
        {
            SessionLifecycleState.RUNNING,
            SessionLifecycleState.PAUSED,
            SessionLifecycleState.FAILED,
            SessionLifecycleState.CANCELLED,
        }
    ),
    SessionLifecycleState.EVALUATING_CONSENSUS: frozenset(
        {
            SessionLifecycleState.RUNNING,
            SessionLifecycleState.COMPLETED,
            SessionLifecycleState.PARTIAL_CONSENSUS_STATE,
            SessionLifecycleState.NO_CONSENSUS,
            SessionLifecycleState.DEADLOCK,
            SessionLifecycleState.FAILED,
            SessionLifecycleState.CANCELLED,
        }
    ),
    SessionLifecycleState.PAUSED: frozenset(
        {
            SessionLifecycleState.RUNNING,
            SessionLifecycleState.FAILED,
            SessionLifecycleState.CANCELLED,
        }
    ),
    SessionLifecycleState.FAILED_RETRYABLE: frozenset(
        {
            SessionLifecycleState.RUNNING,
            SessionLifecycleState.FAILED,
            SessionLifecycleState.CANCELLED,
        }
    ),
}

TERMINAL_SESSION_STATES = frozenset(
    {
        SessionLifecycleState.COMPLETED,
        SessionLifecycleState.PARTIAL_CONSENSUS_STATE,
        SessionLifecycleState.NO_CONSENSUS,
        SessionLifecycleState.DEADLOCK,
        SessionLifecycleState.FAILED,
        SessionLifecycleState.CANCELLED,
    }
)


def validate_session_transition(
    source: SessionLifecycleState,
    target: SessionLifecycleState,
    *,
    current_round: int,
    next_round: int,
    allow_same_state: bool = False,
) -> None:
    if source is target:
        if not allow_same_state:
            raise InvalidSessionTransition("session transition must change state")
        if next_round != current_round:
            raise InvalidSessionTransition("same-state event cannot change session round")
        return
    if target not in _TRANSITIONS.get(source, frozenset()):
        raise InvalidSessionTransition(f"session cannot transition from {source} to {target}")
    if next_round < current_round:
        raise InvalidSessionTransition("session round cannot decrease")
    if next_round > current_round + 1:
        raise InvalidSessionTransition("session round can advance by at most one")
    if next_round != current_round and target is not SessionLifecycleState.RUNNING:
        raise InvalidSessionTransition("session round may advance only when entering RUNNING")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an RFC 3339 offset")
    return value.astimezone(UTC)


class SessionLifecycle(_FrozenModel):
    workspace_id: UUID
    session_id: UUID
    state: SessionLifecycleState = SessionLifecycleState.DRAFT
    round: int = Field(default=0, ge=0)
    workflow_id: str | None = Field(default=None, min_length=1)
    run_id: str | None = Field(default=None, min_length=1)
    last_event_id: UUID | None = None
    initialized_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    _timestamps = field_validator(
        "initialized_at", "started_at", "ended_at", "created_at", "updated_at"
    )(_aware_utc)

    @model_validator(mode="after")
    def consistent_projection(self) -> SessionLifecycle:
        if (self.workflow_id is None) != (self.run_id is None):
            raise ValueError("workflow_id and run_id must be set together")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.state is SessionLifecycleState.DRAFT and self.last_event_id is not None:
            raise ValueError("a draft lifecycle cannot have a transition event")
        if self.state is not SessionLifecycleState.DRAFT and self.initialized_at is None:
            raise ValueError("a non-draft lifecycle requires initialized_at")
        if (
            self.state not in {SessionLifecycleState.DRAFT, SessionLifecycleState.INITIALIZING}
            and self.started_at is None
        ):
            raise ValueError("a started lifecycle requires started_at")
        if (self.state in TERMINAL_SESSION_STATES) != (self.ended_at is not None):
            raise ValueError("ended_at must be set exactly for terminal lifecycle states")
        return self


class SessionTransition(_FrozenModel):
    source: SessionLifecycleState
    target: SessionLifecycleState
    round: int = Field(ge=0)
    event: LedgerAppend
    allow_same_state: bool = False

    @model_validator(mode="after")
    def event_matches_transition(self) -> SessionTransition:
        if self.event.round != self.round:
            raise ValueError("lifecycle event round must match transition round")
        if self.source is self.target and not self.allow_same_state:
            raise ValueError("same-state lifecycle events must be explicitly allowed")
        return self


@runtime_checkable
class SessionLifecycleStore(Protocol):
    """Caller-transaction-scoped, lock-safe lifecycle projection and ledger commit."""

    async def add_draft(
        self, workspace_id: UUID, session_id: UUID, *, created_at: datetime
    ) -> SessionLifecycle: ...

    async def get(self, workspace_id: UUID, session_id: UUID) -> SessionLifecycle | None: ...

    async def attach_workflow(
        self, workspace_id: UUID, session_id: UUID, *, workflow_id: str, run_id: str
    ) -> SessionLifecycle: ...

    async def transition(self, command: SessionTransition) -> SessionLifecycle: ...
