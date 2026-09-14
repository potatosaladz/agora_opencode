"""Live Temporal acceptance for workflow start, duplicate start, describe, and health."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from temporalio import workflow
from temporalio.client import Client

from app.adapters.temporal.session_bootstrap import (
    SessionBootstrapActivities,
    SessionBootstrapWorkflow,
)
from app.adapters.temporal.workflow import TemporalWorkflowEngine
from app.adapters.temporal.workflow_worker import TemporalWorkflowWorker
from app.common.ids import uuid7
from app.domain.session_bootstrap import SessionBootstrapInput, SessionBootstrapTransition
from app.domain.session_lifecycle import SessionLifecycle, SessionLifecycleState
from app.ports.errors import TransientPortError
from app.ports.workflow import WorkflowExecutionStatus, WorkflowInput
from tests.contracts.workflow_engine_contract import assert_workflow_engine_contract
from tests.traceability import req

_TEMPORAL_ADDRESS = os.getenv("TEST_TEMPORAL_ADDRESS")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _TEMPORAL_ADDRESS, reason="TEST_TEMPORAL_ADDRESS is not configured"),
]


@req("FR-105", "FR-207")
async def test_temporal_adapter_satisfies_workflow_engine_contract() -> None:
    assert _TEMPORAL_ADDRESS is not None
    engine = await TemporalWorkflowEngine.connect(
        _TEMPORAL_ADDRESS,
        namespace=os.getenv("TEST_TEMPORAL_NAMESPACE", "default"),
    )

    await assert_workflow_engine_contract(
        engine,
        workflow_id=f"contract-{uuid7()}",
    )


@workflow.defn
class ContractWorkerWorkflow:
    """Test-only workflow; production session behavior begins in T4-02."""

    @workflow.run
    async def run(
        self, workflow_input: dict[str, int | dict[str, str]]
    ) -> dict[str, int | dict[str, str]]:
        return workflow_input


@req("FR-105")
async def test_temporal_worker_polls_and_completes_test_workflow() -> None:
    assert _TEMPORAL_ADDRESS is not None
    namespace = os.getenv("TEST_TEMPORAL_NAMESPACE", "default")
    task_queue = f"contract-worker-{uuid7()}"
    workflow_id = f"contract-worker-{uuid7()}"
    worker = await TemporalWorkflowWorker.connect(
        _TEMPORAL_ADDRESS,
        namespace=namespace,
        task_queue=task_queue,
        workflows=(ContractWorkerWorkflow,),
    )
    engine = await TemporalWorkflowEngine.connect(_TEMPORAL_ADDRESS, namespace=namespace)
    running = asyncio.create_task(worker.run())
    try:
        await engine.start(
            workflow_id,
            "ContractWorkerWorkflow",
            WorkflowInput(payload={"session_id": workflow_id}),
            task_queue=task_queue,
            timeout_s=5.0,
        )
        for _ in range(50):
            execution = await engine.describe(workflow_id, timeout_s=5.0)
            if execution.status is WorkflowExecutionStatus.COMPLETED:
                break
            await asyncio.sleep(0.1)
        assert execution.status is WorkflowExecutionStatus.COMPLETED
    finally:
        await worker.shutdown()
        await asyncio.wait_for(running, timeout=5.0)
        await engine.close()


class _RecordingBootstrapCommitter:
    def __init__(self) -> None:
        self.commands: list[SessionBootstrapTransition] = []
        self.committed = asyncio.Event()

    async def commit(self, command: SessionBootstrapTransition) -> SessionLifecycle:
        self.commands.append(command)
        if command.target is SessionLifecycleState.RUNNING:
            self.committed.set()
        now = datetime.now(UTC)
        return SessionLifecycle(
            workspace_id=command.workspace_id,
            session_id=command.session_id,
            state=command.target,
            round=command.round,
            last_event_id=command.event_id,
            initialized_at=now,
            started_at=now,
            created_at=now,
            updated_at=now,
        )


@req("FR-105", "FR-207", "NFR-001")
async def test_production_bootstrap_runs_activity_with_stable_id_and_waits_durably() -> None:
    assert _TEMPORAL_ADDRESS is not None
    namespace = os.getenv("TEST_TEMPORAL_NAMESPACE", "default")
    task_queue = f"bootstrap-worker-{uuid7()}"
    workflow_id = f"bootstrap-{uuid7()}"
    bootstrap = SessionBootstrapInput(
        workspace_id=uuid7(),
        session_id=uuid7(),
        initialized_event_id=uuid7(),
        round_started_event_id=uuid7(),
        failed_event_id=uuid7(),
        correlation_id=uuid7(),
    )
    committer = _RecordingBootstrapCommitter()
    activities = SessionBootstrapActivities(committer)
    worker = await TemporalWorkflowWorker.connect(
        _TEMPORAL_ADDRESS,
        namespace=namespace,
        task_queue=task_queue,
        workflows=(SessionBootstrapWorkflow,),
        activities=(activities.commit_transition,),
    )
    engine = await TemporalWorkflowEngine.connect(_TEMPORAL_ADDRESS, namespace=namespace)
    client = await Client.connect(_TEMPORAL_ADDRESS, namespace=namespace)
    running = asyncio.create_task(worker.run())
    try:
        await engine.start(
            workflow_id,
            "SessionBootstrapWorkflow",
            WorkflowInput(payload=bootstrap.model_dump(mode="json")),
            task_queue=task_queue,
            timeout_s=5.0,
        )
        await asyncio.wait_for(committer.committed.wait(), timeout=10.0)
        execution = await engine.describe(workflow_id, timeout_s=5.0)

        assert execution.status is WorkflowExecutionStatus.RUNNING
        assert [command.event_id for command in committer.commands] == [
            bootstrap.initialized_event_id,
            bootstrap.round_started_event_id,
        ]
        assert [command.event_type for command in committer.commands] == [
            "SESSION_INITIALIZED",
            "ROUND_STARTED",
        ]
    finally:
        await client.get_workflow_handle(workflow_id).terminate("integration test completed")
        await worker.shutdown()
        await asyncio.wait_for(running, timeout=5.0)
        await engine.close()


class _PostCommitAckLossCommitter:
    """Model PostgreSQL exact replay after worker loss following commit."""

    def __init__(self) -> None:
        self.attempted_ids: list[object] = []
        self.committed_ids: set[object] = set()
        self.first_attempt = asyncio.Event()
        self.round_started = asyncio.Event()
        self._lose_first_ack = True

    async def commit(self, command: SessionBootstrapTransition) -> SessionLifecycle:
        self.attempted_ids.append(command.event_id)
        self.committed_ids.add(command.event_id)
        now = datetime.now(UTC)
        projection = SessionLifecycle(
            workspace_id=command.workspace_id,
            session_id=command.session_id,
            state=command.target,
            round=command.round,
            last_event_id=command.event_id,
            initialized_at=now,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        if self._lose_first_ack:
            self._lose_first_ack = False
            self.first_attempt.set()
            raise TransientPortError("simulated acknowledgement loss", port="postgres")
        if command.target is SessionLifecycleState.RUNNING:
            self.round_started.set()
        return projection


@req("FR-105", "NFR-001")
async def test_worker_restart_retries_same_identity_without_duplicate_committed_effect() -> None:
    assert _TEMPORAL_ADDRESS is not None
    namespace = os.getenv("TEST_TEMPORAL_NAMESPACE", "default")
    task_queue = f"recovery-worker-{uuid7()}"
    workflow_id = f"recovery-{uuid7()}"
    bootstrap = SessionBootstrapInput(
        workspace_id=uuid7(),
        session_id=uuid7(),
        initialized_event_id=uuid7(),
        round_started_event_id=uuid7(),
        failed_event_id=uuid7(),
        correlation_id=uuid7(),
    )
    committer = _PostCommitAckLossCommitter()
    activities = SessionBootstrapActivities(committer)
    first_worker = await TemporalWorkflowWorker.connect(
        _TEMPORAL_ADDRESS,
        namespace=namespace,
        task_queue=task_queue,
        workflows=(SessionBootstrapWorkflow,),
        activities=(activities.commit_transition,),
    )
    engine = await TemporalWorkflowEngine.connect(_TEMPORAL_ADDRESS, namespace=namespace)
    client = await Client.connect(_TEMPORAL_ADDRESS, namespace=namespace)
    first_running = asyncio.create_task(first_worker.run())
    second_worker: TemporalWorkflowWorker | None = None
    second_running: asyncio.Task[None] | None = None
    try:
        await engine.start(
            workflow_id,
            "SessionBootstrapWorkflow",
            WorkflowInput(payload=bootstrap.model_dump(mode="json")),
            task_queue=task_queue,
            timeout_s=5.0,
        )
        await asyncio.wait_for(committer.first_attempt.wait(), timeout=10.0)
        await first_worker.shutdown()
        await asyncio.wait_for(first_running, timeout=5.0)

        second_worker = await TemporalWorkflowWorker.connect(
            _TEMPORAL_ADDRESS,
            namespace=namespace,
            task_queue=task_queue,
            workflows=(SessionBootstrapWorkflow,),
            activities=(activities.commit_transition,),
        )
        second_running = asyncio.create_task(second_worker.run())
        await asyncio.wait_for(committer.round_started.wait(), timeout=15.0)

        assert committer.attempted_ids.count(bootstrap.initialized_event_id) == 2
        assert committer.attempted_ids.count(bootstrap.round_started_event_id) == 1
        assert committer.committed_ids == {
            bootstrap.initialized_event_id,
            bootstrap.round_started_event_id,
        }
    finally:
        await client.get_workflow_handle(workflow_id).terminate("recovery integration completed")
        if not first_running.done():
            await first_worker.shutdown()
            await asyncio.wait_for(first_running, timeout=5.0)
        if second_worker is not None and second_running is not None:
            await second_worker.shutdown()
            await asyncio.wait_for(second_running, timeout=5.0)
        await engine.close()
