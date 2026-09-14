"""Reusable behavioral assertions for every ``WorkflowEngine`` adapter."""

from __future__ import annotations

from datetime import datetime

from app.ports.health import HealthStatus
from app.ports.workflow import (
    WorkflowEngine,
    WorkflowExecutionStatus,
    WorkflowInput,
)


async def assert_workflow_engine_contract(
    engine: WorkflowEngine,
    *,
    workflow_id: str,
    expected_started_at: datetime | None = None,
) -> None:
    """Prove idempotent start and diagnostic description semantics."""
    assert isinstance(engine, WorkflowEngine)
    assert await engine.health() is HealthStatus.OK
    workflow_input = WorkflowInput(
        payload={"session_id": workflow_id, "agent_ids": ["agent-1"]},
        schema_version=1,
    )

    first = await engine.start(
        workflow_id,
        "ContractWorkflow",
        workflow_input,
        task_queue="contract-workflows",
        timeout_s=5.0,
    )
    replay = await engine.start(
        workflow_id,
        "ContractWorkflow",
        workflow_input,
        task_queue="contract-workflows",
        timeout_s=5.0,
    )
    execution = await engine.describe(workflow_id, timeout_s=5.0)

    assert first.workflow_id == workflow_id
    assert first.started is True
    assert first.run_id
    assert replay == first.model_copy(update={"started": False})
    assert execution.workflow_id == workflow_id
    assert execution.run_id == first.run_id
    assert execution.workflow_type == "ContractWorkflow"
    assert execution.task_queue == "contract-workflows"
    assert execution.status is WorkflowExecutionStatus.RUNNING
    if expected_started_at is not None:
        assert execution.started_at == expected_started_at

    await engine.close()
    assert await engine.health() is HealthStatus.DOWN
