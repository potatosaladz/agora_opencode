"""Typed client boundary for durable workflow execution.

The port intentionally excludes worker registration and coordinator behavior. Workflow and
activity definitions belong to worker composition (T4-02/T4-03); lifecycle signals belong to
T4-04. PostgreSQL remains authoritative for session status. ``describe`` exposes only the
execution engine's diagnostic state.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.ports.health import HealthStatus

__all__ = [
    "JsonObject",
    "JsonValue",
    "WorkflowEngine",
    "WorkflowExecution",
    "WorkflowExecutionStatus",
    "WorkflowInput",
    "WorkflowSignal",
    "WorkflowStart",
    "WorkflowWorker",
]

type JsonScalar = str | int | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class WorkflowExecutionStatus(StrEnum):
    """Transport execution state, not the authoritative session lifecycle."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    TERMINATED = "TERMINATED"
    CONTINUED_AS_NEW = "CONTINUED_AS_NEW"
    TIMED_OUT = "TIMED_OUT"
    UNKNOWN = "UNKNOWN"


class WorkflowInput(_Contract):
    """Versioned JSON input passed as the workflow's single argument."""

    payload: JsonObject = Field(default_factory=dict)
    schema_version: int = Field(default=1, ge=1)


class WorkflowStart(_Contract):
    """Identity returned by an idempotent start request."""

    workflow_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    started: bool


class WorkflowSignal(_Contract):
    """Named, versioned JSON signal accepted by one workflow execution."""

    name: str = Field(min_length=1)
    payload: JsonObject = Field(default_factory=dict)
    schema_version: int = Field(default=1, ge=1)


class WorkflowExecution(_Contract):
    """Diagnostic execution-engine metadata.

    API and application code must read authoritative session status from PostgreSQL rather
    than translate this value into a session transition.
    """

    workflow_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    workflow_type: str = Field(min_length=1)
    task_queue: str = Field(min_length=1)
    status: WorkflowExecutionStatus
    started_at: datetime
    closed_at: datetime | None = None


@runtime_checkable
class WorkflowEngine(Protocol):
    """Start and inspect durable workflows without exposing an infrastructure SDK."""

    async def start(
        self,
        workflow_id: str,
        workflow_type: str,
        workflow_input: WorkflowInput,
        *,
        task_queue: str,
        timeout_s: float,
    ) -> WorkflowStart: ...

    async def describe(self, workflow_id: str, *, timeout_s: float) -> WorkflowExecution: ...

    async def signal(
        self, workflow_id: str, workflow_signal: WorkflowSignal, *, timeout_s: float
    ) -> None: ...

    async def health(self) -> HealthStatus: ...

    async def close(self) -> None: ...


@runtime_checkable
class WorkflowWorker(Protocol):
    """Lifecycle only; concrete definitions are supplied at worker composition time."""

    async def run(self) -> None: ...

    async def shutdown(self) -> None: ...
