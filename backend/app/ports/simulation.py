"""`SimulationEngine` and `SandboxExecutionProvider` ports — PORTS.md §8, §11.

Nothing here may import an infrastructure SDK, and nothing here may
import `app.adapters` or `app.domain` — enforced by `tests/test_layering.py`.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ports.health import HealthStatus

__all__ = [
    "ConvergenceStatus",
    "DistributionSpec",
    "EngineKind",
    "NetworkPolicy",
    "ParameterSpec",
    "ResourceUsage",
    "RunBudget",
    "SandboxExecutionProvider",
    "SandboxRequest",
    "SandboxResourceUsage",
    "SandboxResult",
    "ScenarioOverride",
    "SensitivityEntry",
    "SimulationCapabilities",
    "SimulationEngine",
    "SimulationFailureCode",
    "SimulationHorizon",
    "SimulationResult",
    "SimulationResultVariable",
    "SimulationSpec",
    "ValidationCheck",
    "ValidationReport",
    "spec_content_hash",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class EngineKind(StrEnum):
    DETERMINISTIC = "deterministic"
    MONTE_CARLO = "monte_carlo"
    SYSTEM_DYNAMICS = "system_dynamics"
    AGENT_BASED = "agent_based"
    OPTIMIZATION = "optimization"


class ConvergenceStatus(StrEnum):
    CONVERGED = "CONVERGED"
    NOT_CONVERGED = "NOT_CONVERGED"


class SimulationFailureCode(StrEnum):
    SIM_TIMEOUT = "SIM_TIMEOUT"
    SIM_UNSTABLE = "SIM_UNSTABLE"
    SIM_SCHEMA = "SIM_SCHEMA"
    SIM_UNAVAILABLE = "SIM_UNAVAILABLE"
    SPEC_UNLINKED = "SPEC_UNLINKED"
    SPEC_DIM_MISMATCH = "SPEC_DIM_MISMATCH"
    SPEC_UNIT_MISSING = "SPEC_UNIT_MISSING"
    SPEC_BUDGET = "SPEC_BUDGET"


class NetworkPolicy(StrEnum):
    NONE = "NONE"
    EGRESS_ONLY = "EGRESS_ONLY"


# ---------------------------------------------------------------------------
# Spec value objects
# ---------------------------------------------------------------------------


class DistributionSpec(_Frozen):
    type: str = Field(min_length=1)
    min: Decimal | None = None
    max: Decimal | None = None
    mode: Decimal | None = None
    mean: Decimal | None = None
    sd: Decimal | None = None

    @model_validator(mode="after")
    def at_least_one_shape(self) -> DistributionSpec:
        if not any(getattr(self, f) is not None for f in ("min", "max", "mode", "mean", "sd")):
            raise ValueError("distribution must declare at least one shape parameter")
        return self


class ParameterSpec(_Frozen):
    name: str = Field(min_length=1)
    value: Decimal | None = None
    distribution: DistributionSpec | None = None
    source: str = Field(min_length=1)

    @model_validator(mode="after")
    def value_or_distribution(self) -> ParameterSpec:
        if self.value is None and self.distribution is None:
            raise ValueError("parameter must declare either a value or a distribution")
        return self


class ScenarioOverride(_Frozen):
    name: str = Field(min_length=1)
    overrides: dict[str, Any] = Field(default_factory=dict)


class SimulationHorizon(_Frozen):
    steps: int = Field(gt=0)
    dt: Decimal = Field(gt=0)
    unit: str = Field(min_length=1)


class RunBudget(_Frozen):
    max_runs: int = Field(gt=0)
    max_seconds: int = Field(gt=0)
    max_cost_usd: Decimal = Field(ge=0)


# ---------------------------------------------------------------------------
# SimulationSpec
# ---------------------------------------------------------------------------


class SimulationSpec(_Frozen):
    spec_id: UUID
    kind: EngineKind
    model: dict[str, Any] = Field(min_length=1)
    parameters: tuple[ParameterSpec, ...] = Field(min_length=1)
    scenarios: tuple[ScenarioOverride, ...] = Field(min_length=1)
    horizon: SimulationHorizon
    outputs: tuple[str, ...] = Field(min_length=1)
    assumptions: tuple[str, ...] = Field(min_length=1)
    validity_domain: str = Field(min_length=1)
    budget: RunBudget
    seed: int
    engine_version: str = Field(min_length=1)
    schema_version: int = 1

    @field_validator("outputs")
    @classmethod
    def unique_outputs(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(v)) != len(v):
            raise ValueError("output variable names must be unique")
        return v

    @field_validator("parameters")
    @classmethod
    def unique_params(cls, v: tuple[ParameterSpec, ...]) -> tuple[ParameterSpec, ...]:
        if len({p.name for p in v}) != len(v):
            raise ValueError("parameter names must be unique")
        return v

    @field_validator("scenarios")
    @classmethod
    def unique_scenarios(cls, v: tuple[ScenarioOverride, ...]) -> tuple[ScenarioOverride, ...]:
        if len({s.name for s in v}) != len(v):
            raise ValueError("scenario names must be unique")
        return v

    @model_validator(mode="after")
    def schema_check(self) -> SimulationSpec:
        if self.schema_version != 1:
            raise ValueError("unsupported SimulationSpec schema_version")
        return self


def _canonical_json(obj: Any) -> bytes:
    """Deterministic JSON for hashing (RFC 8785 key order)."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def spec_content_hash(spec: SimulationSpec) -> str:
    """SP-1: content-addressed hash of the entire spec."""
    payload = json.loads(spec.model_dump_json())
    digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    return f"sha256:{digest}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ValidationCheck(_Frozen):
    check: str = Field(min_length=1)
    passed: bool
    failure_code: SimulationFailureCode | None = None
    detail: str = ""


class ValidationReport(_Frozen):
    spec_id: UUID
    checks: tuple[ValidationCheck, ...]
    valid: bool

    @model_validator(mode="after")
    def consistency(self) -> ValidationReport:
        if self.valid != all(c.passed for c in self.checks):
            raise ValueError("valid flag must match all checks passing")
        return self


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class SensitivityEntry(_Frozen):
    parameter: str = Field(min_length=1)
    method: str = Field(min_length=1)
    index: Decimal
    rank: int = Field(ge=1)


class ResourceUsage(_Frozen):
    wall_time_s: Decimal = Field(ge=0)
    cpu_seconds: Decimal = Field(ge=0)
    peak_memory_mb: Decimal = Field(ge=0)
    cost_estimate_usd: Decimal = Field(ge=0)


class SimulationResultVariable(_Frozen):
    variable: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    mean: Decimal | None = None
    sd: Decimal | None = None
    ci_low: Decimal | None = None
    ci_high: Decimal | None = None
    quantiles: dict[str, Decimal] = Field(default_factory=dict)
    distribution_ref: str | None = None
    sensitivity: tuple[SensitivityEntry, ...] = ()
    validity_domain: dict[str, Any] = Field(min_length=1)

    @model_validator(mode="after")
    def interval_consistency(self) -> SimulationResultVariable:
        if self.ci_low is not None and self.ci_high is not None and self.ci_low > self.ci_high:
            raise ValueError("ci_low must not exceed ci_high")
        return self


class SimulationResult(_Frozen):
    run_id: UUID
    spec_id: UUID
    spec_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    engine: str = Field(min_length=1)
    engine_version: str = Field(min_length=1)
    seed: int
    run_count: int = Field(gt=0)
    convergence: ConvergenceStatus
    variables: tuple[SimulationResultVariable, ...] = Field(min_length=1)
    scenario_deltas: dict[str, Any] = Field(default_factory=dict)
    resource_usage: ResourceUsage
    warnings: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = Field(min_length=1)
    validity_domain: str = Field(min_length=1)
    evidence_kind: str = Field(default="SIMULATION_RESULT")
    artifact_ref: str | None = None
    schema_version: int = 1

    @field_validator("variables")
    @classmethod
    def unique_variables(
        cls, v: tuple[SimulationResultVariable, ...]
    ) -> tuple[SimulationResultVariable, ...]:
        if len({rv.variable for rv in v}) != len(v):
            raise ValueError("result variable names must be unique")
        return v

    @model_validator(mode="after")
    def result_invariants(self) -> SimulationResult:
        if self.schema_version != 1:
            raise ValueError("unsupported SimulationResult schema_version")
        if self.evidence_kind != "SIMULATION_RESULT":
            raise ValueError("evidence_kind must be SIMULATION_RESULT (FR-703)")
        return self


# ---------------------------------------------------------------------------
# SimulationEngine port — PORTS.md §8
# ---------------------------------------------------------------------------


class SimulationCapabilities(_Frozen):
    supports_distributions: bool = False
    supports_scenarios: bool = False
    supports_sensitivity: bool = False
    max_parameters: int = Field(default=1000, gt=0)
    max_horizon_steps: int = Field(default=100_000, gt=0)
    deterministic: bool = False


@runtime_checkable
class SimulationEngine(Protocol):
    name: str
    version: str

    def capabilities(self) -> SimulationCapabilities: ...
    def validate(self, spec: SimulationSpec) -> ValidationReport: ...
    async def run(
        self,
        spec: SimulationSpec,
        *,
        seed: int,
        budget: RunBudget,
    ) -> SimulationResult: ...


# ---------------------------------------------------------------------------
# SandboxExecutionProvider port — PORTS.md §11, ADR-018
# ---------------------------------------------------------------------------


class SandboxRequest(_Frozen):
    image_digest: str = Field(min_length=1, pattern=r"^sha256:[0-9a-f]{64}$")
    entrypoint: str = Field(min_length=1)
    args: tuple[str, ...] = ()
    input_artifact_refs: tuple[str, ...] = ()
    cpu_limit: Decimal = Field(default=Decimal("2.0"), gt=0)
    memory_limit_mb: int = Field(default=512, gt=0)
    disk_limit_mb: int = Field(default=256, gt=0)
    pids_limit: int = Field(default=128, gt=0)
    wall_clock_timeout_s: int = Field(default=120, gt=0)
    network_policy: NetworkPolicy = NetworkPolicy.NONE
    readonly_root: bool = True


class SandboxResourceUsage(_Frozen):
    wall_time_s: Decimal = Field(ge=0)
    cpu_seconds: Decimal = Field(ge=0)
    peak_memory_mb: Decimal = Field(ge=0)


class SandboxResult(_Frozen):
    exit_code: int
    stdout_ref: str | None = None
    stderr_ref: str | None = None
    resource_usage: SandboxResourceUsage
    terminated_by: str | None = None

    @model_validator(mode="after")
    def terminated_implies_nonzero(self) -> SandboxResult:
        if self.terminated_by and self.exit_code == 0:
            raise ValueError("terminated_by set but exit_code is 0")
        return self


@runtime_checkable
class SandboxExecutionProvider(Protocol):
    async def execute(self, request: SandboxRequest) -> SandboxResult: ...
    async def health(self) -> HealthStatus: ...
    async def close(self) -> None: ...
