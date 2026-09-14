"""Replay-stable commands for authenticated session controls and human directives."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.session_lifecycle import (
    TERMINAL_SESSION_STATES,
    InvalidSessionTransition,
    SessionLifecycle,
    SessionLifecycleState,
    validate_session_transition,
)

__all__ = [
    "SESSION_CONTROL_SIGNAL",
    "HumanDirective",
    "HumanDirectiveKind",
    "SessionControlCommand",
    "SessionControlKind",
    "SessionControlTransition",
    "SessionControlTransitionCommitter",
    "control_event_type",
    "control_transition",
    "session_control_ids",
]

SESSION_CONTROL_SIGNAL = "session_control"


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SessionControlKind(StrEnum):
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    CANCEL = "CANCEL"
    HUMAN_INPUT = "HUMAN_INPUT"


class HumanDirectiveKind(StrEnum):
    INJECT_EVIDENCE = "INJECT_EVIDENCE"
    ADD_CONSTRAINT = "ADD_CONSTRAINT"
    MODIFY_OBJECTIVE = "MODIFY_OBJECTIVE"
    REQUEST_SIMULATION = "REQUEST_SIMULATION"
    REQUEST_CRITIQUE = "REQUEST_CRITIQUE"
    REQUEST_ANOTHER_ROUND = "REQUEST_ANOTHER_ROUND"
    REJECT_RECOMMENDATION = "REJECT_RECOMMENDATION"
    OVERRIDE_OUTCOME = "OVERRIDE_OUTCOME"


class HumanDirective(_Contract):
    kind: HumanDirectiveKind
    instruction: str = Field(min_length=1, max_length=10_000)
    artifact_ids: tuple[UUID, ...] = ()

    @field_validator("instruction")
    @classmethod
    def instruction_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("instruction must not be blank")
        return value

    @field_validator("artifact_ids")
    @classmethod
    def artifact_ids_unique(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("artifact_ids must be unique")
        return values


class SessionControlCommand(_Contract):
    command_id: UUID
    event_id: UUID
    failure_event_id: UUID
    workspace_id: UUID
    session_id: UUID
    kind: SessionControlKind
    observed_state: SessionLifecycleState
    correlation_id: UUID
    actor_id: UUID
    requested_at: datetime
    reason: str = Field(min_length=1, max_length=2_000)
    directive: HumanDirective | None = None

    @field_validator("requested_at")
    @classmethod
    def requested_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requested_at must include an RFC 3339 offset")
        return value.astimezone(UTC)

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value

    @model_validator(mode="after")
    def directive_matches_kind(self) -> SessionControlCommand:
        required = self.kind is SessionControlKind.HUMAN_INPUT
        if required != (self.directive is not None):
            raise ValueError("directive must be set exactly for HUMAN_INPUT")
        return self


class SessionControlTransition(_Contract):
    command: SessionControlCommand
    source: SessionLifecycleState
    target: SessionLifecycleState
    round: int = Field(ge=0)


def session_control_ids(
    workspace_id: UUID,
    session_id: UUID,
    kind: SessionControlKind,
    idempotency_key: str,
    request_hash: str,
) -> tuple[UUID, UUID, UUID]:
    """Derive retry-stable identities without exposing the caller's idempotency key."""
    scope = f"agora:{workspace_id}:{session_id}:{kind.value}:{idempotency_key}:{request_hash}"
    command_id = uuid5(NAMESPACE_URL, f"{scope}:command")
    return (
        command_id,
        uuid5(NAMESPACE_URL, f"{scope}:event"),
        uuid5(NAMESPACE_URL, f"{scope}:failure"),
    )


def control_event_type(kind: SessionControlKind) -> str:
    return {
        SessionControlKind.PAUSE: "SESSION_PAUSED",
        SessionControlKind.RESUME: "SESSION_RESUMED",
        SessionControlKind.CANCEL: "SESSION_CANCELLED",
        SessionControlKind.HUMAN_INPUT: "HUMAN_DIRECTIVE",
    }[kind]


def control_transition(
    command: SessionControlCommand,
    current_state: SessionLifecycleState,
    current_round: int,
) -> SessionControlTransition:
    """Interpret one command using only workflow-history state."""
    if current_state in TERMINAL_SESSION_STATES:
        raise InvalidSessionTransition(f"session is already terminal in {current_state}")
    if command.kind is SessionControlKind.PAUSE:
        target = SessionLifecycleState.PAUSED
    elif command.kind is SessionControlKind.RESUME:
        target = SessionLifecycleState.RUNNING
    elif command.kind is SessionControlKind.CANCEL:
        target = SessionLifecycleState.CANCELLED
    elif current_state is SessionLifecycleState.WAITING_FOR_HUMAN:
        target = SessionLifecycleState.RUNNING
    else:
        target = current_state
    validate_session_transition(
        current_state,
        target,
        current_round=current_round,
        next_round=current_round,
        allow_same_state=command.kind is SessionControlKind.HUMAN_INPUT,
    )
    return SessionControlTransition(
        command=command,
        source=current_state,
        target=target,
        round=current_round,
    )


@runtime_checkable
class SessionControlTransitionCommitter(Protocol):
    async def commit(self, transition: SessionControlTransition) -> SessionLifecycle: ...
