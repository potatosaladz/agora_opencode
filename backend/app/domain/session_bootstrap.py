"""Typed, replay-stable inputs for deterministic session bootstrap orchestration."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.session_lifecycle import SessionLifecycle, SessionLifecycleState

__all__ = [
    "SESSION_BOOTSTRAP_TASK_QUEUE",
    "SESSION_BOOTSTRAP_WORKFLOW",
    "BootstrapFailure",
    "SessionBootstrapInput",
    "SessionBootstrapTransition",
    "SessionTransitionCommitter",
    "bootstrap_payload",
    "session_workflow_id",
]

SESSION_BOOTSTRAP_WORKFLOW = "SessionBootstrapWorkflow"
SESSION_BOOTSTRAP_TASK_QUEUE = "session-bootstrap"


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SessionBootstrapInput(_Contract):
    """Immutable workflow history input; IDs are allocated only by the API caller."""

    workspace_id: UUID
    session_id: UUID
    initialized_event_id: UUID
    round_started_event_id: UUID
    failed_event_id: UUID
    correlation_id: UUID


class BootstrapFailure(_Contract):
    activity_type: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    retry_state: str = Field(min_length=1)
    termination_reason: str = Field(min_length=1)


class SessionBootstrapTransition(_Contract):
    workspace_id: UUID
    session_id: UUID
    event_id: UUID
    event_type: str
    source: SessionLifecycleState
    target: SessionLifecycleState
    round: int
    correlation_id: UUID
    causation_id: UUID | None = None
    failure: BootstrapFailure | None = None

    @model_validator(mode="after")
    def failure_matches_event(self) -> SessionBootstrapTransition:
        failed = self.event_type == "ACTIVITY_DEAD_LETTERED"
        if failed != (self.failure is not None):
            raise ValueError("failure must be set exactly for ACTIVITY_DEAD_LETTERED")
        return self


@runtime_checkable
class SessionTransitionCommitter(Protocol):
    async def commit(self, command: SessionBootstrapTransition) -> SessionLifecycle: ...


def bootstrap_payload(value: SessionBootstrapInput) -> dict[str, Any]:
    """Return only JSON primitives for the generic workflow-engine port."""
    return value.model_dump(mode="json")


def session_workflow_id(session_id: UUID) -> str:
    return f"session-{session_id}"
