"""Static determinism and typed activity tests for T4-02 bootstrap orchestration."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, RetryState
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from app.adapters.temporal.session_bootstrap import (
    SessionBootstrapActivities,
    SessionBootstrapWorkflow,
)
from app.domain.session_bootstrap import SessionBootstrapInput, SessionBootstrapTransition
from app.domain.session_control import SessionControlCommand, SessionControlKind
from app.domain.session_lifecycle import SessionLifecycle, SessionLifecycleState
from app.ports.workflow import WorkflowInput, WorkflowSignal
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 11))


class Committer:
    def __init__(self) -> None:
        self.command: SessionBootstrapTransition | None = None

    async def commit(self, command: SessionBootstrapTransition) -> SessionLifecycle:
        self.command = command
        return SessionLifecycle.model_validate_json(
            json.dumps(
                {
                    "workspace_id": command.workspace_id,
                    "session_id": command.session_id,
                    "state": "INITIALIZING",
                    "round": 0,
                    "last_event_id": command.event_id,
                    "initialized_at": "2026-09-05T12:00:00Z",
                    "created_at": "2026-09-05T11:00:00Z",
                    "updated_at": "2026-09-05T12:00:00Z",
                },
                default=str,
            )
        )


@req("FR-105", "FR-207", "NFR-001", "NFR-020")
async def test_activity_decodes_strict_transition_and_delegates_io() -> None:
    committer = Committer()
    result = await SessionBootstrapActivities(committer).commit_transition(
        {
            "workspace_id": str(U[0]),
            "session_id": str(U[1]),
            "event_id": str(U[2]),
            "event_type": "SESSION_INITIALIZED",
            "source": "DRAFT",
            "target": "INITIALIZING",
            "round": 0,
            "correlation_id": str(U[3]),
            "causation_id": None,
        }
    )

    assert committer.command is not None
    assert committer.command.target is SessionLifecycleState.INITIALIZING
    assert result["state"] == "INITIALIZING"


@req("FR-105", "FR-207", "NFR-001", "NFR-020")
async def test_workflow_reuses_input_event_identity_and_enters_durable_wait(
    monkeypatch: Any,
) -> None:
    activities: list[tuple[dict[str, Any], dict[str, object]]] = []
    waited = False

    async def execute_activity(_name: str, raw: dict[str, Any], **_options: object) -> None:
        activities.append((raw, _options))

    async def wait_condition(predicate: Any, **_options: object) -> None:
        nonlocal waited
        assert predicate() is False
        waited = True
        raise RuntimeError("workflow parked")

    monkeypatch.setattr(
        "app.adapters.temporal.session_bootstrap.workflow.execute_activity", execute_activity
    )
    monkeypatch.setattr(
        "app.adapters.temporal.session_bootstrap.workflow.wait_condition", wait_condition
    )
    bootstrap = SessionBootstrapInput(
        workspace_id=U[0],
        session_id=U[1],
        initialized_event_id=U[2],
        round_started_event_id=U[3],
        failed_event_id=U[4],
        correlation_id=U[5],
    )

    with pytest.raises(RuntimeError, match="workflow parked"):
        await SessionBootstrapWorkflow().run(
            WorkflowInput(payload=bootstrap.model_dump(mode="json")).model_dump(mode="json")
        )

    assert len(activities) == 2
    assert activities[0][0]["event_id"] == str(U[2])
    assert activities[0][0]["event_type"] == "SESSION_INITIALIZED"
    assert activities[1][0]["event_id"] == str(U[3])
    assert activities[1][0]["event_type"] == "ROUND_STARTED"
    assert activities[1][0]["source"] == "INITIALIZING"
    assert activities[1][0]["target"] == "RUNNING"
    assert activities[1][0]["round"] == 1
    assert activities[1][0]["causation_id"] == str(U[2])
    for raw, options in activities:
        activity_id = options["activity_id"]
        assert isinstance(activity_id, str)
        assert activity_id.endswith(raw["event_id"])
        assert options["start_to_close_timeout"] == timedelta(seconds=15)
        assert options["schedule_to_close_timeout"] == timedelta(minutes=5)
        retry = options["retry_policy"]
        assert isinstance(retry, RetryPolicy)
        assert retry.maximum_attempts == 10
    assert waited is True


@req("FR-105", "FR-207", "NFR-001", "NFR-020")
@pytest.mark.parametrize(
    ("fail_on", "source", "failed_event_id"),
    [
        (1, "DRAFT", U[2]),
        (2, "INITIALIZING", U[3]),
    ],
)
async def test_bootstrap_retry_exhaustion_commits_structured_dead_letter(
    monkeypatch: Any,
    fail_on: int,
    source: str,
    failed_event_id: UUID,
) -> None:
    activities: list[tuple[str, dict[str, Any], dict[str, object]]] = []

    async def execute_activity(name: str, raw: dict[str, Any], **options: object) -> None:
        activities.append((name, raw, options))
        if len(activities) == fail_on:
            raise ActivityError(
                "activity exhausted",
                scheduled_event_id=1,
                started_event_id=2,
                identity="worker",
                activity_type=name,
                activity_id=str(options["activity_id"]),
                retry_state=RetryState.MAXIMUM_ATTEMPTS_REACHED,
            )

    monkeypatch.setattr(
        "app.adapters.temporal.session_bootstrap.workflow.execute_activity", execute_activity
    )
    bootstrap = SessionBootstrapInput(
        workspace_id=U[0],
        session_id=U[1],
        initialized_event_id=U[2],
        round_started_event_id=U[3],
        failed_event_id=U[4],
        correlation_id=U[5],
    )

    with pytest.raises(ActivityError, match="activity exhausted"):
        await SessionBootstrapWorkflow().run(
            WorkflowInput(payload=bootstrap.model_dump(mode="json")).model_dump(mode="json")
        )

    dead_letter = activities[-1][1]
    assert dead_letter["event_id"] == str(U[4])
    assert dead_letter["event_type"] == "ACTIVITY_DEAD_LETTERED"
    assert dead_letter["source"] == source
    assert dead_letter["target"] == "FAILED"
    assert dead_letter["failure"] == {
        "activity_type": "commit_session_bootstrap_transition",
        "operation_id": (f"{U[1]}:commit_session_bootstrap_transition:{failed_event_id}"),
        "retry_state": "MAXIMUM_ATTEMPTS_REACHED",
        "termination_reason": "ACTIVITY_POLICY_EXHAUSTED",
    }


@req("FR-105", "FR-207", "NFR-001", "NFR-020")
async def test_workflow_deduplicates_controls_and_discards_stale_commands(monkeypatch: Any) -> None:
    activities: list[dict[str, Any]] = []

    async def execute_activity(_name: str, raw: dict[str, Any], **_options: object) -> None:
        activities.append(raw)

    async def wait_condition(predicate: Any, **_options: object) -> None:
        if not predicate():
            raise RuntimeError("workflow parked")

    monkeypatch.setattr(
        "app.adapters.temporal.session_bootstrap.workflow.execute_activity", execute_activity
    )
    monkeypatch.setattr(
        "app.adapters.temporal.session_bootstrap.workflow.wait_condition", wait_condition
    )
    bootstrap = SessionBootstrapInput(
        workspace_id=U[0],
        session_id=U[1],
        initialized_event_id=U[2],
        round_started_event_id=U[3],
        failed_event_id=U[4],
        correlation_id=U[5],
    )
    pause = SessionControlCommand(
        command_id=U[6],
        event_id=U[7],
        failure_event_id=U[8],
        workspace_id=U[0],
        session_id=U[1],
        kind=SessionControlKind.PAUSE,
        observed_state=SessionLifecycleState.RUNNING,
        correlation_id=U[5],
        actor_id=U[0],
        requested_at=datetime(2026, 9, 5, 12, tzinfo=UTC),
        reason="Pause once",
    )
    instance = SessionBootstrapWorkflow()
    signal = WorkflowSignal(
        name="session_control", payload=pause.model_dump(mode="json")
    ).model_dump(mode="json")
    instance.receive_control(signal)
    instance.receive_control(signal)
    instance.receive_control(
        WorkflowSignal(
            name="session_control",
            payload=pause.model_copy(update={"command_id": U[7], "event_id": U[6]}).model_dump(
                mode="json"
            ),
        ).model_dump(mode="json")
    )

    with pytest.raises(RuntimeError, match="workflow parked"):
        await instance.run(
            WorkflowInput(payload=bootstrap.model_dump(mode="json")).model_dump(mode="json")
        )

    control_activities = [raw for raw in activities if "command" in raw]
    assert len(control_activities) == 1
    assert control_activities[0]["target"] == "PAUSED"


@req("FR-105", "FR-207", "NFR-001", "NFR-020")
async def test_control_retry_exhaustion_commits_structured_dead_letter(monkeypatch: Any) -> None:
    activities: list[tuple[str, dict[str, Any], dict[str, object]]] = []

    async def execute_activity(name: str, raw: dict[str, Any], **options: object) -> None:
        activities.append((name, raw, options))
        if "command" in raw:
            raise ActivityError(
                "control exhausted",
                scheduled_event_id=1,
                started_event_id=2,
                identity="worker",
                activity_type=name,
                activity_id=str(options["activity_id"]),
                retry_state=RetryState.MAXIMUM_ATTEMPTS_REACHED,
            )

    async def wait_condition(predicate: Any, **_options: object) -> None:
        assert predicate()

    monkeypatch.setattr(
        "app.adapters.temporal.session_bootstrap.workflow.execute_activity", execute_activity
    )
    monkeypatch.setattr(
        "app.adapters.temporal.session_bootstrap.workflow.wait_condition", wait_condition
    )
    bootstrap = SessionBootstrapInput(
        workspace_id=U[0],
        session_id=U[1],
        initialized_event_id=U[2],
        round_started_event_id=U[3],
        failed_event_id=U[4],
        correlation_id=U[5],
    )
    pause = SessionControlCommand(
        command_id=U[6],
        event_id=U[7],
        failure_event_id=U[8],
        workspace_id=U[0],
        session_id=U[1],
        kind=SessionControlKind.PAUSE,
        observed_state=SessionLifecycleState.RUNNING,
        correlation_id=U[5],
        actor_id=U[9],
        requested_at=datetime(2026, 9, 5, 12, tzinfo=UTC),
        reason="Pause once",
    )
    instance = SessionBootstrapWorkflow()
    instance.receive_control(
        WorkflowSignal(name="session_control", payload=pause.model_dump(mode="json")).model_dump(
            mode="json"
        )
    )

    with pytest.raises(ActivityError, match="control exhausted"):
        await instance.run(
            WorkflowInput(payload=bootstrap.model_dump(mode="json")).model_dump(mode="json")
        )

    dead_letter = activities[-1][1]
    assert dead_letter["event_id"] == str(pause.failure_event_id)
    assert dead_letter["source"] == "RUNNING"
    assert dead_letter["target"] == "FAILED"
    assert dead_letter["causation_id"] == str(pause.event_id)
    assert dead_letter["failure"]["operation_id"].endswith(str(pause.command_id))


@req("FR-105", "FR-207", "NFR-001", "NFR-020")
def test_workflow_module_has_no_nondeterministic_io_or_identity_generation() -> None:
    source = (
        Path(__file__).parents[2] / "app" / "adapters" / "temporal" / "session_bootstrap.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    forbidden = {"datetime.now", "uuid4", "uuid7", "random.random", "open"}

    assert not calls & forbidden
    assert "execute_activity" in source
    assert "wait_condition" in source


@req("FR-105", "FR-207", "NFR-001", "NFR-020")
async def test_workflow_definition_prepares_in_temporal_sandbox() -> None:
    definition = workflow._Definition.must_from_class(SessionBootstrapWorkflow)
    SandboxedWorkflowRunner().prepare_workflow(definition)
