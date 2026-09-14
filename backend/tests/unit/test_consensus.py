"""T9-03..T9-06 consensus strategy, registry and orchestrator tests.

Worked examples are taken verbatim from docs/consensus-formalism/{weighted,
evidence_weighted,constraint_aware}.md so the formal document and the code
cannot silently drift apart.

trace: T9-03, T9-04, T9-05, T9-06, FR-601..FR-608, FR-505, FR-506
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from app.application.consensus import (
    ConsensusError,
    ConsensusOrchestrator,
    ConstraintAwareStrategy,
    EvidenceWeightedStrategy,
    StrategyRegistry,
    WeightedStrategy,
)
from app.domain.consensus import ConsensusExplanation, ConsensusOutcome, ConsensusRunRecord
from app.ports.consensus import (
    AgentPosition,
    AlternativeInput,
    ConsensusContext,
    EvidenceCitationInput,
    FeasibilityStatus,
    FeasibilityVerdict,
    ObjectiveInput,
    StrategyConfig,
)
from tests.traceability import req


def _position(alt_id: UUID, stance: str, evidence_ids: tuple[UUID, ...] = ()) -> AgentPosition:
    return AgentPosition(
        agent_id=uuid4(),
        agent_definition_version="v1",
        alternative_id=alt_id,
        stance=stance,
        confidence=Decimal("1"),
        evidence_ids=evidence_ids,
    )


class FakeConsensusResultStore:
    """In-memory fake of `ConsensusResultStore` for orchestrator tests."""

    def __init__(self) -> None:
        self.results: dict[UUID, ConsensusRunRecord] = {}
        self.explanations: dict[UUID, ConsensusExplanation] = {}

    async def add_result(self, record: ConsensusRunRecord) -> None:
        self.results[record.id] = record

    async def get_result(self, workspace_id: UUID, result_id: UUID) -> ConsensusRunRecord | None:
        return self.results.get(result_id)

    async def list_results(
        self, workspace_id: UUID, session_id: UUID, *, strategy: str | None = None
    ) -> tuple[ConsensusRunRecord, ...]:
        return tuple(self.results.values())

    async def get_round_result(
        self,
        workspace_id: UUID,
        session_id: UUID,
        *,
        round: int,
    ) -> ConsensusRunRecord | None:
        for record in self.results.values():
            if record.session_id == session_id and record.round == round:
                return record
        return None

    async def add_explanation(
        self, workspace_id: UUID, result_id: UUID, explanation: ConsensusExplanation
    ) -> None:
        self.explanations[result_id] = explanation

    async def get_explanation(
        self, workspace_id: UUID, result_id: UUID
    ) -> ConsensusExplanation | None:
        return self.explanations.get(result_id)


# ---------------------------------------------------------------------------
# WeightedStrategy — docs/consensus-formalism/weighted.md worked example
# ---------------------------------------------------------------------------


@req("FR-505", "FR-604", "FR-605", "FR-606")
async def test_weighted_worked_example() -> None:
    """a1: SUPPORT,SUPPORT,OPPOSE -> 0.667; a2: OPPOSE,ABSTAIN,SUPPORT -> 0.5."""
    a1, a2 = uuid4(), uuid4()
    positions = (
        _position(a1, "SUPPORT"),
        _position(a1, "SUPPORT"),
        _position(a1, "OPPOSE"),
        _position(a2, "OPPOSE"),
        _position(a2, "ABSTAIN"),
        _position(a2, "SUPPORT"),
    )
    ctx = ConsensusContext(
        session_id=uuid4(),
        round=1,
        alternatives=(
            AlternativeInput(alternative_id=a1, name="a1"),
            AlternativeInput(alternative_id=a2, name="a2"),
        ),
        agent_positions=positions,
        strategy_config=StrategyConfig(
            strategy_name="weighted",
            strategy_version="1.0.0",
            parameters={"abstain_policy": "EXCLUDE", "alpha": "0.5"},
        ),
    )

    strategy = WeightedStrategy()
    result = await strategy.evaluate(ctx)
    by_id = {s.alternative_id: s for s in result.scores}

    assert by_id[a1].support == pytest.approx(Decimal("0.6667"), abs=Decimal("0.001"))
    assert by_id[a2].support == Decimal("0.5")
    assert result.outcome == ConsensusOutcome.PARTIAL_CONSENSUS
    assert result.selected_alternative_id == a1
    # C-3: explain() is total.
    explanation = strategy.explain(result)
    assert explanation.formula
    assert explanation.consensus_id == result.result_id


@req("FR-604")
async def test_weighted_no_alternatives_no_consensus() -> None:
    ctx = ConsensusContext(
        session_id=uuid4(),
        round=1,
        alternatives=(AlternativeInput(alternative_id=uuid4(), name="only"),),
        agent_positions=(),
        strategy_config=StrategyConfig(
            strategy_name="weighted", strategy_version="1.0.0", parameters={}
        ),
    )
    result = await WeightedStrategy().evaluate(ctx)
    assert result.outcome == ConsensusOutcome.NO_CONSENSUS
    assert result.degenerate_input is True


# ---------------------------------------------------------------------------
# EvidenceWeightedStrategy — docs/consensus-formalism/evidence_weighted.md
# ---------------------------------------------------------------------------


@req("FR-604")
async def test_evidence_weighted_worked_example() -> None:
    """E(a1) = 1.0*1.0 + 2*(0.3*0.6) = 1.36 per the doc's worked example."""
    a1, a2 = uuid4(), uuid4()
    ev_cc, ev_u1, ev_u2 = uuid4(), uuid4(), uuid4()

    positions = (
        _position(a1, "SUPPORT", (ev_cc, ev_u1, ev_u2)),
        _position(a1, "SUPPORT"),
        _position(a1, "SUPPORT"),
        _position(a2, "SUPPORT"),
        _position(a2, "SUPPORT"),
        _position(a2, "SUPPORT"),
    )
    evidence = (
        EvidenceCitationInput(
            evidence_id=ev_cc,
            verification="CROSS_CHECKED",
            trust_level="PRIMARY",
            polarity="SUPPORT",
            publisher="pub1",
        ),
        EvidenceCitationInput(
            evidence_id=ev_u1,
            verification="UNVERIFIED",
            trust_level="SECONDARY",
            polarity="SUPPORT",
            publisher="pub2",
        ),
        EvidenceCitationInput(
            evidence_id=ev_u2,
            verification="UNVERIFIED",
            trust_level="SECONDARY",
            polarity="SUPPORT",
            publisher="pub3",
        ),
    )
    ctx = ConsensusContext(
        session_id=uuid4(),
        round=1,
        alternatives=(
            AlternativeInput(alternative_id=a1, name="a1"),
            AlternativeInput(alternative_id=a2, name="a2"),
        ),
        agent_positions=positions,
        evidence=evidence,
        strategy_config=StrategyConfig(
            strategy_name="evidence_weighted",
            strategy_version="1.0.0",
            parameters={"evidence_weight": "0.4", "lambda": "0.5"},
        ),
    )

    result = await EvidenceWeightedStrategy().evaluate(ctx)
    by_id = {s.alternative_id: s for s in result.scores}
    assert by_id[a1].evidence_strength == Decimal("1.36")
    assert by_id[a2].evidence_strength == Decimal("0")
    assert result.outcome == ConsensusOutcome.FULL_CONSENSUS


@req("FR-604")
async def test_evidence_weighted_zero_citations_is_insufficient_evidence() -> None:
    """Failure mode: zero citations anywhere -> INSUFFICIENT_EVIDENCE."""
    a1 = uuid4()
    ctx = ConsensusContext(
        session_id=uuid4(),
        round=1,
        alternatives=(AlternativeInput(alternative_id=a1, name="a1"),),
        agent_positions=(_position(a1, "SUPPORT"),),
        strategy_config=StrategyConfig(
            strategy_name="evidence_weighted", strategy_version="1.0.0", parameters={}
        ),
    )
    result = await EvidenceWeightedStrategy().evaluate(ctx)
    assert result.outcome == ConsensusOutcome.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# ConstraintAwareStrategy — docs/consensus-formalism/constraint_aware.md
# ---------------------------------------------------------------------------


@req("FR-604")
async def test_constraint_aware_stage2_no_evidence_is_insufficient_evidence() -> None:
    """Stage 2 evidence floor: no alternative has E > 0 -> INSUFFICIENT_EVIDENCE."""
    a1 = uuid4()
    ctx = ConsensusContext(
        session_id=uuid4(),
        round=1,
        alternatives=(AlternativeInput(alternative_id=a1, name="a1"),),
        agent_positions=(_position(a1, "SUPPORT"),),
        strategy_config=StrategyConfig(
            strategy_name="constraint_aware", strategy_version="1.0.0", parameters={}
        ),
    )
    result = await ConstraintAwareStrategy().evaluate(ctx)
    assert result.outcome == ConsensusOutcome.INSUFFICIENT_EVIDENCE


@req("FR-604", "FR-607")
async def test_constraint_aware_stage4_conflicting_objectives_is_pareto_set() -> None:
    """Stage 4: declared-conflicting objectives with no dominance -> PARETO_SET."""
    a1, a2 = uuid4(), uuid4()
    o_cost, o_emissions = uuid4(), uuid4()
    ev1, ev2 = uuid4(), uuid4()
    positions = (
        _position(a1, "SUPPORT", (ev1,)),
        _position(a2, "SUPPORT", (ev2,)),
    )
    evidence = (
        EvidenceCitationInput(
            evidence_id=ev1,
            verification="CROSS_CHECKED",
            trust_level="PRIMARY",
            polarity="SUPPORT",
        ),
        EvidenceCitationInput(
            evidence_id=ev2,
            verification="CROSS_CHECKED",
            trust_level="PRIMARY",
            polarity="SUPPORT",
        ),
    )
    objectives = (
        ObjectiveInput(
            objective_id=o_cost,
            name="cost",
            weight=Decimal("0.5"),
            direction="MIN",
            conflicts_with=(o_emissions,),
        ),
        ObjectiveInput(
            objective_id=o_emissions,
            name="emissions",
            weight=Decimal("0.5"),
            direction="MIN",
            conflicts_with=(o_cost,),
        ),
    )
    objective_values = {
        str(o_cost): {str(a1): "1.0", str(a2): "0.2"},
        str(o_emissions): {str(a1): "0.2", str(a2): "1.0"},
    }
    ctx = ConsensusContext(
        session_id=uuid4(),
        round=1,
        alternatives=(
            AlternativeInput(alternative_id=a1, name="tariff"),
            AlternativeInput(alternative_id=a2, name="do-nothing"),
        ),
        agent_positions=positions,
        evidence=evidence,
        objectives=objectives,
        objective_values=objective_values,
        strategy_config=StrategyConfig(
            strategy_name="constraint_aware", strategy_version="1.0.0", parameters={}
        ),
    )
    result = await ConstraintAwareStrategy().evaluate(ctx)
    assert result.outcome == ConsensusOutcome.PARETO_SET
    assert set(result.pareto_set) == {a1, a2}
    assert result.selected_alternative_id is None


@req("FR-602", "FR-603", "FR-604")
async def test_constraint_aware_stage1_all_infeasible() -> None:
    """C-1: no strategy may rank an infeasible alternative."""
    a1 = uuid4()
    ctx = ConsensusContext(
        session_id=uuid4(),
        round=1,
        alternatives=(AlternativeInput(alternative_id=a1, name="a1"),),
        agent_positions=(_position(a1, "SUPPORT"),),
        feasibility=(
            FeasibilityVerdict(
                alternative_id=a1,
                status=FeasibilityStatus.UNSAT,
                unsat_core=("budget <= ceiling",),
            ),
        ),
        strategy_config=StrategyConfig(
            strategy_name="constraint_aware", strategy_version="1.0.0", parameters={}
        ),
    )
    result = await ConstraintAwareStrategy().evaluate(ctx)
    assert result.outcome == ConsensusOutcome.INFEASIBLE
    assert "budget <= ceiling" in result.blocking_constraints


@req("FR-708", "NFR-020")
@pytest.mark.parametrize(
    "strategy",
    [WeightedStrategy(), EvidenceWeightedStrategy(), ConstraintAwareStrategy()],
    ids=("weighted", "evidence_weighted", "constraint_aware"),
)
async def test_unknown_selection_is_explicitly_conditional_not_sat(
    strategy: object,
) -> None:
    unknown = uuid4()
    evidence_id = uuid4()
    ctx = ConsensusContext(
        session_id=uuid4(),
        round=1,
        alternatives=(AlternativeInput(alternative_id=unknown, name="unknown"),),
        agent_positions=(_position(unknown, "SUPPORT", (evidence_id,)),),
        evidence=(
            EvidenceCitationInput(
                evidence_id=evidence_id,
                verification="CROSS_CHECKED",
                trust_level="PRIMARY",
                polarity="SUPPORT",
                publisher="independent",
            ),
        ),
        feasibility=(
            FeasibilityVerdict(
                alternative_id=unknown,
                status=FeasibilityStatus.UNKNOWN,
                reason_unknown="timeout",
            ),
        ),
        strategy_config=StrategyConfig(
            strategy_name=cast(Any, strategy).name,
            strategy_version="1.0.0",
            parameters={"allow_unevidenced": True},
        ),
    )

    result = await cast(Any, strategy).evaluate(ctx)

    assert result.selected_alternative_id == unknown
    assert result.outcome is ConsensusOutcome.CONDITIONAL_CONSENSUS
    assert result.scores[0].feasibility is FeasibilityStatus.UNKNOWN
    assert any(step.outputs.get("unknown") == 1 for step in result.derivation)


@req("FR-708")
def test_consensus_unknown_verdict_cannot_fabricate_sat_or_unsat_evidence() -> None:
    with pytest.raises(ValueError, match="UNKNOWN requires only"):
        FeasibilityVerdict(
            alternative_id=uuid4(),
            status=FeasibilityStatus.UNKNOWN,
            reason_unknown="timeout",
            witness={"x": 1},
        )
    with pytest.raises(ValueError, match="UNSAT requires only"):
        FeasibilityVerdict(alternative_id=uuid4(), status=FeasibilityStatus.UNSAT)


@req("FR-708")
def test_consensus_rejects_duplicate_and_foreign_feasibility_verdicts() -> None:
    alternative = uuid4()
    verdict = FeasibilityVerdict(alternative_id=alternative, status=FeasibilityStatus.SAT)
    config = StrategyConfig(strategy_name="weighted", strategy_version="1.0.0", parameters={})

    with pytest.raises(ValueError, match="must be unique"):
        ConsensusContext(
            session_id=uuid4(),
            round=1,
            alternatives=(AlternativeInput(alternative_id=alternative, name="a"),),
            feasibility=(verdict, verdict),
            strategy_config=config,
        )
    with pytest.raises(ValueError, match="must reference"):
        ConsensusContext(
            session_id=uuid4(),
            round=1,
            alternatives=(AlternativeInput(alternative_id=alternative, name="a"),),
            feasibility=(FeasibilityVerdict(alternative_id=uuid4(), status=FeasibilityStatus.SAT),),
            strategy_config=config,
        )


# ---------------------------------------------------------------------------
# StrategyRegistry — T9-06, S-1, FR-608
# ---------------------------------------------------------------------------


@req("FR-608")
def test_registry_rejects_undocumented_strategy() -> None:
    """S-1: no formal document, no registration."""
    with pytest.raises(ConsensusError, match="no formal document"):
        StrategyRegistry(
            [WeightedStrategy()],
            documented_names=frozenset({"some_other_strategy"}),
        )


@req("FR-608")
def test_registry_rejects_duplicate_name_and_version() -> None:
    with pytest.raises(ConsensusError, match="duplicate"):
        StrategyRegistry(
            [WeightedStrategy(), WeightedStrategy()],
            documented_names=frozenset({"weighted"}),
        )


@req("FR-601")
def test_registry_resolves_registered_strategy() -> None:
    registry = StrategyRegistry([WeightedStrategy()], documented_names=frozenset({"weighted"}))
    resolved = registry.resolve("weighted", "1.0.0")
    assert resolved.name == "weighted"


@req("FR-608")
def test_registry_raises_on_unknown_strategy() -> None:
    registry = StrategyRegistry([WeightedStrategy()], documented_names=frozenset({"weighted"}))
    with pytest.raises(ConsensusError, match="unknown consensus strategy"):
        registry.resolve("nope", "1.0.0")


# ---------------------------------------------------------------------------
# ConsensusOrchestrator — T9-05, T9-06, S-2, S-3
# ---------------------------------------------------------------------------


@req("FR-505", "FR-506", "FR-601", "FR-605")
async def test_orchestrator_persists_result_and_explanation() -> None:
    registry = StrategyRegistry(
        [WeightedStrategy(), EvidenceWeightedStrategy(), ConstraintAwareStrategy()],
        documented_names=frozenset({"weighted", "evidence_weighted", "constraint_aware"}),
    )
    store = FakeConsensusResultStore()
    orchestrator = ConsensusOrchestrator(registry, store)

    a1 = uuid4()
    ctx = ConsensusContext(
        session_id=uuid4(),
        round=1,
        alternatives=(AlternativeInput(alternative_id=a1, name="a1"),),
        agent_positions=(_position(a1, "SUPPORT"),),
        strategy_config=StrategyConfig(
            strategy_name="weighted", strategy_version="1.0.0", parameters={}
        ),
    )
    workspace_id = uuid4()
    result = await orchestrator.run(workspace_id, ctx)

    assert result.result_id in store.results
    assert result.result_id in store.explanations
    record = store.results[result.result_id]
    assert record.strategy == "weighted"
    assert record.workspace_id == workspace_id


@req("FR-608")
async def test_orchestrator_raises_for_unknown_strategy() -> None:
    registry = StrategyRegistry([WeightedStrategy()], documented_names=frozenset({"weighted"}))
    orchestrator = ConsensusOrchestrator(registry, FakeConsensusResultStore())

    a1 = uuid4()
    ctx = ConsensusContext(
        session_id=uuid4(),
        round=1,
        alternatives=(AlternativeInput(alternative_id=a1, name="a1"),),
        agent_positions=(_position(a1, "SUPPORT"),),
        strategy_config=StrategyConfig(
            strategy_name="unregistered", strategy_version="1.0.0", parameters={}
        ),
    )
    with pytest.raises(ConsensusError, match="unknown consensus strategy"):
        await orchestrator.run(uuid4(), ctx)
