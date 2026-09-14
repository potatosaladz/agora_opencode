"""Consensus domain models — Phase 9 persistence contracts.

Re-exports port-level types and adds persistence-layer models:
  - ConsensusRunRecord (maps to consensus_results table)
  - ConsensusResultStore (persistence protocol)
  - feasibility_gate() — shared gate (C-1, FR-602)

Domain may import from ports per test_layering.py rules.

trace: T9-02, FR-602, FR-603
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.symbolic_unknown_policy import (
    SymbolicAssuranceAction,
    SymbolicUnknownPolicy,
)
from app.ports.consensus import (
    AbstainPolicy,
    AgentContribution,
    AgentPosition,
    AlternativeInput,
    AlternativeScore,
    AssumptionInput,
    ConsensusContext,
    ConsensusExplanation,
    ConsensusOutcome,
    ConsensusResult,
    ConstraintInput,
    CounterfactualEntry,
    CritiqueInput,
    DerivationStep,
    DissentEntry,
    EvidenceCitationInput,
    FeasibilityStatus,
    FeasibilityVerdict,
    MinorityEntry,
    ObjectiveInput,
    ObjectiveScore,
    PropositionInput,
    StrategyConfig,
    StrategyParameterSpec,
    _Frozen,
    consensus_input_hash,
)
from app.ports.symbolic import SymbolicStatus

__all__ = [
    # Re-exports from ports
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
    "ConsensusResultStore",
    "ConsensusRunRecord",
    "ConstraintInput",
    "CounterfactualEntry",
    "CritiqueInput",
    "DerivationStep",
    "DissentEntry",
    "EvidenceCitationInput",
    "FeasibilityGateResult",
    "FeasibilityStatus",
    "FeasibilityVerdict",
    "MinorityEntry",
    "ObjectiveInput",
    "ObjectiveScore",
    "PropositionInput",
    "StrategyConfig",
    "StrategyParameterSpec",
    "consensus_input_hash",
    "feasibility_gate",
]


# ---------------------------------------------------------------------------
# Feasibility gate — C-1, FR-602 (shared, not per-strategy)
# ---------------------------------------------------------------------------


# trace: FR-602, FR-603, FR-708
class FeasibilityGateResult(_Frozen):
    """Output of the shared feasibility gate.

    Implemented once in the coordinator. Cannot be disabled
    by a strategy. C-1 enforced by construction.
    """

    rankable: tuple[AlternativeInput, ...] = ()
    infeasible: tuple[FeasibilityVerdict, ...] = ()
    unknown: tuple[FeasibilityVerdict, ...] = ()
    all_infeasible: bool = False
    has_unknown: bool = False


def feasibility_gate(
    alternatives: tuple[AlternativeInput, ...],
    feasibility: tuple[FeasibilityVerdict, ...],
) -> FeasibilityGateResult:
    """Shared feasibility gate — FR-602, C-1.

    Before any formula runs:
    - UNSAT alternatives are removed from ranking, H(a) recorded
    - If all UNSAT → outcome INFEASIBLE; stop
    - UNKNOWN alternatives may be ranked only as unresolved and cap a selected result at CONDITIONAL
    """
    verdicts = {v.alternative_id: v for v in feasibility}
    unknown_policy = SymbolicUnknownPolicy()
    rankable: list[AlternativeInput] = []
    infeasible: list[FeasibilityVerdict] = []
    unknown: list[FeasibilityVerdict] = []

    for alt in alternatives:
        verdict = verdicts.get(alt.alternative_id)
        if verdict is None:
            # No applicable symbolic verdict means the gate has no symbolic claim to make.
            rankable.append(alt)
            continue
        action = unknown_policy.decide_status(
            SymbolicStatus(verdict.status.value),
            reason_unknown=verdict.reason_unknown,
        ).action
        if action is SymbolicAssuranceAction.PROCEED:
            rankable.append(alt)
        elif action is SymbolicAssuranceAction.BLOCK:
            infeasible.append(verdict)
        elif action is SymbolicAssuranceAction.DEFER:
            unknown.append(verdict)
            rankable.append(alt)

    return FeasibilityGateResult(
        rankable=tuple(rankable),
        infeasible=tuple(infeasible),
        unknown=tuple(unknown),
        all_infeasible=len(rankable) == 0,
        has_unknown=len(unknown) > 0,
    )


# ---------------------------------------------------------------------------
# ConsensusRunRecord — durable row per DATA_MODEL.md §7
# ---------------------------------------------------------------------------


class ConsensusRunRecord(_Frozen):
    """Durable record for a consensus result."""

    id: UUID
    workspace_id: UUID
    session_id: UUID
    round: int = Field(ge=1)
    strategy: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    outcome: ConsensusOutcome
    selected_alternative_id: UUID | None = None
    pareto_set: tuple[UUID, ...] = ()
    support: str | None = None
    dissent: str | None = None
    abstention: str | None = None
    coverage: str | None = None
    constraint_report: dict[str, Any] = Field(
        default_factory=dict,
    )
    conditions: tuple[str, ...] = ()
    input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime

    @model_validator(mode="after")
    def selection_feasibility(self) -> ConsensusRunRecord:
        """FR-603: infeasible alternatives cannot be selected."""
        selectable = {
            ConsensusOutcome.FULL_CONSENSUS,
            ConsensusOutcome.PARTIAL_CONSENSUS,
            ConsensusOutcome.CONDITIONAL_CONSENSUS,
        }
        if self.selected_alternative_id is not None and self.outcome not in selectable:
            raise ValueError(
                f"selected_alternative_id set but outcome {self.outcome} is not selectable (FR-603)"
            )
        return self


# ---------------------------------------------------------------------------
# ConsensusResultStore — persistence port
# ---------------------------------------------------------------------------


@runtime_checkable
class ConsensusResultStore(Protocol):
    """Caller-transaction-scoped persistence."""

    async def add_result(
        self,
        record: ConsensusRunRecord,
    ) -> None: ...

    async def get_result(
        self,
        workspace_id: UUID,
        result_id: UUID,
    ) -> ConsensusRunRecord | None: ...

    async def list_results(
        self,
        workspace_id: UUID,
        session_id: UUID,
        *,
        strategy: str | None = None,
    ) -> tuple[ConsensusRunRecord, ...]: ...

    async def add_explanation(
        self,
        workspace_id: UUID,
        result_id: UUID,
        explanation: ConsensusExplanation,
    ) -> None: ...

    async def get_explanation(
        self,
        workspace_id: UUID,
        result_id: UUID,
    ) -> ConsensusExplanation | None: ...
