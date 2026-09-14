"""SDK-boundary tests for the Temporal workflow-engine adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from temporalio.client import Client
from temporalio.client import WorkflowExecutionStatus as TemporalExecutionStatus
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from app.adapters.temporal.workflow import TemporalWorkflowEngine
from app.ports.errors import PermanentPortError, TransientPortError
from app.ports.health import HealthStatus
from app.ports.workflow import WorkflowExecutionStatus, WorkflowInput, WorkflowSignal
from tests.traceability import req


class _FakeServiceClient:
    def __init__(self, *, serving: bool = True) -> None:
        self.serving = serving

    async def check_health(self, **_kwargs: object) -> bool:
        return self.serving


class _FakeHandle:
    def __init__(self, workflow_id: str, *, run_id: str = "run-1") -> None:
        self.result_run_id = run_id
        self._workflow_id = workflow_id

    async def describe(self, **_kwargs: object) -> object:
        return SimpleNamespace(
            id=self._workflow_id,
            run_id=self.result_run_id,
            workflow_type="SessionWorkflow",
            task_queue="session-workflows",
            status=TemporalExecutionStatus.RUNNING,
            start_time=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
            close_time=None,
        )

    async def signal(self, name: str, arg: object, **kwargs: Any) -> None:
        self.signal_call = (name, arg, kwargs)


class _FakeClient:
    def __init__(self) -> None:
        self.service_client = _FakeServiceClient()
        self.calls: list[tuple[str, object, dict[str, Any]]] = []
        self.duplicate = False
        self.handle = _FakeHandle("session-1")

    async def start_workflow(
        self, workflow_type: str, workflow_input: object, **kwargs: Any
    ) -> _FakeHandle:
        self.calls.append((workflow_type, workflow_input, kwargs))
        if self.duplicate:
            raise WorkflowAlreadyStartedError(str(kwargs["id"]), workflow_type, run_id="run-1")
        return _FakeHandle(str(kwargs["id"]))

    def get_workflow_handle(self, workflow_id: str) -> _FakeHandle:
        self.handle._workflow_id = workflow_id
        return self.handle


@req("FR-105", "FR-207", "NFR-020")
async def test_start_pins_duplicate_policies_and_normalizes_duplicate() -> None:
    client = _FakeClient()
    engine = TemporalWorkflowEngine(cast(Client, client))
    workflow_input = WorkflowInput(payload={"session_id": "session-1"})

    started = await engine.start(
        "session-1",
        "SessionWorkflow",
        workflow_input,
        task_queue="session-workflows",
        timeout_s=4.0,
    )
    client.duplicate = True
    replay = await engine.start(
        "session-1",
        "SessionWorkflow",
        workflow_input,
        task_queue="session-workflows",
        timeout_s=4.0,
    )

    assert started.started is True
    assert replay.started is False
    assert started.run_id == replay.run_id == "run-1"
    _, serialized_input, options = client.calls[0]
    assert serialized_input == {"payload": {"session_id": "session-1"}, "schema_version": 1}
    assert options["id_reuse_policy"] is WorkflowIDReusePolicy.REJECT_DUPLICATE
    assert options["id_conflict_policy"] is WorkflowIDConflictPolicy.FAIL


@req("FR-105", "FR-207", "NFR-020")
async def test_describe_maps_transport_state_without_session_semantics() -> None:
    engine = TemporalWorkflowEngine(cast(Client, _FakeClient()))

    execution = await engine.describe("session-1", timeout_s=2.0)

    assert execution.status is WorkflowExecutionStatus.RUNNING
    assert execution.workflow_type == "SessionWorkflow"


@req("FR-105", "FR-207", "NFR-020")
async def test_signal_sends_single_versioned_envelope_with_rpc_timeout() -> None:
    client = _FakeClient()
    engine = TemporalWorkflowEngine(cast(Client, client))

    await engine.signal(
        "session-1",
        WorkflowSignal(name="session_control", payload={"command": "PAUSE"}),
        timeout_s=3.0,
    )

    name, arg, options = client.handle.signal_call
    assert name == "session_control"
    assert arg == {"payload": {"command": "PAUSE"}, "schema_version": 1, "name": "session_control"}
    assert options["rpc_timeout"].total_seconds() == 3.0


@req("FR-105", "FR-207", "NFR-020")
async def test_health_reflects_service_and_adapter_lifecycle() -> None:
    client = _FakeClient()
    engine = TemporalWorkflowEngine(cast(Client, client))

    assert await engine.health() is HealthStatus.OK
    client.service_client.serving = False
    assert await engine.health() is HealthStatus.DEGRADED
    await engine.close()
    assert await engine.health() is HealthStatus.DOWN


@req("FR-105", "FR-207", "NFR-020")
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (RPCStatusCode.NOT_FOUND, PermanentPortError),
        (RPCStatusCode.UNAVAILABLE, TransientPortError),
    ],
)
async def test_raw_rpc_errors_never_escape(
    status: RPCStatusCode, expected: type[PermanentPortError | TransientPortError]
) -> None:
    class FailingHandle(_FakeHandle):
        async def describe(self, **_kwargs: object) -> object:
            raise RPCError("failed", status, b"")

    client = _FakeClient()
    client.get_workflow_handle = lambda workflow_id: FailingHandle(workflow_id)  # type: ignore[method-assign]
    engine = TemporalWorkflowEngine(cast(Client, client))

    with pytest.raises(expected):
        await engine.describe("session-1", timeout_s=2.0)


@req("FR-105", "FR-207", "NFR-020")
async def test_raw_runtime_errors_never_escape() -> None:
    class FailingHandle(_FakeHandle):
        async def describe(self, **_kwargs: object) -> object:
            raise RuntimeError("SDK runtime failed")

    client = _FakeClient()
    client.get_workflow_handle = lambda workflow_id: FailingHandle(workflow_id)  # type: ignore[method-assign]
    engine = TemporalWorkflowEngine(cast(Client, client))

    with pytest.raises(TransientPortError, match="RuntimeError"):
        await engine.describe("session-1", timeout_s=2.0)
