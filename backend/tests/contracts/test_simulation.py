"""Phase 8 acceptance tests — simulation contracts.

T8-00: freeze the contract. trace: FR-701, FR-702, FR-703, FR-704
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.simulation import RunStatus, SimulationRunRecord
from app.ports.simulation import (
    ConvergenceStatus,
    DistributionSpec,
    EngineKind,
    ParameterSpec,
    ResourceUsage,
    RunBudget,
    ScenarioOverride,
    SensitivityEntry,
    SimulationCapabilities,
    SimulationFailureCode,
    SimulationHorizon,
    SimulationResult,
    SimulationResultVariable,
    SimulationSpec,
    ValidationCheck,
    ValidationReport,
    spec_content_hash,
)
from tests.traceability import req

SPEC_ID = UUID("018f4000-0000-7000-8000-000000000001")
RUN_ID = UUID("018f4000-0000-7000-8000-000000000002")
WORKSPACE_ID = UUID("018f4000-0000-7000-8000-000000000003")
SESSION_ID = UUID("018f4000-0000-7000-8000-000000000004")
AGENT_ID = UUID("018f4000-0000-7000-8000-000000000005")
HASH = "sha256:" + "a" * 64


def _param(
    name: str = "rate",
    value: Decimal | None = Decimal("0.1"),
    dist: DistributionSpec | None = None,
) -> ParameterSpec:
    return ParameterSpec(name=name, value=value, distribution=dist, source="art_01")


def _dist() -> DistributionSpec:
    return DistributionSpec(
        type="triangular",
        min=Decimal("0.05"),
        mode=Decimal("0.12"),
        max=Decimal("0.30"),
    )


def _budget() -> RunBudget:
    return RunBudget(max_runs=1000, max_seconds=60, max_cost_usd=Decimal("1.0"))


def _horizon() -> SimulationHorizon:
    return SimulationHorizon(steps=60, dt=Decimal("1"), unit="month")


def _spec(**kw: object) -> SimulationSpec:
    d: dict[str, object] = {
        "spec_id": SPEC_ID,
        "kind": EngineKind.SYSTEM_DYNAMICS,
        "model": {"stocks": ["uptake"], "flows": ["adoption"]},
        "parameters": (_param(),),
        "scenarios": (ScenarioOverride(name="baseline"),),
        "horizon": _horizon(),
        "outputs": ("uptake",),
        "assumptions": ("asm_01",),
        "validity_domain": "national level, 2025-2030",
        "budget": _budget(),
        "seed": 42,
        "engine_version": "sd-engine@1.0.0",
    }
    d.update(kw)
    return SimulationSpec(**d)  # type: ignore[arg-type]


def _result_var(variable: str = "uptake", **kw: object) -> SimulationResultVariable:
    d: dict[str, object] = {
        "variable": variable,
        "unit": "count",
        "mean": Decimal("100.5"),
        "sd": Decimal("12.3"),
        "ci_low": Decimal("80.0"),
        "ci_high": Decimal("121.0"),
        "validity_domain": {"scope": "national"},
    }
    d.update(kw)
    return SimulationResultVariable(**d)  # type: ignore[arg-type]


def _result(**kw: object) -> SimulationResult:
    d: dict[str, object] = {
        "run_id": RUN_ID,
        "spec_id": SPEC_ID,
        "spec_hash": HASH,
        "engine": "system_dynamics",
        "engine_version": "sd-engine@1.0.0",
        "seed": 42,
        "run_count": 1000,
        "convergence": ConvergenceStatus.CONVERGED,
        "variables": (_result_var(),),
        "resource_usage": ResourceUsage(
            wall_time_s=Decimal("5.2"),
            cpu_seconds=Decimal("4.8"),
            peak_memory_mb=Decimal("128"),
            cost_estimate_usd=Decimal("0.01"),
        ),
        "assumptions": ("asm_01",),
        "validity_domain": "national level, 2025-2030",
    }
    d.update(kw)
    return SimulationResult(**d)  # type: ignore[arg-type]


class TestSimulationSpec:
    @req("FR-701")
    def test_valid_spec(self) -> None:
        assert _spec().kind == EngineKind.SYSTEM_DYNAMICS

    @req("FR-702")
    def test_spec_hash_deterministic(self) -> None:
        assert spec_content_hash(_spec()) == spec_content_hash(_spec())

    @req("FR-702")
    def test_spec_hash_changes_with_seed(self) -> None:
        assert spec_content_hash(_spec(seed=42)) != spec_content_hash(_spec(seed=99))

    @req("FR-702")
    def test_spec_hash_changes_with_engine_version(self) -> None:
        h1 = spec_content_hash(_spec(engine_version="sd-engine@1.0.0"))
        h2 = spec_content_hash(_spec(engine_version="sd-engine@2.0.0"))
        assert h1 != h2

    @req("FR-702")
    def test_parameter_requires_value_or_distribution(self) -> None:
        with pytest.raises(ValueError, match="value or a distribution"):
            ParameterSpec(name="rate", source="art_01")

    @req("FR-702")
    def test_parameter_with_distribution(self) -> None:
        assert _param(value=None, dist=_dist()).distribution is not None

    @req("FR-702")
    def test_distribution_requires_shape(self) -> None:
        with pytest.raises(ValueError, match="shape parameter"):
            DistributionSpec(type="triangular")

    @req("FR-702")
    def test_duplicate_output_names_rejected(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            _spec(outputs=("x", "x"))

    @req("FR-702")
    def test_duplicate_param_names_rejected(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            _spec(parameters=(_param(name="a"), _param(name="a")))

    @req("FR-702")
    def test_duplicate_scenario_names_rejected(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            _spec(scenarios=(ScenarioOverride(name="s"), ScenarioOverride(name="s")))

    @req("FR-702")
    def test_bad_schema_version(self) -> None:
        with pytest.raises(ValueError, match="schema_version"):
            _spec(schema_version=99)

    @req("FR-703")
    def test_empty_assumptions_rejected(self) -> None:
        with pytest.raises(ValueError, match="assumptions"):
            _spec(assumptions=())

    @req("FR-702")
    def test_empty_validity_domain_rejected(self) -> None:
        with pytest.raises(ValueError, match="validity_domain"):
            _spec(validity_domain="")

    @req("FR-702")
    def test_frozen(self) -> None:
        with pytest.raises(ValidationError, match="frozen"):
            _spec().seed = 99  # type: ignore[misc]


class TestSimulationResult:
    @req("FR-702", "FR-703")
    def test_valid_result(self) -> None:
        assert _result().evidence_kind == "SIMULATION_RESULT"

    @req("FR-702")
    def test_result_carries_all_fr702_fields(self) -> None:
        r = _result()
        assert r.engine
        assert r.engine_version
        assert r.spec_hash.startswith("sha256:")
        assert r.seed == 42
        assert r.run_count == 1000
        assert r.validity_domain

    @req("FR-702")
    def test_ci_low_gt_ci_high_rejected(self) -> None:
        with pytest.raises(ValueError, match="ci_low"):
            _result_var(ci_low=Decimal("200"), ci_high=Decimal("100"))

    @req("FR-703")
    def test_evidence_kind_must_be_simulation_result(self) -> None:
        with pytest.raises(ValueError, match="SIMULATION_RESULT"):
            _result(evidence_kind="WORLD_FACT")

    @req("FR-702")
    def test_duplicate_variable_names_rejected(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            _result(variables=(_result_var("x"), _result_var("x")))

    @req("FR-702")
    def test_frozen(self) -> None:
        with pytest.raises(ValidationError, match="frozen"):
            _result().seed = 99  # type: ignore[misc]


class TestValidationReport:
    @req("FR-701")
    def test_valid_report(self) -> None:
        rpt = ValidationReport(
            spec_id=SPEC_ID,
            checks=(ValidationCheck(check="units", passed=True),),
            valid=True,
        )
        assert rpt.valid

    @req("FR-701")
    def test_valid_flag_mismatch(self) -> None:
        with pytest.raises(ValueError, match="valid flag"):
            ValidationReport(
                spec_id=SPEC_ID,
                checks=(
                    ValidationCheck(
                        check="u",
                        passed=False,
                        failure_code=SimulationFailureCode.SPEC_UNIT_MISSING,
                    ),
                ),
                valid=True,
            )


class TestSimulationRunRecord:
    def _record(self, **kw: object) -> SimulationRunRecord:
        d: dict[str, object] = {
            "id": RUN_ID,
            "workspace_id": WORKSPACE_ID,
            "session_id": SESSION_ID,
            "requested_by": AGENT_ID,
            "round": 1,
            "engine": "system_dynamics",
            "engine_version": "sd-engine@1.0.0",
            "spec_ref": "sim-specs/abc",
            "spec_hash": HASH,
            "sandboxed": True,
            "seed": 42,
            "n_runs": 1000,
            "horizon": "60month",
            "params": {"rate": "0.1"},
            "status": RunStatus.PENDING,
            "created_at": datetime.now(UTC),
        }
        d.update(kw)
        return SimulationRunRecord(**d)  # type: ignore[arg-type]

    @req("FR-701")
    def test_pending_record(self) -> None:
        assert self._record().status == RunStatus.PENDING

    @req("FR-701")
    def test_completed_requires_finished_at(self) -> None:
        with pytest.raises(ValueError, match="finished_at"):
            self._record(status=RunStatus.COMPLETED, started_at=datetime.now(UTC))

    @req("FR-701")
    def test_failed_requires_error(self) -> None:
        with pytest.raises(ValueError, match="error"):
            self._record(
                status=RunStatus.FAILED,
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )

    @req("FR-701")
    def test_running_requires_started_at(self) -> None:
        with pytest.raises(ValueError, match="started_at"):
            self._record(status=RunStatus.RUNNING)

    @req("FR-701")
    def test_rejected_requires_error(self) -> None:
        with pytest.raises(ValueError, match="error"):
            self._record(status=RunStatus.REJECTED)


class TestPorts:
    @req("FR-701")
    def test_simulation_engine_protocol(self) -> None:
        from app.ports.simulation import SimulationEngine

        assert hasattr(SimulationEngine, "run")
        assert hasattr(SimulationEngine, "validate")

    @req("FR-704")
    def test_sandbox_execution_provider_protocol(self) -> None:
        from app.ports.simulation import SandboxExecutionProvider

        assert hasattr(SandboxExecutionProvider, "execute")

    @req("FR-704")
    def test_sandbox_request_model(self) -> None:
        from app.ports.simulation import NetworkPolicy, SandboxRequest

        req = SandboxRequest(image_digest=HASH, entrypoint="/run.py")
        assert req.network_policy == NetworkPolicy.NONE
        assert req.readonly_root is True

    @req("FR-704")
    def test_sandbox_result_terminated_nonzero(self) -> None:
        from app.ports.simulation import SandboxResourceUsage, SandboxResult

        with pytest.raises(ValueError, match="terminated_by"):
            SandboxResult(
                exit_code=0,
                resource_usage=SandboxResourceUsage(
                    wall_time_s=Decimal("1"),
                    cpu_seconds=Decimal("1"),
                    peak_memory_mb=Decimal("10"),
                ),
                terminated_by="timeout",
            )


class TestSensitivity:
    @req("FR-702")
    def test_compute_sensitivity_ranks(self) -> None:
        from app.application.simulation import compute_sensitivity_ranks

        entries = (
            SensitivityEntry(parameter="a", method="sobol", index=Decimal("0.2"), rank=99),
            SensitivityEntry(parameter="b", method="sobol", index=Decimal("0.8"), rank=99),
            SensitivityEntry(parameter="c", method="sobol", index=Decimal("0.5"), rank=99),
        )
        ranked = compute_sensitivity_ranks(entries)
        assert ranked[0].parameter == "b"
        assert ranked[0].rank == 1
        assert ranked[1].parameter == "c"
        assert ranked[1].rank == 2
        assert ranked[2].parameter == "a"
        assert ranked[2].rank == 3

    @req("FR-702")
    def test_empty_sensitivity(self) -> None:
        from app.application.simulation import compute_sensitivity_ranks

        assert compute_sensitivity_ranks(()) == ()

    @req("FR-702")
    def test_negative_indices_ranked_by_absolute(self) -> None:
        from app.application.simulation import compute_sensitivity_ranks

        entries = (
            SensitivityEntry(parameter="x", method="oat", index=Decimal("-0.9"), rank=99),
            SensitivityEntry(parameter="y", method="oat", index=Decimal("0.3"), rank=99),
        )
        ranked = compute_sensitivity_ranks(entries)
        assert ranked[0].parameter == "x"
        assert ranked[0].rank == 1


# -- In-memory test doubles --


class InMemorySimulationRunStore:
    def __init__(self) -> None:
        self._runs: dict[UUID, dict[str, object]] = {}
        self._vars: dict[UUID, list[SimulationResultVariable]] = {}

    async def add_run(self, run: SimulationRunRecord) -> None:
        self._runs[run.id] = run.model_dump()

    async def get_run(self, workspace_id: UUID, run_id: UUID) -> SimulationRunRecord | None:
        d = self._runs.get(run_id)
        return SimulationRunRecord(**d) if d else None  # type: ignore[arg-type]

    async def update_status(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        status: RunStatus,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        d = self._runs[run_id]
        d["status"] = status
        if error is not None:
            d["error"] = error
        if started_at is not None:
            d["started_at"] = started_at
        if finished_at is not None:
            d["finished_at"] = finished_at

    async def add_result_variable(
        self, workspace_id: UUID, run_id: UUID, variable: SimulationResultVariable
    ) -> None:
        self._vars.setdefault(run_id, []).append(variable)

    async def get_result_variables(
        self, workspace_id: UUID, run_id: UUID
    ) -> tuple[SimulationResultVariable, ...]:
        return tuple(self._vars.get(run_id, []))

    async def list_runs(
        self, workspace_id: UUID, session_id: UUID, *, status: RunStatus | None = None
    ) -> tuple[SimulationRunRecord, ...]:
        return tuple(
            SimulationRunRecord(**d)  # type: ignore[arg-type]
            for d in self._runs.values()
            if d["workspace_id"] == workspace_id
            and d["session_id"] == session_id
            and (status is None or d["status"] == status)
        )


class StubSimulationEngine:
    name: str = "stub"
    version: str = "stub@1.0.0"

    def capabilities(self) -> SimulationCapabilities:
        return SimulationCapabilities(
            supports_distributions=True,
            supports_scenarios=True,
            supports_sensitivity=True,
            deterministic=True,
        )

    def validate(self, spec: SimulationSpec) -> ValidationReport:
        return ValidationReport(
            spec_id=spec.spec_id,
            checks=(ValidationCheck(check="stub", passed=True),),
            valid=True,
        )

    async def run(self, spec: SimulationSpec, *, seed: int, budget: RunBudget) -> SimulationResult:
        return SimulationResult(
            run_id=RUN_ID,
            spec_id=spec.spec_id,
            spec_hash=spec_content_hash(spec),
            engine=self.name,
            engine_version=self.version,
            seed=seed,
            run_count=budget.max_runs,
            convergence=ConvergenceStatus.CONVERGED,
            variables=(_result_var(),),
            resource_usage=ResourceUsage(
                wall_time_s=Decimal("1"),
                cpu_seconds=Decimal("1"),
                peak_memory_mb=Decimal("64"),
                cost_estimate_usd=Decimal("0.01"),
            ),
            assumptions=("asm_01",),
            validity_domain="test domain",
        )


class TestOrchestration:
    @req("FR-701")
    @pytest.mark.asyncio
    async def test_request_creates_pending(self) -> None:
        from app.application.simulation import SimulationOrchestrator

        orch = SimulationOrchestrator(
            engine=StubSimulationEngine(),
            store=InMemorySimulationRunStore(),
        )
        record = await orch.request_simulation(
            spec=_spec(),
            workspace_id=WORKSPACE_ID,
            session_id=SESSION_ID,
            requested_by=AGENT_ID,
            round=1,
            spec_ref="sim-specs/t",
            run_id=RUN_ID,
        )
        assert record.status == RunStatus.PENDING
        assert record.spec_hash.startswith("sha256:")

    @req("FR-701", "FR-702")
    @pytest.mark.asyncio
    async def test_execute_happy_path(self) -> None:
        from app.application.simulation import SimulationOrchestrator

        store = InMemorySimulationRunStore()
        orch = SimulationOrchestrator(
            engine=StubSimulationEngine(),
            store=store,
        )
        await orch.request_simulation(
            spec=_spec(),
            workspace_id=WORKSPACE_ID,
            session_id=SESSION_ID,
            requested_by=AGENT_ID,
            round=1,
            spec_ref="sim-specs/t",
            run_id=RUN_ID,
        )
        result = await orch.execute_simulation(
            workspace_id=WORKSPACE_ID,
            run_id=RUN_ID,
            spec=_spec(),
        )
        assert result.convergence == ConvergenceStatus.CONVERGED
        run = await store.get_run(WORKSPACE_ID, RUN_ID)
        assert run is not None
        assert run.status == RunStatus.COMPLETED
