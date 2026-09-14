"""`ConsensusStrategy` port and consensus value objects — PORTS.md §6.

Nothing here may import an infrastructure SDK, and nothing here may
import `app.adapters` or `app.domain` — enforced by `tests/test_layering.py`.

trace: T9-01, FR-601, FR-604, FR-605, FR-505, FR-506
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "AbstainPolicy",
    "AgentContribution",
    "AgentPosition",
    "AlternativeInput",
    "AlternativeScore",
    "AssumptionInput",
    "ConsensusContext",
    "ConsensusExplanation",
    "ConsensusOutcome",
    "ConsensusResult",
    "ConsensusStrategy",
    "ConstraintInput",
    "ConvergenceDecision",
    "ConvergenceState",
    "ConvergenceStrategy",
    "CounterfactualEntry",
    "CritiqueInput",
    "DerivationStep",
    "DissentEntry",
    "EvidenceCitationInput",
    "FeasibilityStatus",
    "FeasibilityVerdict",
    "MinorityEntry",
    "ObjectiveInput",
    "ObjectiveScore",
    "PropositionInput",
    "StrategyConfig",
    "StrategyParameterSpec",
    "consensus_input_hash",
]


# trace: FR-505, FR-506, FR-601, FR-603, FR-604, FR-605, FR-606
class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


# ---------------------------------------------------------------------------
# Enumerations — FR-604
# ---------------------------------------------------------------------------


class ConsensusOutcome(StrEnum):
    """Eight outcome classes required by FR-604."""

    FULL_CONSENSUS = "FULL_CONSENSUS"
    PARTIAL_CONSENSUS = "PARTIAL_CONSENSUS"
    CONDITIONAL_CONSENSUS = "CONDITIONAL_CONSENSUS"
    PARETO_SET = "PARETO_SET"
    NO_CONSENSUS = "NO_CONSENSUS"
    DEADLOCK = "DEADLOCK"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    INFEASIBLE = "INFEASIBLE"


class FeasibilityStatus(StrEnum):
    SAT = "SAT"
    UNSAT = "UNSAT"
    UNKNOWN = "UNKNOWN"


class AbstainPolicy(StrEnum):
    EXCLUDE = "EXCLUDE"
    HALF = "HALF"


# ---------------------------------------------------------------------------
# Consensus input value objects
# ---------------------------------------------------------------------------


class FeasibilityVerdict(_Frozen):
    """Per-alternative feasibility from the shared gate (C-1)."""

    alternative_id: UUID
    status: FeasibilityStatus
    unsat_core: tuple[str, ...] = ()
    witness: dict[str, Any] | None = None
    reason_unknown: str | None = None

    @model_validator(mode="after")
    def evidence_matches_status(self) -> FeasibilityVerdict:
        if self.status is FeasibilityStatus.SAT:
            if self.unsat_core or self.reason_unknown is not None:
                raise ValueError("SAT cannot contain contradiction or UNKNOWN evidence")
        elif self.status is FeasibilityStatus.UNSAT:
            if not self.unsat_core or self.witness is not None or self.reason_unknown is not None:
                raise ValueError("UNSAT requires only contradiction evidence")
        elif self.status is FeasibilityStatus.UNKNOWN and (
            self.reason_unknown is None
            or not self.reason_unknown.strip()
            or self.unsat_core
            or self.witness is not None
        ):
            raise ValueError("UNKNOWN requires only a non-empty reason")
        return self


class StrategyParameterSpec(_Frozen):
    """Declared parameter for a strategy — FR-608."""

    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    default: Any = None
    description: str = ""


class StrategyConfig(_Frozen):
    """Strategy selection and parameter binding (S-2)."""

    strategy_name: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class AgentPosition(_Frozen):
    """One agent's position on one alternative."""

    agent_id: UUID
    agent_definition_version: str = Field(min_length=1)
    alternative_id: UUID
    stance: str = Field(min_length=1)
    confidence: Decimal = Field(ge=0, le=1)
    rationale: str = ""
    evidence_ids: tuple[UUID, ...] = ()


class EvidenceCitationInput(_Frozen):
    """An evidence citation with verification and trust metadata."""

    evidence_id: UUID
    verification: str = Field(min_length=1)
    trust_level: str = Field(min_length=1)
    polarity: str = Field(min_length=1)
    publisher: str = ""


class ObjectiveInput(_Frozen):
    objective_id: UUID
    name: str = Field(min_length=1)
    weight: Decimal = Field(ge=0, le=1)
    direction: str = Field(min_length=1)
    conflicts_with: tuple[UUID, ...] = ()


class ConstraintInput(_Frozen):
    constraint_id: UUID
    name: str = Field(min_length=1)
    constraint_type: str = Field(min_length=1)
    formal_status: str = Field(min_length=1)


class AlternativeInput(_Frozen):
    alternative_id: UUID
    name: str = Field(min_length=1)


class PropositionInput(_Frozen):
    """Normalized proposition (FR-606)."""

    proposition_id: UUID
    normalized_text: str = Field(min_length=1)


class CritiqueInput(_Frozen):
    critique_id: UUID
    target_id: UUID
    critique_type: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    resolution: str = Field(min_length=1)


class AssumptionInput(_Frozen):
    assumption_id: UUID
    statement: str = Field(min_length=1)
    materiality: str = ""


class ConsensusContext(_Frozen):
    """Complete frozen input set — §2 of CONSENSUS_MODEL.md.

    A strategy may not fetch anything else.
    """

    session_id: UUID
    round: int = Field(ge=1)
    alternatives: tuple[AlternativeInput, ...] = Field(min_length=1)
    propositions: tuple[PropositionInput, ...] = ()
    agent_positions: tuple[AgentPosition, ...] = ()
    evidence: tuple[EvidenceCitationInput, ...] = ()
    assumptions: tuple[AssumptionInput, ...] = ()
    critiques: tuple[CritiqueInput, ...] = ()
    objectives: tuple[ObjectiveInput, ...] = ()
    constraints: tuple[ConstraintInput, ...] = ()
    feasibility: tuple[FeasibilityVerdict, ...] = ()
    strategy_config: StrategyConfig
    objective_values: dict[str, dict[str, str]] = Field(
        default_factory=dict,
    )

    @field_validator("alternatives")
    @classmethod
    def unique_alternatives(
        cls,
        v: tuple[AlternativeInput, ...],
    ) -> tuple[AlternativeInput, ...]:
        if len({a.alternative_id for a in v}) != len(v):
            raise ValueError("alternative IDs must be unique")
        return v

    @model_validator(mode="after")
    def feasibility_matches_alternatives(self) -> ConsensusContext:
        alternative_ids = {alternative.alternative_id for alternative in self.alternatives}
        verdict_ids = [verdict.alternative_id for verdict in self.feasibility]
        if len(set(verdict_ids)) != len(verdict_ids):
            raise ValueError("feasibility verdict alternative IDs must be unique")
        if not set(verdict_ids).issubset(alternative_ids):
            raise ValueError("feasibility verdict must reference a context alternative")
        return self


# ---------------------------------------------------------------------------
# Content-addressable input hash
# ---------------------------------------------------------------------------


def _canonical_json(value: Any) -> str:
    """Minimal deterministic JSON for hashing."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float | Decimal):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, UUID):
        return json.dumps(str(value), ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list | tuple):
        return "[" + ",".join(_canonical_json(i) for i in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value.keys())
        return (
            "{" + ",".join(f"{_canonical_json(k)}:{_canonical_json(value[k])}" for k in keys) + "}"
        )
    if isinstance(value, BaseModel):
        return _canonical_json(json.loads(value.model_dump_json()))
    return json.dumps(str(value), ensure_ascii=False, separators=(",", ":"))


def consensus_input_hash(context: ConsensusContext) -> str:
    """SHA-256 of the canonical JSON of a ConsensusContext."""
    raw = json.loads(context.model_dump_json())
    canonical = _canonical_json(raw).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


# ---------------------------------------------------------------------------
# Consensus result value objects — FR-604, FR-605
# ---------------------------------------------------------------------------


class AlternativeScore(_Frozen):
    """Per-alternative score computed by a strategy."""

    alternative_id: UUID
    alternative_name: str = Field(min_length=1)
    rank: int = Field(ge=1)
    support: Decimal = Field(ge=0, le=1)
    value_score: Decimal | None = None
    rank_score: Decimal | None = None
    feasibility: FeasibilityStatus = FeasibilityStatus.SAT
    evidence_strength: Decimal | None = None


class ObjectiveScore(_Frozen):
    alternative_id: UUID
    objective_id: UUID
    raw_value: Decimal | None = None
    normalized: Decimal | None = Field(default=None, ge=0, le=1)


class AgentContribution(_Frozen):
    """Per-agent contribution to the result (FR-605)."""

    agent_id: UUID
    alternative_id: UUID
    stance: str = Field(min_length=1)
    position_score: Decimal = Field(ge=0)
    confidence: Decimal = Field(ge=0, le=1)
    evidence_score: Decimal = Field(default=Decimal("0"), ge=0)


class DissentEntry(_Frozen):
    """Dissenting or abstaining agent record (FR-505)."""

    agent_id: UUID
    stance: str = Field(min_length=1)
    warrant_artifact_ids: tuple[UUID, ...] = ()
    disputed_proposition_ids: tuple[UUID, ...] = ()
    unresolved_critique_ids: tuple[UUID, ...] = ()
    what_would_change: str = ""


class MinorityEntry(_Frozen):
    """Minority report entry — FR-505, FR-506."""

    agent_id: UUID
    position: str = Field(min_length=1)
    warrant_artifact_ids: tuple[UUID, ...] = ()
    disputed_propositions: tuple[UUID, ...] = ()
    unresolved_critiques: tuple[UUID, ...] = ()
    what_would_change: str = ""


class DerivationStep(_Frozen):
    step: int = Field(ge=1)
    stage: str = Field(min_length=1)
    description: str = Field(min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)


class CounterfactualEntry(_Frozen):
    change: str = Field(min_length=1)
    effect: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class ConsensusResult(_Frozen):
    """Full result of a consensus evaluation — FR-604, FR-605."""

    result_id: UUID
    session_id: UUID
    round: int = Field(ge=1)
    strategy: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    outcome: ConsensusOutcome
    scores: tuple[AlternativeScore, ...] = ()
    selected_alternative_id: UUID | None = None
    pareto_set: tuple[UUID, ...] = ()
    support: Decimal | None = Field(default=None, ge=0, le=1)
    dissent_ratio: Decimal | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    abstention_ratio: Decimal | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    blocking_constraints: tuple[str, ...] = ()
    blocking_critiques: tuple[UUID, ...] = ()
    conditions: tuple[str, ...] = ()
    degenerate_input: bool = False
    input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    contributions: tuple[AgentContribution, ...] = ()
    dissent: tuple[DissentEntry, ...] = ()
    minority_report: tuple[MinorityEntry, ...] = ()
    derivation: tuple[DerivationStep, ...] = ()
    schema_version: int = 1

    @model_validator(mode="after")
    def result_invariants(self) -> ConsensusResult:
        if self.schema_version != 1:
            raise ValueError("unsupported ConsensusResult schema_version")
        _selectable = {
            ConsensusOutcome.FULL_CONSENSUS,
            ConsensusOutcome.PARTIAL_CONSENSUS,
            ConsensusOutcome.CONDITIONAL_CONSENSUS,
        }
        if self.selected_alternative_id is not None and self.outcome not in _selectable:
            raise ValueError(
                f"selected_alternative_id set but outcome {self.outcome} is not selectable (FR-603)"
            )
        return self


class ConsensusExplanation(_Frozen):
    """Structured explanation — FR-605, C-3."""

    consensus_id: UUID
    outcome: ConsensusOutcome
    strategy: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    weights: dict[str, Any] = Field(default_factory=dict)
    thresholds: dict[str, Any] = Field(default_factory=dict)
    contributions: tuple[AgentContribution, ...] = ()
    derivation: tuple[DerivationStep, ...] = ()
    caveats: tuple[str, ...] = ()
    minority_report: tuple[MinorityEntry, ...] = ()
    counterfactuals: tuple[CounterfactualEntry, ...] = ()
    flip_distance: Decimal | None = None
    degenerate_input: bool = False
    input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# ConsensusStrategy port — PORTS.md §6, FR-601
# ---------------------------------------------------------------------------


@runtime_checkable
class ConsensusStrategy(Protocol):
    name: str
    version: str

    def required_inputs(self) -> frozenset[str]: ...
    def parameters(
        self,
    ) -> Mapping[str, StrategyParameterSpec]: ...
    async def evaluate(
        self,
        context: ConsensusContext,
    ) -> ConsensusResult: ...
    def explain(
        self,
        result: ConsensusResult,
    ) -> ConsensusExplanation: ...


# ---------------------------------------------------------------------------
# ConvergenceStrategy port — PORTS.md §6
# ---------------------------------------------------------------------------


class ConvergenceState(_Frozen):
    round: int = Field(ge=1)
    position_movement: Decimal = Field(ge=0)
    unresolved_critiques: int = Field(ge=0)
    evidence_gaps_closed: int = Field(ge=0)
    budget_remaining_rounds: int = Field(ge=0)
    budget_remaining_tokens: int = Field(ge=0)
    oscillation_detected: bool = False


class ConvergenceDecision(_Frozen):
    should_continue: bool
    reason: str = Field(min_length=1)


@runtime_checkable
class ConvergenceStrategy(Protocol):
    async def evaluate(
        self,
        state: ConvergenceState,
    ) -> ConvergenceDecision: ...
