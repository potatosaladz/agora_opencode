"""Typed session-control identities, transitions, signaling, and retry tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.adapters.inmemory.session_lifecycle import InMemorySessionLifecycleStore
from app.adapters.temporal.session_control import SessionControlActivities
from app.application.session_control import SessionControlService, validate_control_request
from app.domain.reasoning import ActorClass
from app.domain.reasoning_ledger import LedgerAppend
from app.domain.session_control import (
    HumanDirective,
    HumanDirectiveKind,
    SessionControlCommand,
    SessionControlKind,
    control_transition,
    session_control_ids,
)
from app.domain.session_lifecycle import (
    InvalidSessionTransition,
    SessionLifecycle,
    SessionLifecycleState,
    SessionTransition,
)
from app.ports.workflow import WorkflowInput
from tests.traceability import req
from tests.unit.test_session_lifecycle import NOW, RecordingLedger, U, transition


def command(kind: SessionControlKind, *, command_id: UUID = U[5]) -> SessionControlCommand:
    return SessionControlCommand(
        command_id=command_id,
        event_id=U[6],
        failure_event_id=U[7],
        workspace_id=U[0],
        session_id=U[1],
        kind=kind,
        observed_state=SessionLifecycleState.RUNNING,
        correlation_id=U[2],
        actor_id=U[3],
        requested_at=datetime(2026, 9, 5, 12, tzinfo=UTC),
        reason="Operator requested control",
    )


@req("FR-104", "FR-207")
def test_control_ids_are_stable_and_content_scoped() -> None:
    first = session_control_ids(U[0], U[1], SessionControlKind.PAUSE, "key", "hash-a")
    assert first == session_control_ids(U[0], U[1], SessionControlKind.PAUSE, "key", "hash-a")
    assert first != session_control_ids(U[0], U[1], SessionControlKind.PAUSE, "key", "hash-b")
    assert len(set(first)) == 3


@req("FR-104", "FR-207")
def test_directives_are_strict_and_require_matching_command_kind() -> None:
    with pytest.raises(ValidationError):
        HumanDirective.model_validate({"kind": "UNKNOWN", "instruction": "Continue"})
    with pytest.raises(ValidationError, match="unique"):
        HumanDirective(
            kind=HumanDirectiveKind.INJECT_EVIDENCE,
            instruction="Use evidence",
            artifact_ids=(U[7], U[7]),
        )
    with pytest.raises(ValidationError, match="exactly for HUMAN_INPUT"):
        command(SessionControlKind.HUMAN_INPUT)


@req("FR-104", "FR-207")
@pytest.mark.parametrize(
    ("kind", "source", "target"),
    [
        (SessionControlKind.PAUSE, SessionLifecycleState.RUNNING, SessionLifecycleState.PAUSED),
        (SessionControlKind.RESUME, SessionLifecycleState.PAUSED, SessionLifecycleState.RUNNING),
        (SessionControlKind.CANCEL, SessionLifecycleState.RUNNING, SessionLifecycleState.CANCELLED),
    ],
)
def test_control_transitions_follow_lifecycle_graph(
    kind: SessionControlKind, source: SessionLifecycleState, target: SessionLifecycleState
) -> None:
    assert control_transition(command(kind), source, 2).target is target


@req("FR-104", "FR-207")
def test_illegal_control_and_terminal_replay_are_rejected() -> None:
    with pytest.raises(InvalidSessionTransition):
        control_transition(command(SessionControlKind.RESUME), SessionLifecycleState.RUNNING, 1)
    with pytest.raises(InvalidSessionTransition, match="terminal"):
        control_transition(command(SessionControlKind.CANCEL), SessionLifecycleState.COMPLETED, 1)


@req("FR-104", "FR-207")
async def test_signal_delivery_and_activity_retry_commit_once() -> None:
    from app.adapters.inmemory.workflow import InMemoryWorkflowEngine

    engine = InMemoryWorkflowEngine()
    await engine.start(
        f"session-{U[1]}", "Workflow", WorkflowInput(), task_queue="queue", timeout_s=1
    )
    pause = command(SessionControlKind.PAUSE)
    await SessionControlService(engine).enqueue(pause)
    assert engine.signals[f"session-{U[1]}"][0].payload["command_id"] == str(U[5])

    ledger = RecordingLedger()
    store = InMemorySessionLifecycleStore(ledger)
    await store.add_draft(U[0], U[1], created_at=NOW)
    await store.attach_workflow(U[0], U[1], workflow_id="workflow", run_id="run")
    await store.transition(
        transition(U[4], SessionLifecycleState.DRAFT, SessionLifecycleState.INITIALIZING)
    )
    await store.transition(
        transition(
            U[8], SessionLifecycleState.INITIALIZING, SessionLifecycleState.RUNNING, round_=1
        )
    )
    interpreted = control_transition(pause, SessionLifecycleState.RUNNING, 1)

    class Committer:
        async def commit(self, received: Any) -> SessionLifecycle:
            return await store.transition(
                SessionTransition(
                    source=received.source,
                    target=received.target,
                    round=received.round,
                    event=LedgerAppend(
                        id=received.command.event_id,
                        workspace_id=received.command.workspace_id,
                        session_id=received.command.session_id,
                        event_type="SESSION_PAUSED",
                        payload_schema_version=1,
                        correlation_id=received.command.correlation_id,
                        actor_class=ActorClass.HUMAN,
                        actor_id=received.command.actor_id,
                        round=received.round,
                        payload={"command_id": str(received.command.command_id)},
                        recorded_at=received.command.requested_at,
                    ),
                )
            )

    activity = SessionControlActivities(Committer())
    raw = interpreted.model_dump(mode="json")
    first = await activity.commit_transition(raw)
    replay = await activity.commit_transition(raw)
    assert first == replay
    assert first["state"] == "PAUSED"
    assert [event.id for event in ledger.events].count(pause.event_id) == 1


@req("FR-104", "FR-207")
async def test_request_validation_uses_postgres_projection_state() -> None:
    ledger = RecordingLedger()
    store = InMemorySessionLifecycleStore(ledger)
    draft = await store.add_draft(U[0], U[1], created_at=NOW)
    with pytest.raises(InvalidSessionTransition, match="not been started"):
        validate_control_request(SessionControlKind.PAUSE, draft)
