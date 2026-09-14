"""Validate and enqueue session controls without giving the API lifecycle authority."""

from __future__ import annotations

from app.common.errors import ValidationFailed, WorkflowUnreachable
from app.domain.session_bootstrap import session_workflow_id
from app.domain.session_control import (
    SESSION_CONTROL_SIGNAL,
    SessionControlCommand,
    SessionControlKind,
)
from app.domain.session_lifecycle import (
    TERMINAL_SESSION_STATES,
    InvalidSessionTransition,
    SessionLifecycle,
    SessionLifecycleState,
    validate_session_transition,
)
from app.ports.errors import PortError
from app.ports.workflow import WorkflowEngine, WorkflowSignal

__all__ = ["SessionControlService", "validate_control_request"]


def validate_control_request(kind: SessionControlKind, lifecycle: SessionLifecycle) -> None:
    if lifecycle.workflow_id is None:
        raise InvalidSessionTransition("session has not been started")
    if lifecycle.state in TERMINAL_SESSION_STATES:
        raise InvalidSessionTransition(f"session is already terminal in {lifecycle.state}")
    if kind is SessionControlKind.HUMAN_INPUT:
        if lifecycle.state not in {
            SessionLifecycleState.RUNNING,
            SessionLifecycleState.WAITING_FOR_HUMAN,
            SessionLifecycleState.PAUSED,
        }:
            raise InvalidSessionTransition(
                f"human input is not accepted while session is {lifecycle.state}"
            )
        return
    target = {
        SessionControlKind.PAUSE: SessionLifecycleState.PAUSED,
        SessionControlKind.RESUME: SessionLifecycleState.RUNNING,
        SessionControlKind.CANCEL: SessionLifecycleState.CANCELLED,
    }[kind]
    validate_session_transition(
        lifecycle.state,
        target,
        current_round=lifecycle.round,
        next_round=lifecycle.round,
    )


class SessionControlService:
    def __init__(self, workflows: WorkflowEngine, *, timeout_s: float = 5.0) -> None:
        self._workflows = workflows
        self._timeout_s = timeout_s

    async def enqueue(self, command: SessionControlCommand) -> None:
        try:
            await self._workflows.signal(
                session_workflow_id(command.session_id),
                WorkflowSignal(
                    name=SESSION_CONTROL_SIGNAL,
                    payload=command.model_dump(mode="json"),
                ),
                timeout_s=self._timeout_s,
            )
        except PortError as exc:
            raise WorkflowUnreachable("the session control could not be delivered") from exc
        except ValueError as exc:
            raise ValidationFailed("the session control is invalid") from exc
