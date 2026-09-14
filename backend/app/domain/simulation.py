"""Simulation domain models — Phase 8 persistence contracts.

Re-exports port-level types and adds persistence-layer models:
  - SimulationRunRecord (maps to simulation_runs table)
  - SimulationRunStore (persistence protocol)

Domain may import from ports per test_layering.py rules.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import Field, model_validator

from app.ports.simulation import (
    ConvergenceStatus,
    DistributionSpec,
    EngineKind,
    ParameterSpec,
    ResourceUsage,
    RunBudget,
    ScenarioOverride,
    SensitivityEntry,
    SimulationFailureCode,
    SimulationHorizon,
    SimulationResult,
    SimulationResultVariable,
    SimulationSpec,
    ValidationCheck,
    ValidationReport,
    _Frozen,
    spec_content_hash,
)

__all__ = [
    # Re-exports from ports
    "ConvergenceStatus",
    "DistributionSpec",
    "EngineKind",
    "ParameterSpec",
    "ResourceUsage",
    "RunBudget",
    "RunStatus",
    "ScenarioOverride",
    "SensitivityEntry",
    "SimulationFailureCode",
    "SimulationHorizon",
    "SimulationResult",
    "SimulationResultVariable",
    "SimulationRunRecord",
    "SimulationRunStore",
    "SimulationSpec",
    "ValidationCheck",
    "ValidationReport",
    "spec_content_hash",
]


# ---------------------------------------------------------------------------
# RunStatus enum (domain-only, not needed by the port)
# ---------------------------------------------------------------------------


class RunStatus(StrEnum):
    """Lifecycle states for a simulation run row."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# SimulationRunRecord — durable row per DATA_MODEL.md §10
# ---------------------------------------------------------------------------


class SimulationRunRecord(_Frozen):
    """Durable record for a simulation run."""

    id: UUID
    workspace_id: UUID
    session_id: UUID
    requested_by: UUID
    round: int = Field(ge=1)
    engine: str = Field(min_length=1)
    engine_version: str = Field(min_length=1)
    spec_ref: str = Field(min_length=1)
    spec_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    sandboxed: bool
    seed: int
    n_runs: int = Field(gt=0)
    horizon: str = Field(min_length=1)
    params: dict[str, Any]
    status: RunStatus = RunStatus.PENDING
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime

    @model_validator(mode="after")
    def status_constraints(self) -> SimulationRunRecord:
        terminal = {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.TIMEOUT,
        }
        if self.status in terminal and self.finished_at is None:
            raise ValueError(f"terminal status {self.status} requires finished_at")
        error_req = {
            RunStatus.FAILED,
            RunStatus.TIMEOUT,
            RunStatus.REJECTED,
        }
        if self.status in error_req and not self.error:
            raise ValueError(f"failure status {self.status} requires error")
        needs_started = {
            RunStatus.RUNNING,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.TIMEOUT,
        }
        if self.status in needs_started and self.started_at is None:
            raise ValueError(f"status {self.status} requires started_at")
        return self


# ---------------------------------------------------------------------------
# SimulationRunStore — persistence port
# ---------------------------------------------------------------------------


@runtime_checkable
class SimulationRunStore(Protocol):
    """Caller-transaction-scoped persistence."""

    async def add_run(self, run: SimulationRunRecord) -> None: ...

    async def get_run(self, workspace_id: UUID, run_id: UUID) -> SimulationRunRecord | None: ...

    async def update_status(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        status: RunStatus,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None: ...

    async def add_result_variable(
        self,
        workspace_id: UUID,
        run_id: UUID,
        variable: SimulationResultVariable,
    ) -> None: ...

    async def get_result_variables(
        self, workspace_id: UUID, run_id: UUID
    ) -> tuple[SimulationResultVariable, ...]: ...

    async def list_runs(
        self,
        workspace_id: UUID,
        session_id: UUID,
        *,
        status: RunStatus | None = None,
    ) -> tuple[SimulationRunRecord, ...]: ...
