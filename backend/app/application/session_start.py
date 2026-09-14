"""Idempotently attach one durable bootstrap workflow to a bound draft session."""

from __future__ import annotations

from app.common.errors import WorkflowUnreachable
from app.domain.session_bootstrap import (
    SESSION_BOOTSTRAP_TASK_QUEUE,
    SESSION_BOOTSTRAP_WORKFLOW,
    SessionBootstrapInput,
    bootstrap_payload,
    session_workflow_id,
)
from app.domain.session_lifecycle import SessionLifecycle, SessionLifecycleStore
from app.ports.errors import PortError
from app.ports.workflow import WorkflowEngine, WorkflowInput

__all__ = ["SessionStartService"]


class SessionStartService:
    def __init__(
        self,
        lifecycle: SessionLifecycleStore,
        workflows: WorkflowEngine,
        *,
        task_queue: str = SESSION_BOOTSTRAP_TASK_QUEUE,
        timeout_s: float = 5.0,
    ) -> None:
        self._lifecycle = lifecycle
        self._workflows = workflows
        self._task_queue = task_queue
        self._timeout_s = timeout_s

    async def start(self, bootstrap: SessionBootstrapInput) -> SessionLifecycle:
        workflow_id = session_workflow_id(bootstrap.session_id)
        try:
            execution = await self._workflows.start(
                workflow_id,
                SESSION_BOOTSTRAP_WORKFLOW,
                WorkflowInput(payload=bootstrap_payload(bootstrap)),
                task_queue=self._task_queue,
                timeout_s=self._timeout_s,
            )
        except PortError as exc:
            raise WorkflowUnreachable("the session workflow could not be started") from exc
        return await self._lifecycle.attach_workflow(
            bootstrap.workspace_id,
            bootstrap.session_id,
            workflow_id=execution.workflow_id,
            run_id=execution.run_id,
        )
