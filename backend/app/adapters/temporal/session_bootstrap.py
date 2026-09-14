"""Deterministic Temporal workflow and I/O activity for T4-02 session bootstrap."""

from __future__ import annotations

import json
from typing import Any

from temporalio import activity, workflow
from temporalio.exceptions import ActivityError

from app.domain.orchestration_policy import STATE_COMMIT_POLICY, activity_operation_id
from app.domain.session_bootstrap import (
    SESSION_BOOTSTRAP_WORKFLOW,
    BootstrapFailure,
    SessionBootstrapInput,
    SessionBootstrapTransition,
    SessionTransitionCommitter,
)
from app.domain.session_control import (
    SESSION_CONTROL_SIGNAL,
    SessionControlCommand,
    control_transition,
)
from app.domain.session_lifecycle import (
    InvalidSessionTransition,
    SessionLifecycle,
    SessionLifecycleState,
)
from app.ports.workflow import WorkflowInput, WorkflowSignal

from .activity_policy import activity_options, run_activity, temporal_retry_policy
from .session_control import SESSION_CONTROL_ACTIVITY

__all__ = ["SessionBootstrapActivities", "SessionBootstrapWorkflow"]

_ACTIVITY = "commit_session_bootstrap_transition"


class SessionBootstrapActivities:
    def __init__(self, committer: SessionTransitionCommitter) -> None:
        self._committer = committer

    @activity.defn(name=_ACTIVITY)
    async def commit_transition(self, raw: dict[str, Any]) -> dict[str, Any]:
        async def commit() -> SessionLifecycle:
            command = SessionBootstrapTransition.model_validate_json(json.dumps(raw))
            return await self._committer.commit(command)

        projection = await run_activity(commit)
        return projection.model_dump(mode="json")


@workflow.defn(name=SESSION_BOOTSTRAP_WORKFLOW)
class SessionBootstrapWorkflow:
    """Bootstrap a draft through round-one start and then park durably."""

    def __init__(self) -> None:
        self._pending_controls: list[SessionControlCommand] = []
        self._processed_control_ids: set[str] = set()
        self._state = SessionLifecycleState.DRAFT
        self._round = 0

    @workflow.signal(name=SESSION_CONTROL_SIGNAL)
    def receive_control(self, raw: dict[str, Any]) -> None:
        signal = WorkflowSignal.model_validate_json(json.dumps(raw))
        self._pending_controls.append(
            SessionControlCommand.model_validate_json(json.dumps(signal.payload))
        )

    @workflow.run
    async def run(self, raw: dict[str, Any]) -> None:
        envelope = WorkflowInput.model_validate_json(json.dumps(raw))
        bootstrap = SessionBootstrapInput.model_validate_json(json.dumps(envelope.payload))
        try:
            await self._transition(
                SessionBootstrapTransition(
                    workspace_id=bootstrap.workspace_id,
                    session_id=bootstrap.session_id,
                    event_id=bootstrap.initialized_event_id,
                    event_type="SESSION_INITIALIZED",
                    source=SessionLifecycleState.DRAFT,
                    target=SessionLifecycleState.INITIALIZING,
                    round=0,
                    correlation_id=bootstrap.correlation_id,
                )
            )
            self._state = SessionLifecycleState.INITIALIZING
            await self._transition(
                SessionBootstrapTransition(
                    workspace_id=bootstrap.workspace_id,
                    session_id=bootstrap.session_id,
                    event_id=bootstrap.round_started_event_id,
                    event_type="ROUND_STARTED",
                    source=SessionLifecycleState.INITIALIZING,
                    target=SessionLifecycleState.RUNNING,
                    round=1,
                    correlation_id=bootstrap.correlation_id,
                    causation_id=bootstrap.initialized_event_id,
                )
            )
            self._state = SessionLifecycleState.RUNNING
            self._round = 1
        except ActivityError as exc:
            failed_event_id = (
                bootstrap.initialized_event_id
                if self._state is SessionLifecycleState.DRAFT
                else bootstrap.round_started_event_id
            )
            operation_id = activity_operation_id(
                str(bootstrap.session_id), _ACTIVITY, str(failed_event_id)
            )
            await self._transition(
                SessionBootstrapTransition(
                    workspace_id=bootstrap.workspace_id,
                    session_id=bootstrap.session_id,
                    event_id=bootstrap.failed_event_id,
                    event_type="ACTIVITY_DEAD_LETTERED",
                    source=self._state,
                    target=SessionLifecycleState.FAILED,
                    round=self._round,
                    correlation_id=bootstrap.correlation_id,
                    causation_id=(
                        bootstrap.initialized_event_id
                        if self._state is not SessionLifecycleState.DRAFT
                        else None
                    ),
                    failure=BootstrapFailure(
                        activity_type=exc.activity_type,
                        operation_id=operation_id,
                        retry_state=(
                            exc.retry_state.name if exc.retry_state is not None else "UNKNOWN"
                        ),
                        termination_reason="ACTIVITY_POLICY_EXHAUSTED",
                    ),
                )
            )
            raise
        while self._state is not SessionLifecycleState.CANCELLED:
            await workflow.wait_condition(lambda: bool(self._pending_controls))
            command = self._pending_controls.pop(0)
            identity = str(command.command_id)
            if identity in self._processed_control_ids:
                continue
            try:
                transition = control_transition(command, self._state, self._round)
            except InvalidSessionTransition:
                # The API validates against the authoritative projection, but another accepted
                # signal may commit first. A stale command must not poison the workflow task loop.
                self._processed_control_ids.add(identity)
                continue
            operation_id = activity_operation_id(
                str(command.session_id), SESSION_CONTROL_ACTIVITY, str(command.command_id)
            )
            try:
                await workflow.execute_activity(
                    SESSION_CONTROL_ACTIVITY,
                    transition.model_dump(mode="json"),
                    activity_id=operation_id,
                    start_to_close_timeout=activity_options(
                        STATE_COMMIT_POLICY
                    ).start_to_close_timeout,
                    schedule_to_close_timeout=activity_options(
                        STATE_COMMIT_POLICY
                    ).schedule_to_close_timeout,
                    retry_policy=temporal_retry_policy(STATE_COMMIT_POLICY),
                )
            except ActivityError as exc:
                await self._transition(
                    SessionBootstrapTransition(
                        workspace_id=command.workspace_id,
                        session_id=command.session_id,
                        event_id=command.failure_event_id,
                        event_type="ACTIVITY_DEAD_LETTERED",
                        source=self._state,
                        target=SessionLifecycleState.FAILED,
                        round=self._round,
                        correlation_id=command.correlation_id,
                        causation_id=command.event_id,
                        failure=BootstrapFailure(
                            activity_type=exc.activity_type,
                            operation_id=operation_id,
                            retry_state=(
                                exc.retry_state.name if exc.retry_state is not None else "UNKNOWN"
                            ),
                            termination_reason="ACTIVITY_POLICY_EXHAUSTED",
                        ),
                    )
                )
                raise
            self._state = transition.target
            self._round = transition.round
            self._processed_control_ids.add(identity)

    async def _transition(self, command: SessionBootstrapTransition) -> None:
        await workflow.execute_activity(
            _ACTIVITY,
            command.model_dump(mode="json"),
            activity_id=activity_operation_id(
                str(command.session_id), _ACTIVITY, str(command.event_id)
            ),
            start_to_close_timeout=activity_options(STATE_COMMIT_POLICY).start_to_close_timeout,
            schedule_to_close_timeout=activity_options(
                STATE_COMMIT_POLICY
            ).schedule_to_close_timeout,
            retry_policy=temporal_retry_policy(STATE_COMMIT_POLICY),
        )
