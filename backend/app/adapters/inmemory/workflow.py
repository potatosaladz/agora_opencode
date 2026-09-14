"""Deterministic in-memory reference adapter for ``WorkflowEngine``."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass

from app.common.clock import Clock, SystemClock
from app.ports.errors import PermanentPortError, TransientPortError
from app.ports.health import HealthStatus
from app.ports.workflow import (
    WorkflowEngine,
    WorkflowExecution,
    WorkflowExecutionStatus,
    WorkflowInput,
    WorkflowSignal,
    WorkflowStart,
)

__all__ = ["InMemoryWorkflowEngine"]

_PORT = "workflow_engine"


@dataclass(frozen=True, slots=True)
class _StoredExecution:
    description: WorkflowExecution
    workflow_input: WorkflowInput


class InMemoryWorkflowEngine:
    """Single-process adapter implementing idempotent start and engine inspection."""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._executions: dict[str, _StoredExecution] = {}
        self._closed = False
        self._lock = asyncio.Lock()
        self.signals: dict[str, list[WorkflowSignal]] = {}

    async def start(
        self,
        workflow_id: str,
        workflow_type: str,
        workflow_input: WorkflowInput,
        *,
        task_queue: str,
        timeout_s: float,
    ) -> WorkflowStart:
        self._guard("start")
        _validate_command(workflow_id, workflow_type, task_queue, timeout_s)
        async with self._lock:
            existing = self._executions.get(workflow_id)
            if existing is not None:
                return WorkflowStart(
                    workflow_id=workflow_id,
                    run_id=existing.description.run_id,
                    started=False,
                )

            run_id = hashlib.sha256(workflow_id.encode("utf-8")).hexdigest()
            description = WorkflowExecution(
                workflow_id=workflow_id,
                run_id=run_id,
                workflow_type=workflow_type,
                task_queue=task_queue,
                status=WorkflowExecutionStatus.RUNNING,
                started_at=self._clock.now(),
            )
            self._executions[workflow_id] = _StoredExecution(description, workflow_input)
            return WorkflowStart(workflow_id=workflow_id, run_id=run_id, started=True)

    async def describe(self, workflow_id: str, *, timeout_s: float) -> WorkflowExecution:
        self._guard("describe")
        if not workflow_id.strip():
            raise PermanentPortError("workflow_id must not be blank", port=_PORT)
        if timeout_s <= 0:
            raise PermanentPortError("timeout_s must be positive", port=_PORT)
        try:
            return self._executions[workflow_id].description
        except KeyError as exc:
            raise PermanentPortError(
                f"workflow {workflow_id!r} does not exist", port=_PORT, cause=exc
            ) from exc

    async def signal(
        self, workflow_id: str, workflow_signal: WorkflowSignal, *, timeout_s: float
    ) -> None:
        self._guard("signal")
        if timeout_s <= 0:
            raise PermanentPortError("timeout_s must be positive", port=_PORT)
        async with self._lock:
            if workflow_id not in self._executions:
                raise PermanentPortError(f"workflow {workflow_id!r} does not exist", port=_PORT)
            self.signals.setdefault(workflow_id, []).append(workflow_signal)

    async def health(self) -> HealthStatus:
        return HealthStatus.DOWN if self._closed else HealthStatus.OK

    async def close(self) -> None:
        self._closed = True

    def _guard(self, operation: str) -> None:
        if self._closed:
            raise TransientPortError(f"workflow engine is closed; cannot {operation}", port=_PORT)


def _validate_command(
    workflow_id: str, workflow_type: str, task_queue: str, timeout_s: float
) -> None:
    if not workflow_id.strip():
        raise PermanentPortError("workflow_id must not be blank", port=_PORT)
    if not workflow_type.strip():
        raise PermanentPortError("workflow_type must not be blank", port=_PORT)
    if not task_queue.strip():
        raise PermanentPortError("task_queue must not be blank", port=_PORT)
    if timeout_s <= 0:
        raise PermanentPortError("timeout_s must be positive", port=_PORT)


_WORKFLOW_PORT: type[WorkflowEngine] = InMemoryWorkflowEngine
