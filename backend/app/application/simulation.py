"""Simulation orchestration service — Phase 8.

Coordinates: spec validation → sandbox execution → result storage.
trace: T8-03, T8-04
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from app.domain.simulation import (
    RunStatus,
    SimulationRunRecord,
    SimulationRunStore,
)
from app.ports.simulation import (
    SensitivityEntry,
    SimulationEngine,
    SimulationFailureCode,
    SimulationResult,
    SimulationResultVariable,
    SimulationSpec,
    ValidationReport,
    spec_content_hash,
)

__all__ = [
    "SimulationError",
    "SimulationOrchestrator",
    "compute_sensitivity_ranks",
]


class SimulationError(Exception):
    def __init__(self, code: SimulationFailureCode, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def compute_sensitivity_ranks(
    entries: tuple[SensitivityEntry, ...],
) -> tuple[SensitivityEntry, ...]:
    """T8-04: Re-rank by descending absolute index."""
    if not entries:
        return ()
    sorted_entries = sorted(entries, key=lambda e: abs(e.index), reverse=True)
    return tuple(
        SensitivityEntry(
            parameter=e.parameter,
            method=e.method,
            index=e.index,
            rank=rank,
        )
        for rank, e in enumerate(sorted_entries, start=1)
    )


class SimulationOrchestrator:
    """Coordinates spec → validate → run → store result."""

    def __init__(
        self,
        engine: SimulationEngine,
        store: SimulationRunStore,
    ) -> None:
        self._engine = engine
        self._store = store

    def validate_spec(self, spec: SimulationSpec) -> ValidationReport:
        return self._engine.validate(spec)

    async def request_simulation(
        self,
        *,
        spec: SimulationSpec,
        workspace_id: UUID,
        session_id: UUID,
        requested_by: UUID,
        round: int,
        spec_ref: str,
        run_id: UUID,
    ) -> SimulationRunRecord:
        computed_hash = spec_content_hash(spec)
        record = SimulationRunRecord(
            id=run_id,
            workspace_id=workspace_id,
            session_id=session_id,
            requested_by=requested_by,
            round=round,
            engine=self._engine.name,
            engine_version=self._engine.version,
            spec_ref=spec_ref,
            spec_hash=computed_hash,
            sandboxed=True,
            seed=spec.seed,
            n_runs=spec.budget.max_runs,
            horizon=f"{spec.horizon.steps}{spec.horizon.unit}",
            params=json.loads(spec.model_dump_json(include={"parameters"})),
            status=RunStatus.PENDING,
            created_at=datetime.now(UTC),
        )
        await self._store.add_run(record)
        return record

    async def execute_simulation(
        self,
        *,
        workspace_id: UUID,
        run_id: UUID,
        spec: SimulationSpec,
    ) -> SimulationResult:
        """Execute a simulation: validate → run → rank → store."""
        validation = self.validate_spec(spec)
        if not validation.valid:
            codes = [c.failure_code for c in validation.checks if not c.passed and c.failure_code]
            code = codes[0] if codes else SimulationFailureCode.SPEC_BUDGET
            detail = "; ".join(c.detail for c in validation.checks if not c.passed and c.detail)
            await self._store.update_status(
                workspace_id,
                run_id,
                status=RunStatus.REJECTED,
                error=f"{code}: {detail}",
            )
            raise SimulationError(code, detail)

        started_at = datetime.now(UTC)
        await self._store.update_status(
            workspace_id,
            run_id,
            status=RunStatus.RUNNING,
            started_at=started_at,
        )

        try:
            result = await self._engine.run(spec, seed=spec.seed, budget=spec.budget)
        except TimeoutError as exc:
            await self._store.update_status(
                workspace_id,
                run_id,
                status=RunStatus.TIMEOUT,
                error="SIM_TIMEOUT: wall-clock exceeded",
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
            raise SimulationError(
                SimulationFailureCode.SIM_TIMEOUT,
                "engine exceeded wall-clock budget",
            ) from exc
        except Exception as exc:
            await self._store.update_status(
                workspace_id,
                run_id,
                status=RunStatus.FAILED,
                error=f"SIM_UNAVAILABLE: {exc}",
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
            raise SimulationError(
                SimulationFailureCode.SIM_UNAVAILABLE,
                str(exc),
            ) from exc

        # T8-04: re-rank sensitivity per variable
        ranked: list[SimulationResultVariable] = []
        for var in result.variables:
            rv = SimulationResultVariable(
                variable=var.variable,
                unit=var.unit,
                mean=var.mean,
                sd=var.sd,
                ci_low=var.ci_low,
                ci_high=var.ci_high,
                quantiles=var.quantiles,
                distribution_ref=var.distribution_ref,
                sensitivity=compute_sensitivity_ranks(var.sensitivity),
                validity_domain=var.validity_domain,
            )
            ranked.append(rv)
            await self._store.add_result_variable(workspace_id, run_id, rv)

        await self._store.update_status(
            workspace_id,
            run_id,
            status=RunStatus.COMPLETED,
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )

        return SimulationResult(
            run_id=result.run_id,
            spec_id=result.spec_id,
            spec_hash=result.spec_hash,
            engine=result.engine,
            engine_version=result.engine_version,
            seed=result.seed,
            run_count=result.run_count,
            convergence=result.convergence,
            variables=tuple(ranked),
            scenario_deltas=result.scenario_deltas,
            resource_usage=result.resource_usage,
            warnings=result.warnings,
            assumptions=result.assumptions,
            validity_domain=result.validity_domain,
            artifact_ref=result.artifact_ref,
        )
