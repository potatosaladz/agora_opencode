"""Offline behavioral contract for the workflow-engine reference adapter."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.adapters.inmemory.workflow import InMemoryWorkflowEngine
from app.common.clock import FrozenClock
from app.ports.errors import PermanentPortError, TransientPortError
from app.ports.workflow import WorkflowInput
from tests.contracts.workflow_engine_contract import assert_workflow_engine_contract
from tests.traceability import req

pytestmark = pytest.mark.contract


@req("FR-105", "FR-207")
async def test_inmemory_adapter_satisfies_workflow_engine_contract() -> None:
    moment = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    engine = InMemoryWorkflowEngine(clock=FrozenClock(moment))

    await assert_workflow_engine_contract(
        engine,
        workflow_id="session-contract",
        expected_started_at=moment,
    )


@req("FR-105", "FR-207")
async def test_commands_are_validated_and_closed_adapter_fails_loudly() -> None:
    engine = InMemoryWorkflowEngine()

    with pytest.raises(PermanentPortError, match="workflow_id"):
        await engine.start(
            " ",
            "ContractWorkflow",
            WorkflowInput(),
            task_queue="contract-workflows",
            timeout_s=5.0,
        )
    with pytest.raises(PermanentPortError, match="does not exist"):
        await engine.describe("missing", timeout_s=5.0)

    await engine.close()
    with pytest.raises(TransientPortError, match="closed"):
        await engine.describe("session-contract", timeout_s=5.0)


@req("FR-105", "FR-207")
def test_workflow_input_is_strict_versioned_json() -> None:
    with pytest.raises(ValidationError):
        WorkflowInput.model_validate({"payload": {"temperature": 0.5}, "schema_version": 1})
    with pytest.raises(ValidationError):
        WorkflowInput.model_validate({"payload": {}, "schema_version": 0})
    with pytest.raises(ValidationError):
        WorkflowInput.model_validate({"payload": {}, "schema_version": 1, "unknown": True})
