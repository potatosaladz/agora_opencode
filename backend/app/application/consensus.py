"""Consensus engine — strategy implementations and orchestrator.

trace: T9-03, T9-04, T9-05, T9-06
FR-601, FR-602, FR-603, FR-604, FR-605, FR-606, FR-607, FR-608
FR-505, FR-506
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID, uuid4

from app.domain.consensus import (
    ConsensusOutcome,
    ConsensusResultStore,
    ConsensusRunRecord,
    FeasibilityStatus,
    feasibility_gate,
)
from app.ports.consensus import (
    AbstainPolicy,
    AgentContribution,
    AgentPosition,
    AlternativeScore,
    ConsensusContext,
    ConsensusExplanation,
    ConsensusResult,
    ConsensusStrategy,
    CritiqueInput,
    DerivationStep,
    DissentEntry,
    EvidenceCitationInput,
    MinorityEntry,
    ObjectiveInput,
    StrategyParameterSpec,
    consensus_input_hash,
)

__all__ = [
    "ConsensusError",
    "ConsensusOrchestrator",
    "ConstraintAwareStrategy",
    "EvidenceWeightedStrategy",
    "StrategyRegistry",
    "WeightedStrategy",
]


# trace: FR-505, FR-506, FR-601, FR-602, FR-605, FR-607, FR-608
class ConsensusError(Exception):
    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(detail)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_POSITION_WEIGHTS: dict[str, Decimal] = {
    "SUPPORT": Decimal("1"),
    "CONDITIONALLY_SUPPORT": Decimal("0.75"),
    "INSUFFICIENT_EVIDENCE": Decimal("0.25"),
    "OPPOSE": Decimal("0"),
    "ABSTAIN": Decimal("0.5"),
}


def _position_score(
    stance: str,
    confidence: Decimal,
    use_confidence: bool,
    weights: dict[str, Decimal] | None = None,
) -> Decimal:
    w = (weights or _POSITION_WEIGHTS).get(stance, Decimal("0.5"))
    if use_confidence:
        return w * confidence
    return w


def _compute_support(
    alt_id: UUID,
    positions: tuple[AgentPosition, ...],
    use_confidence: bool,
    abstain_policy: AbstainPolicy,
    weights: dict[str, Decimal] | None = None,
) -> tuple[Decimal, int]:
    """Return (support, active_count) for an alternative."""
    relevant = [p for p in positions if p.alternative_id == alt_id]
    if abstain_policy == AbstainPolicy.EXCLUDE:
        relevant = [p for p in relevant if p.stance != "ABSTAIN"]
    if not relevant:
        return Decimal("0"), 0
    total = sum(
        (
            _position_score(
                p.stance,
                p.confidence,
                use_confidence,
                weights,
            )
            for p in relevant
        ),
        start=Decimal("0"),
    )
    return total / len(relevant), len(relevant)


def _blocking_critiques(
    critiques: tuple[CritiqueInput, ...],
) -> tuple[UUID, ...]:
    return tuple(
        c.critique_id
        for c in critiques
        if c.severity == "BLOCKING" and c.resolution in ("OPEN", "UNRESOLVED", "DISPUTED")
    )


def _build_dissent(
    alt_id: UUID,
    positions: tuple[AgentPosition, ...],
) -> tuple[DissentEntry, ...]:
    """FR-505: every dissenting/abstaining agent recorded."""
    return tuple(
        DissentEntry(
            agent_id=p.agent_id,
            stance=p.stance,
            warrant_artifact_ids=p.evidence_ids,
        )
        for p in positions
        if p.alternative_id == alt_id
        and p.stance
        in (
            "OPPOSE",
            "ABSTAIN",
            "INSUFFICIENT_EVIDENCE",
        )
    )


def _build_minority(
    alt_id: UUID,
    positions: tuple[AgentPosition, ...],
    critiques: tuple[CritiqueInput, ...],
) -> tuple[MinorityEntry, ...]:
    """FR-505, FR-506: minority report always present."""
    unresolved = {
        c.critique_id for c in critiques if c.resolution in ("OPEN", "UNRESOLVED", "DISPUTED")
    }
    return tuple(
        MinorityEntry(
            agent_id=p.agent_id,
            position=p.stance,
            warrant_artifact_ids=p.evidence_ids,
            unresolved_critiques=tuple(unresolved),
        )
        for p in positions
        if p.alternative_id == alt_id and p.stance in ("OPPOSE", "INSUFFICIENT_EVIDENCE")
    )


def _contributions(
    positions: tuple[AgentPosition, ...],
    use_confidence: bool,
) -> tuple[AgentContribution, ...]:
    return tuple(
        AgentContribution(
            agent_id=p.agent_id,
            alternative_id=p.alternative_id,
            stance=p.stance,
            position_score=_position_score(
                p.stance,
                p.confidence,
                use_confidence,
            ),
            confidence=p.confidence,
        )
        for p in positions
    )


def _blocking_gate_outcome(
    blocking: tuple[UUID, ...],
    candidate: ConsensusOutcome,
) -> ConsensusOutcome:
    """C-6: unresolved blocking critique caps at PARTIAL_CONSENSUS."""
    if blocking and candidate == ConsensusOutcome.FULL_CONSENSUS:
        return ConsensusOutcome.PARTIAL_CONSENSUS
    return candidate


def _degenerate(context: ConsensusContext) -> bool:
    """FR result flag: one alternative, one active agent, or none."""
    active_agents = {p.agent_id for p in context.agent_positions}
    return len(context.alternatives) <= 1 or len(active_agents) <= 1


def _weighted_objective_value(
    alt_id: UUID,
    objectives: tuple[ObjectiveInput, ...],
    objective_values: dict[str, dict[str, str]],
) -> Decimal | None:
    """value(a) = Σ_k w_k · v_k(a); returns None when no objective has a value."""
    total = Decimal("0")
    any_value = False
    for obj in objectives:
        raw = objective_values.get(str(obj.objective_id), {}).get(str(alt_id))
        if raw is None:
            continue
        any_value = True
        total += obj.weight * Decimal(raw)
    return total if any_value else None


def _derivation(
    stage: str,
    description: str,
    step: int,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
) -> DerivationStep:
    return DerivationStep(
        step=step,
        stage=stage,
        description=description,
        inputs=inputs,
        outputs=outputs,
    )


def _empty_explanation(
    result: ConsensusResult,
    formula: str,
    weights: dict[str, Any],
    thresholds: dict[str, Any],
    caveats: tuple[str, ...] = (),
) -> ConsensusExplanation:
    """C-3: explain(result) is total — never raises, never empty."""
    return ConsensusExplanation(
        consensus_id=result.result_id,
        outcome=result.outcome,
        strategy=result.strategy,
        strategy_version=result.strategy_version,
        formula=formula,
        weights=weights,
        thresholds=thresholds,
        contributions=result.contributions,
        derivation=result.derivation,
        caveats=caveats,
        minority_report=result.minority_report,
        counterfactuals=(),
        flip_distance=None,
        degenerate_input=result.degenerate_input,
        input_hash=result.input_hash,
    )


# ---------------------------------------------------------------------------
# WeightedStrategy — consensus-formalism/weighted.md
# ---------------------------------------------------------------------------


class WeightedStrategy:
    """Deterministic linear aggregation of positions and objective value.

    trace: T9-03, FR-601, FR-602, FR-603, FR-604, FR-605, FR-606, FR-607
    """

    name = "weighted"
    version = "1.0.0"

    _PARAMS: ClassVar[dict[str, StrategyParameterSpec]] = {
        "position_weights": StrategyParameterSpec(
            name="position_weights",
            type="map",
            default=dict(_POSITION_WEIGHTS),
            description="maps a position to a score",
        ),
        "use_confidence": StrategyParameterSpec(
            name="use_confidence",
            type="bool",
            default=False,
            description="whether c(a,i) scales the position score",
        ),
        "abstain_policy": StrategyParameterSpec(
            name="abstain_policy",
            type="enum",
            default=AbstainPolicy.EXCLUDE.value,
            description="how abstentions enter the denominator",
        ),
        "agreement_threshold": StrategyParameterSpec(
            name="agreement_threshold",
            type="float",
            default="0.66",
            description="upper bound for FULL_CONSENSUS",
        ),
        "partial_threshold": StrategyParameterSpec(
            name="partial_threshold",
            type="float",
            default="0.5",
            description="lower bound for any consensus claim",
        ),
        "alpha": StrategyParameterSpec(
            name="alpha",
            type="float",
            default="0.5",
            description=("blend between support and objective value in rank_score"),
        ),
    }

    def required_inputs(self) -> frozenset[str]:
        return frozenset({"alternatives", "agent_positions", "objectives", "critiques"})

    def parameters(self) -> Mapping[str, StrategyParameterSpec]:
        return dict(self._PARAMS)

    async def evaluate(self, context: ConsensusContext) -> ConsensusResult:
        params = context.strategy_config.parameters
        use_confidence = bool(params.get("use_confidence", False))
        abstain_policy = AbstainPolicy(params.get("abstain_policy", AbstainPolicy.EXCLUDE.value))
        agreement_threshold = Decimal(str(params.get("agreement_threshold", "0.66")))
        partial_threshold = Decimal(str(params.get("partial_threshold", "0.5")))
        alpha = Decimal(str(params.get("alpha", "0.5")))
        raw_weights = params.get("position_weights")
        weights = {k: Decimal(str(v)) for k, v in raw_weights.items()} if raw_weights else None

        input_hash = consensus_input_hash(context)
        gate = feasibility_gate(context.alternatives, context.feasibility)
        derivation: list[DerivationStep] = [
            _derivation(
                "feasibility",
                "shared feasibility gate applied before ranking (C-1)",
                1,
                {"alternative_count": len(context.alternatives)},
                {
                    "rankable": len(gate.rankable),
                    "infeasible": len(gate.infeasible),
                    "unknown": len(gate.unknown),
                },
            )
        ]

        if gate.all_infeasible:
            return ConsensusResult(
                result_id=uuid4(),
                session_id=context.session_id,
                round=context.round,
                strategy=self.name,
                strategy_version=self.version,
                outcome=ConsensusOutcome.INFEASIBLE,
                blocking_constraints=tuple(core for v in gate.infeasible for core in v.unsat_core),
                degenerate_input=_degenerate(context),
                input_hash=input_hash,
                derivation=tuple(derivation),
            )

        blocking = _blocking_critiques(context.critiques)
        scores: list[AlternativeScore] = []
        contributions: list[AgentContribution] = []
        dissent: list[DissentEntry] = []
        minority: list[MinorityEntry] = []
        rank_scores: dict[UUID, Decimal] = {}

        for alt in gate.rankable:
            support, _active = _compute_support(
                alt.alternative_id,
                context.agent_positions,
                use_confidence,
                abstain_policy,
                weights,
            )
            value = _weighted_objective_value(
                alt.alternative_id, context.objectives, context.objective_values
            )
            rank_score = (
                alpha * support + (Decimal("1") - alpha) * value if value is not None else support
            )
            rank_scores[alt.alternative_id] = rank_score
            contributions.extend(
                _contributions(
                    tuple(
                        p for p in context.agent_positions if p.alternative_id == alt.alternative_id
                    ),
                    use_confidence,
                )
            )
            dissent.extend(_build_dissent(alt.alternative_id, context.agent_positions))
            minority.extend(
                _build_minority(alt.alternative_id, context.agent_positions, context.critiques)
            )
            unk = next(
                (v for v in gate.unknown if v.alternative_id == alt.alternative_id),
                None,
            )
            scores.append(
                AlternativeScore(
                    alternative_id=alt.alternative_id,
                    alternative_name=alt.name,
                    rank=1,
                    support=max(Decimal("0"), min(Decimal("1"), support)),
                    value_score=value,
                    rank_score=rank_score,
                    feasibility=(
                        FeasibilityStatus.UNKNOWN if unk is not None else FeasibilityStatus.SAT
                    ),
                    evidence_strength=None,
                )
            )

        ranked = sorted(scores, key=lambda s: rank_scores[s.alternative_id], reverse=True)
        scores = [s.model_copy(update={"rank": i + 1}) for i, s in enumerate(ranked)]
        derivation.append(
            _derivation(
                "ranking",
                "support and rank_score computed per feasible alternative",
                2,
                {"alpha": str(alpha)},
                {
                    str(s.alternative_id): {
                        "support": str(s.support),
                        "rank_score": str(s.rank_score),
                    }
                    for s in scores
                },
            )
        )

        if not scores:
            return ConsensusResult(
                result_id=uuid4(),
                session_id=context.session_id,
                round=context.round,
                strategy=self.name,
                strategy_version=self.version,
                outcome=ConsensusOutcome.NO_CONSENSUS,
                degenerate_input=_degenerate(context),
                input_hash=input_hash,
                derivation=tuple(derivation),
            )

        leader = scores[0]
        leader_support = leader.support
        all_active_supportive = all(
            p.stance in ("SUPPORT", "ABSTAIN")
            for p in context.agent_positions
            if p.alternative_id == leader.alternative_id
        )

        if leader_support >= agreement_threshold and all_active_supportive:
            outcome = ConsensusOutcome.FULL_CONSENSUS
        elif leader_support >= partial_threshold:
            outcome = ConsensusOutcome.PARTIAL_CONSENSUS
        else:
            outcome = ConsensusOutcome.NO_CONSENSUS

        if any(v.alternative_id == leader.alternative_id for v in gate.unknown):
            outcome = ConsensusOutcome.CONDITIONAL_CONSENSUS

        outcome = _blocking_gate_outcome(blocking, outcome)

        selected = (
            leader.alternative_id
            if outcome
            in (
                ConsensusOutcome.FULL_CONSENSUS,
                ConsensusOutcome.PARTIAL_CONSENSUS,
                ConsensusOutcome.CONDITIONAL_CONSENSUS,
            )
            else None
        )

        total_positions = len(context.agent_positions) or 1
        dissent_count = len([p for p in context.agent_positions if p.stance == "OPPOSE"])
        abstain_count = len([p for p in context.agent_positions if p.stance == "ABSTAIN"])

        derivation.append(
            _derivation(
                "classify",
                "outcome classified from thresholds and blocking critiques",
                3,
                {
                    "agreement_threshold": str(agreement_threshold),
                    "partial_threshold": str(partial_threshold),
                },
                {
                    "outcome": outcome.value,
                    "leader_support": str(leader_support),
                },
            )
        )

        return ConsensusResult(
            result_id=uuid4(),
            session_id=context.session_id,
            round=context.round,
            strategy=self.name,
            strategy_version=self.version,
            outcome=outcome,
            scores=tuple(scores),
            selected_alternative_id=selected,
            support=leader_support,
            dissent_ratio=Decimal(dissent_count) / Decimal(total_positions),
            abstention_ratio=Decimal(abstain_count) / Decimal(total_positions),
            blocking_critiques=blocking,
            degenerate_input=_degenerate(context),
            input_hash=input_hash,
            contributions=tuple(contributions),
            dissent=tuple(dissent),
            minority_report=tuple(minority),
            derivation=tuple(derivation),
        )

    def explain(self, result: ConsensusResult) -> ConsensusExplanation:
        return _empty_explanation(
            result,
            formula=(
                "score(a,i)=s(p(a,i)) * (use_confidence?c(a,i):1); "
                "support(a)=sum(score)/|N_a|; "
                "rank_score(a)=alpha*support(a)+(1-alpha)*value(a)"
            ),
            weights={"position_weights": dict(_POSITION_WEIGHTS)},
            thresholds={},
        )


# ---------------------------------------------------------------------------
# EvidenceWeightedStrategy — consensus-formalism/evidence_weighted.md
# ---------------------------------------------------------------------------

_VERIFICATION_WEIGHTS: dict[str, Decimal] = {
    "UNVERIFIED": Decimal("0.3"),
    "SOURCE_VERIFIED": Decimal("0.8"),
    "CROSS_CHECKED": Decimal("1.0"),
    "DISPUTED": Decimal("0.1"),
    "REJECTED": Decimal("0.0"),
}

_TRUST_MULTIPLIER: dict[str, Decimal] = {
    "PRIMARY": Decimal("1.0"),
    "AUTHORITATIVE": Decimal("0.9"),
    "SECONDARY": Decimal("0.6"),
    "COMMERCIAL": Decimal("0.4"),
    "UNATTRIBUTED": Decimal("0.0"),
    "SYNTHETIC": Decimal("0.0"),
}


def _citation_weight(
    citation: EvidenceCitationInput,
    verification_weights: dict[str, Decimal],
    trust_multiplier: dict[str, Decimal],
) -> Decimal:
    v = verification_weights.get(citation.verification, Decimal("0"))
    t = trust_multiplier.get(citation.trust_level, Decimal("0"))
    return v * t


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


def _evidence_for_position(
    position: AgentPosition,
    evidence: tuple[EvidenceCitationInput, ...],
) -> tuple[EvidenceCitationInput, ...]:
    lookup = {e.evidence_id: e for e in evidence}
    return tuple(lookup[eid] for eid in position.evidence_ids if eid in lookup)


def _capped_by_publisher(
    citations: tuple[EvidenceCitationInput, ...],
    cap: int,
) -> tuple[EvidenceCitationInput, ...]:
    """independence_cap: max citations counted from one publisher."""
    counts: dict[str, int] = {}
    kept: list[EvidenceCitationInput] = []
    for c in citations:
        key = c.publisher or ""
        counts[key] = counts.get(key, 0) + 1
        if counts[key] <= cap:
            kept.append(c)
    return tuple(kept)


def _evidence_strength(
    position: AgentPosition,
    evidence: tuple[EvidenceCitationInput, ...],
    verification_weights: dict[str, Decimal],
    trust_multiplier: dict[str, Decimal],
    independence_cap: int,
) -> tuple[Decimal, Decimal]:
    """Return (E, D) for one agent position — evidence_weighted.md."""
    citations = _capped_by_publisher(_evidence_for_position(position, evidence), independence_cap)
    e_total = Decimal("0")
    d_total = Decimal("0")
    for c in citations:
        if c.verification == "REJECTED":
            continue
        w = _citation_weight(c, verification_weights, trust_multiplier)
        if c.polarity == "SUPPORT":
            e_total += w
        elif c.polarity == "OPPOSE":
            d_total += w
    return e_total, d_total


class EvidenceWeightedStrategy:
    """Support weighted by verified evidence strength.

    trace: T9-03, FR-601, FR-602, FR-603, FR-604, FR-605, FR-606, FR-607
    """

    name = "evidence_weighted"
    version = "1.0.0"

    _PARAMS: ClassVar[dict[str, StrategyParameterSpec]] = {
        **WeightedStrategy._PARAMS,
        "verification_weights": StrategyParameterSpec(
            name="verification_weights",
            type="map",
            default={k: str(v) for k, v in _VERIFICATION_WEIGHTS.items()},
            description="how much a citation counts",
        ),
        "trust_multiplier": StrategyParameterSpec(
            name="trust_multiplier",
            type="map",
            default={k: str(v) for k, v in _TRUST_MULTIPLIER.items()},
            description="source-quality scaling",
        ),
        "evidence_weight": StrategyParameterSpec(
            name="evidence_weight",
            type="float",
            default="0.4",
            description="beta: blend between raw and evidence-weighted support",
        ),
        "independence_cap": StrategyParameterSpec(
            name="independence_cap",
            type="int",
            default=2,
            description="max citations counted from one publisher",
        ),
        "lambda": StrategyParameterSpec(
            name="lambda",
            type="float",
            default="0.5",
            description="how much backing may raise a position",
        ),
    }

    def required_inputs(self) -> frozenset[str]:
        return frozenset(
            {
                "alternatives",
                "agent_positions",
                "objectives",
                "critiques",
                "evidence",
            }
        )

    def parameters(self) -> Mapping[str, StrategyParameterSpec]:
        return dict(self._PARAMS)

    async def evaluate(self, context: ConsensusContext) -> ConsensusResult:
        params = context.strategy_config.parameters
        use_confidence = bool(params.get("use_confidence", False))
        abstain_policy = AbstainPolicy(params.get("abstain_policy", AbstainPolicy.EXCLUDE.value))
        agreement_threshold = Decimal(str(params.get("agreement_threshold", "0.66")))
        partial_threshold = Decimal(str(params.get("partial_threshold", "0.5")))
        alpha = Decimal(str(params.get("alpha", "0.5")))
        beta = Decimal(str(params.get("evidence_weight", "0.4")))
        lam = Decimal(str(params.get("lambda", "0.5")))
        independence_cap = int(params.get("independence_cap", 2))
        raw_verif = params.get("verification_weights")
        verification_weights = (
            {k: Decimal(str(v)) for k, v in raw_verif.items()}
            if raw_verif
            else _VERIFICATION_WEIGHTS
        )
        raw_trust = params.get("trust_multiplier")
        trust_multiplier = (
            {k: Decimal(str(v)) for k, v in raw_trust.items()} if raw_trust else _TRUST_MULTIPLIER
        )
        raw_weights = params.get("position_weights")
        pos_weights = {k: Decimal(str(v)) for k, v in raw_weights.items()} if raw_weights else None

        input_hash = consensus_input_hash(context)
        gate = feasibility_gate(context.alternatives, context.feasibility)
        derivation: list[DerivationStep] = [
            _derivation(
                "feasibility",
                "shared feasibility gate applied before ranking (C-1)",
                1,
                {"alternative_count": len(context.alternatives)},
                {
                    "rankable": len(gate.rankable),
                    "infeasible": len(gate.infeasible),
                    "unknown": len(gate.unknown),
                },
            )
        ]

        if gate.all_infeasible:
            return ConsensusResult(
                result_id=uuid4(),
                session_id=context.session_id,
                round=context.round,
                strategy=self.name,
                strategy_version=self.version,
                outcome=ConsensusOutcome.INFEASIBLE,
                blocking_constraints=tuple(core for v in gate.infeasible for core in v.unsat_core),
                degenerate_input=_degenerate(context),
                input_hash=input_hash,
                derivation=tuple(derivation),
            )

        evw_blocking = _blocking_critiques(context.critiques)
        evw_scores: list[AlternativeScore] = []
        evw_contributions: list[AgentContribution] = []
        evw_dissent: list[DissentEntry] = []
        evw_minority: list[MinorityEntry] = []
        evw_rank_scores: dict[UUID, Decimal] = {}
        evw_evidence_totals: dict[UUID, Decimal] = {}

        for alt in gate.rankable:
            relevant = [
                p for p in context.agent_positions if p.alternative_id == alt.alternative_id
            ]
            if abstain_policy == AbstainPolicy.EXCLUDE:
                relevant = [p for p in relevant if p.stance != "ABSTAIN"]
            e_alt = Decimal("0")
            if relevant:
                weighted_terms = Decimal("0")
                for p in relevant:
                    e_i, d_i = _evidence_strength(
                        p,
                        context.evidence,
                        verification_weights,
                        trust_multiplier,
                        independence_cap,
                    )
                    e_alt += e_i
                    evid = _clamp(
                        (e_i - d_i) / (e_i + d_i + Decimal("1")),
                        Decimal("-1"),
                        Decimal("1"),
                    )
                    base = _position_score(p.stance, p.confidence, use_confidence, pos_weights)
                    weighted_terms += base * (Decimal("1") + lam * max(Decimal("0"), evid))
                support_ev = min(Decimal("1"), weighted_terms / Decimal(len(relevant)))
            else:
                support_ev = Decimal("0")
            evw_evidence_totals[alt.alternative_id] = e_alt

            support_weighted, _active = _compute_support(
                alt.alternative_id,
                context.agent_positions,
                use_confidence,
                abstain_policy,
                pos_weights,
            )
            support = (Decimal("1") - beta) * support_weighted + beta * support_ev

            value = _weighted_objective_value(
                alt.alternative_id, context.objectives, context.objective_values
            )
            rank_score = (
                alpha * support + (Decimal("1") - alpha) * value if value is not None else support
            )
            evw_rank_scores[alt.alternative_id] = rank_score

            evw_contributions.extend(_contributions(tuple(relevant), use_confidence))
            evw_dissent.extend(_build_dissent(alt.alternative_id, context.agent_positions))
            evw_minority.extend(
                _build_minority(alt.alternative_id, context.agent_positions, context.critiques)
            )
            unk = next(
                (v for v in gate.unknown if v.alternative_id == alt.alternative_id),
                None,
            )
            evw_scores.append(
                AlternativeScore(
                    alternative_id=alt.alternative_id,
                    alternative_name=alt.name,
                    rank=1,
                    support=max(Decimal("0"), min(Decimal("1"), support)),
                    value_score=value,
                    rank_score=rank_score,
                    feasibility=(
                        FeasibilityStatus.UNKNOWN if unk is not None else FeasibilityStatus.SAT
                    ),
                    evidence_strength=e_alt,
                )
            )

        evw_ranked = sorted(
            evw_scores, key=lambda s: evw_rank_scores[s.alternative_id], reverse=True
        )
        evw_scores = [s.model_copy(update={"rank": i + 1}) for i, s in enumerate(evw_ranked)]
        derivation.append(
            _derivation(
                "ranking",
                "support blended with evidence-weighted support_ev per alternative",
                2,
                {"alpha": str(alpha), "beta": str(beta), "lambda": str(lam)},
                {
                    str(s.alternative_id): {
                        "support": str(s.support),
                        "evidence_strength": str(s.evidence_strength),
                        "rank_score": str(s.rank_score),
                    }
                    for s in evw_scores
                },
            )
        )

        if not evw_scores:
            return ConsensusResult(
                result_id=uuid4(),
                session_id=context.session_id,
                round=context.round,
                strategy=self.name,
                strategy_version=self.version,
                outcome=ConsensusOutcome.NO_CONSENSUS,
                degenerate_input=_degenerate(context),
                input_hash=input_hash,
                derivation=tuple(derivation),
            )

        leader = evw_scores[0]

        if evw_evidence_totals.get(leader.alternative_id, Decimal("0")) == 0:
            return ConsensusResult(
                result_id=uuid4(),
                session_id=context.session_id,
                round=context.round,
                strategy=self.name,
                strategy_version=self.version,
                outcome=ConsensusOutcome.INSUFFICIENT_EVIDENCE,
                scores=tuple(evw_scores),
                blocking_critiques=evw_blocking,
                degenerate_input=_degenerate(context),
                input_hash=input_hash,
                contributions=tuple(evw_contributions),
                dissent=tuple(evw_dissent),
                minority_report=tuple(evw_minority),
                derivation=(
                    *derivation,
                    _derivation(
                        "evidence_gate",
                        "leading alternative has no verified backing (evidence_weighted.md)",
                        3,
                        {"alternative_id": str(leader.alternative_id)},
                        {"outcome": "INSUFFICIENT_EVIDENCE"},
                    ),
                ),
            )

        leader_support = leader.support
        all_active_supportive = all(
            p.stance in ("SUPPORT", "ABSTAIN")
            for p in context.agent_positions
            if p.alternative_id == leader.alternative_id
        )

        if leader_support >= agreement_threshold and all_active_supportive:
            outcome = ConsensusOutcome.FULL_CONSENSUS
        elif leader_support >= partial_threshold:
            outcome = ConsensusOutcome.PARTIAL_CONSENSUS
        else:
            outcome = ConsensusOutcome.NO_CONSENSUS

        if any(v.alternative_id == leader.alternative_id for v in gate.unknown):
            outcome = ConsensusOutcome.CONDITIONAL_CONSENSUS

        outcome = _blocking_gate_outcome(evw_blocking, outcome)

        selected = (
            leader.alternative_id
            if outcome
            in (
                ConsensusOutcome.FULL_CONSENSUS,
                ConsensusOutcome.PARTIAL_CONSENSUS,
                ConsensusOutcome.CONDITIONAL_CONSENSUS,
            )
            else None
        )

        total_positions = len(context.agent_positions) or 1
        dissent_count = len([p for p in context.agent_positions if p.stance == "OPPOSE"])
        abstain_count = len([p for p in context.agent_positions if p.stance == "ABSTAIN"])

        derivation.append(
            _derivation(
                "classify",
                "outcome classified from thresholds and blocking critiques",
                3,
                {
                    "agreement_threshold": str(agreement_threshold),
                    "partial_threshold": str(partial_threshold),
                },
                {
                    "outcome": outcome.value,
                    "leader_support": str(leader_support),
                },
            )
        )

        return ConsensusResult(
            result_id=uuid4(),
            session_id=context.session_id,
            round=context.round,
            strategy=self.name,
            strategy_version=self.version,
            outcome=outcome,
            scores=tuple(evw_scores),
            selected_alternative_id=selected,
            support=leader_support,
            dissent_ratio=Decimal(dissent_count) / Decimal(total_positions),
            abstention_ratio=Decimal(abstain_count) / Decimal(total_positions),
            blocking_critiques=evw_blocking,
            degenerate_input=_degenerate(context),
            input_hash=input_hash,
            contributions=tuple(evw_contributions),
            dissent=tuple(evw_dissent),
            minority_report=tuple(evw_minority),
            derivation=tuple(derivation),
        )

    def explain(self, result: ConsensusResult) -> ConsensusExplanation:
        return _empty_explanation(
            result,
            formula=(
                "w(e)=verif_w[verif(e)]*trust_m[trust(e)]; "
                "evid(i,a)=clamp((E-D)/(E+D+1),-1,1); "
                "support_ev(a)=sum(s(p)*(1+lambda*max(0,evid)))/|N_a|; "
                "support(a)=(1-beta)*support_weighted(a)+beta*support_ev(a)"
            ),
            weights={
                "verification_weights": {k: str(v) for k, v in _VERIFICATION_WEIGHTS.items()},
                "trust_multiplier": {k: str(v) for k, v in _TRUST_MULTIPLIER.items()},
            },
            thresholds={},
        )


# ---------------------------------------------------------------------------
# ConstraintAwareStrategy — consensus-formalism/constraint_aware.md
# ---------------------------------------------------------------------------


def _objective_value_lookup(
    alt_id: UUID,
    objectives: tuple[ObjectiveInput, ...],
    objective_values: dict[str, dict[str, str]],
) -> dict[UUID, Decimal]:
    """v_k(a) per objective for one alternative."""
    values: dict[UUID, Decimal] = {}
    for obj in objectives:
        raw = objective_values.get(str(obj.objective_id), {}).get(str(alt_id))
        if raw is not None:
            values[obj.objective_id] = Decimal(raw)
    return values


def _dominates(
    a_values: dict[UUID, Decimal],
    b_values: dict[UUID, Decimal],
    objective_ids: tuple[UUID, ...],
    epsilon: Decimal,
) -> bool:
    """True iff a dominates b: a >= b on all objectives, > on at least one."""
    if not objective_ids:
        return False
    at_least_one_better = False
    for k in objective_ids:
        av = a_values.get(k)
        bv = b_values.get(k)
        if av is None or bv is None:
            return False
        if av < bv:
            return False
        if av > bv + epsilon:
            at_least_one_better = True
    return at_least_one_better


def _undominated(
    alt_ids: tuple[UUID, ...],
    values_by_alt: dict[UUID, dict[UUID, Decimal]],
    objective_ids: tuple[UUID, ...],
    epsilon: Decimal,
) -> tuple[UUID, ...]:
    """Stage 3: undominated set P."""
    result = []
    for a in alt_ids:
        dominated = any(
            b != a
            and _dominates(
                values_by_alt.get(b, {}),
                values_by_alt.get(a, {}),
                objective_ids,
                epsilon,
            )
            for b in alt_ids
        )
        if not dominated:
            result.append(a)
    return tuple(result)


class ConstraintAwareStrategy:
    """Feasibility-gated lexicographic strategy — MVP default.

    Stages: (1) feasibility, (2) evidence floor, (3) dominance, (4) conflict
    test, (5) support order, (6) robustness, (7) classify.
    trace: T9-03, FR-601..FR-607, C-1..C-8
    """

    name = "constraint_aware"
    version = "1.0.0"

    _PARAMS: ClassVar[dict[str, StrategyParameterSpec]] = {
        **EvidenceWeightedStrategy._PARAMS,
        "allow_unevidenced": StrategyParameterSpec(
            name="allow_unevidenced",
            type="bool",
            default=False,
            description="skip the evidence floor at Stage 2",
        ),
        "epsilon": StrategyParameterSpec(
            name="epsilon",
            type="float",
            default="0.01",
            description="dominance tie-break margin",
        ),
        "min_flip_distance": StrategyParameterSpec(
            name="min_flip_distance",
            type="float",
            default="0.05",
            description="Stage 6 robustness threshold",
        ),
    }

    def required_inputs(self) -> frozenset[str]:
        return frozenset(
            {
                "alternatives",
                "agent_positions",
                "objectives",
                "critiques",
                "evidence",
                "constraints",
                "feasibility",
            }
        )

    def parameters(self) -> Mapping[str, StrategyParameterSpec]:
        return dict(self._PARAMS)

    async def evaluate(self, context: ConsensusContext) -> ConsensusResult:
        params = context.strategy_config.parameters
        use_confidence = bool(params.get("use_confidence", False))
        abstain_policy = AbstainPolicy(params.get("abstain_policy", AbstainPolicy.EXCLUDE.value))
        agreement_threshold = Decimal(str(params.get("agreement_threshold", "0.66")))
        partial_threshold = Decimal(str(params.get("partial_threshold", "0.5")))
        beta = Decimal(str(params.get("evidence_weight", "0.4")))
        lam = Decimal(str(params.get("lambda", "0.5")))
        independence_cap = int(params.get("independence_cap", 2))
        epsilon = Decimal(str(params.get("epsilon", "0.01")))
        min_flip_distance = Decimal(str(params.get("min_flip_distance", "0.05")))
        allow_unevidenced = bool(params.get("allow_unevidenced", False))
        raw_verif = params.get("verification_weights")
        verification_weights = (
            {k: Decimal(str(v)) for k, v in raw_verif.items()}
            if raw_verif
            else _VERIFICATION_WEIGHTS
        )
        raw_trust = params.get("trust_multiplier")
        trust_multiplier = (
            {k: Decimal(str(v)) for k, v in raw_trust.items()} if raw_trust else _TRUST_MULTIPLIER
        )
        raw_weights = params.get("position_weights")
        pos_weights = {k: Decimal(str(v)) for k, v in raw_weights.items()} if raw_weights else None

        input_hash = consensus_input_hash(context)

        # Stage 1: shared feasibility gate (C-1).
        gate = feasibility_gate(context.alternatives, context.feasibility)
        derivation: list[DerivationStep] = [
            _derivation(
                "stage1_feasibility",
                "UNSAT removed, unsat cores recorded; all UNSAT -> INFEASIBLE",
                1,
                {"alternative_count": len(context.alternatives)},
                {
                    "rankable": len(gate.rankable),
                    "infeasible": len(gate.infeasible),
                    "unknown": len(gate.unknown),
                },
            )
        ]
        if gate.all_infeasible:
            return ConsensusResult(
                result_id=uuid4(),
                session_id=context.session_id,
                round=context.round,
                strategy=self.name,
                strategy_version=self.version,
                outcome=ConsensusOutcome.INFEASIBLE,
                blocking_constraints=tuple(core for v in gate.infeasible for core in v.unsat_core),
                degenerate_input=_degenerate(context),
                input_hash=input_hash,
                derivation=tuple(derivation),
            )

        blocking = _blocking_critiques(context.critiques)

        # Precompute per-alternative evidence totals and support_ev for Stage 5.
        evidence_totals: dict[UUID, Decimal] = {}
        support_ev_by_alt: dict[UUID, Decimal] = {}
        contributions: list[AgentContribution] = []
        dissent: list[DissentEntry] = []
        minority: list[MinorityEntry] = []

        for alt in gate.rankable:
            relevant = [
                p for p in context.agent_positions if p.alternative_id == alt.alternative_id
            ]
            if abstain_policy == AbstainPolicy.EXCLUDE:
                relevant = [p for p in relevant if p.stance != "ABSTAIN"]
            e_alt = Decimal("0")
            if relevant:
                weighted_terms = Decimal("0")
                for p in relevant:
                    e_i, d_i = _evidence_strength(
                        p,
                        context.evidence,
                        verification_weights,
                        trust_multiplier,
                        independence_cap,
                    )
                    e_alt += e_i
                    evid = _clamp(
                        (e_i - d_i) / (e_i + d_i + Decimal("1")),
                        Decimal("-1"),
                        Decimal("1"),
                    )
                    base = _position_score(p.stance, p.confidence, use_confidence, pos_weights)
                    weighted_terms += base * (Decimal("1") + lam * max(Decimal("0"), evid))
                support_ev_alt = min(Decimal("1"), weighted_terms / Decimal(len(relevant)))
            else:
                support_ev_alt = Decimal("0")
            evidence_totals[alt.alternative_id] = e_alt
            support_weighted, _active = _compute_support(
                alt.alternative_id,
                context.agent_positions,
                use_confidence,
                abstain_policy,
                pos_weights,
            )
            support_ev_by_alt[alt.alternative_id] = (
                Decimal("1") - beta
            ) * support_weighted + beta * support_ev_alt
            contributions.extend(_contributions(tuple(relevant), use_confidence))
            dissent.extend(_build_dissent(alt.alternative_id, context.agent_positions))
            minority.extend(
                _build_minority(alt.alternative_id, context.agent_positions, context.critiques)
            )

        # Stage 2: evidence floor — keep iff Σ_i E(i,a) > 0 unless allow_unevidenced.
        stage1_ids = tuple(alt.alternative_id for alt in gate.rankable)
        if allow_unevidenced:
            stage2_ids = stage1_ids
        else:
            stage2_ids = tuple(a for a in stage1_ids if evidence_totals.get(a, Decimal("0")) > 0)
        derivation.append(
            _derivation(
                "stage2_evidence_floor",
                "alternatives with zero verified evidence excluded",
                2,
                {"allow_unevidenced": allow_unevidenced},
                {"remaining": len(stage2_ids)},
            )
        )
        if not stage2_ids:
            return ConsensusResult(
                result_id=uuid4(),
                session_id=context.session_id,
                round=context.round,
                strategy=self.name,
                strategy_version=self.version,
                outcome=ConsensusOutcome.INSUFFICIENT_EVIDENCE,
                blocking_critiques=blocking,
                degenerate_input=_degenerate(context),
                input_hash=input_hash,
                contributions=tuple(contributions),
                dissent=tuple(dissent),
                minority_report=tuple(minority),
                derivation=tuple(derivation),
            )

        # Stage 3: dominance — undominated set P.
        by_id = {alt.alternative_id: alt for alt in gate.rankable}
        values_by_alt = {
            a: _objective_value_lookup(a, context.objectives, context.objective_values)
            for a in stage2_ids
        }
        objective_ids = tuple(o.objective_id for o in context.objectives)
        pareto = _undominated(stage2_ids, values_by_alt, objective_ids, epsilon)
        derivation.append(
            _derivation(
                "stage3_dominance",
                "undominated set computed over declared objectives",
                3,
                {"objective_count": len(objective_ids)},
                {"undominated": [str(a) for a in pareto]},
            )
        )

        # Stage 4: conflict test — objectives declared conflicting and the
        # argmax differs for >= 2 objectives over P -> PARETO_SET, stop.
        declared_conflicting = any(o.conflicts_with for o in context.objectives)
        argmaxes: set[UUID] = set()
        for obj in context.objectives:
            best_alt: UUID | None = None
            best_val: Decimal | None = None
            for a in pareto:
                v = values_by_alt.get(a, {}).get(obj.objective_id)
                if v is not None and (best_val is None or v > best_val):
                    best_val = v
                    best_alt = a
            if best_alt is not None:
                argmaxes.add(best_alt)

        if declared_conflicting and len(argmaxes) >= 2 and len(pareto) > 1:
            scores = tuple(
                AlternativeScore(
                    alternative_id=a,
                    alternative_name=by_id[a].name,
                    rank=i + 1,
                    support=max(
                        Decimal("0"),
                        min(Decimal("1"), support_ev_by_alt.get(a, Decimal("0"))),
                    ),
                    value_score=None,
                    rank_score=None,
                    feasibility=FeasibilityStatus.SAT,
                    evidence_strength=evidence_totals.get(a),
                )
                for i, a in enumerate(pareto)
            )
            derivation.append(
                _derivation(
                    "stage4_conflict_test",
                    "objectives declared conflicting; frontier returned",
                    4,
                    {"argmax_count": len(argmaxes)},
                    {"frontier": [str(a) for a in pareto]},
                )
            )
            outcome = _blocking_gate_outcome(blocking, ConsensusOutcome.PARETO_SET)
            return ConsensusResult(
                result_id=uuid4(),
                session_id=context.session_id,
                round=context.round,
                strategy=self.name,
                strategy_version=self.version,
                outcome=outcome,
                scores=scores,
                pareto_set=pareto,
                blocking_critiques=blocking,
                degenerate_input=_degenerate(context),
                input_hash=input_hash,
                contributions=tuple(contributions),
                dissent=tuple(dissent),
                minority_report=tuple(minority),
                derivation=tuple(derivation),
            )

        # Stage 5: support order — rank P by support_ev(a).
        ranked_ids = sorted(
            pareto,
            key=lambda a: support_ev_by_alt.get(a, Decimal("0")),
            reverse=True,
        )
        scores = tuple(
            AlternativeScore(
                alternative_id=a,
                alternative_name=by_id[a].name,
                rank=i + 1,
                support=max(
                    Decimal("0"),
                    min(Decimal("1"), support_ev_by_alt.get(a, Decimal("0"))),
                ),
                value_score=None,
                rank_score=support_ev_by_alt.get(a),
                feasibility=(
                    FeasibilityStatus.UNKNOWN
                    if any(v.alternative_id == a for v in gate.unknown)
                    else FeasibilityStatus.SAT
                ),
                evidence_strength=evidence_totals.get(a),
            )
            for i, a in enumerate(ranked_ids)
        )
        derivation.append(
            _derivation(
                "stage5_support_order",
                "undominated set ranked by support_ev(a)",
                5,
                {},
                {str(s.alternative_id): str(s.support) for s in scores},
            )
        )

        # Stage 6: robustness — flip distance vs min_flip_distance.
        threshold_bound = False
        if len(scores) >= 2:
            flip_distance = abs(scores[0].support - scores[1].support)
            threshold_bound = flip_distance < min_flip_distance
        derivation.append(
            _derivation(
                "stage6_robustness",
                "flip distance compared against min_flip_distance",
                6,
                {"min_flip_distance": str(min_flip_distance)},
                {"threshold_bound": threshold_bound},
            )
        )

        # Stage 7: classify — as evidence_weighted, capped by UNKNOWN / blocking.
        leader = scores[0]
        leader_support = leader.support
        all_active_supportive = all(
            p.stance in ("SUPPORT", "ABSTAIN")
            for p in context.agent_positions
            if p.alternative_id == leader.alternative_id
        )
        if leader_support >= agreement_threshold and all_active_supportive:
            outcome = ConsensusOutcome.FULL_CONSENSUS
        elif leader_support >= partial_threshold:
            outcome = ConsensusOutcome.PARTIAL_CONSENSUS
        else:
            outcome = ConsensusOutcome.NO_CONSENSUS

        if any(v.alternative_id == leader.alternative_id for v in gate.unknown):
            outcome = ConsensusOutcome.CONDITIONAL_CONSENSUS

        outcome = _blocking_gate_outcome(blocking, outcome)

        selected = (
            leader.alternative_id
            if outcome
            in (
                ConsensusOutcome.FULL_CONSENSUS,
                ConsensusOutcome.PARTIAL_CONSENSUS,
                ConsensusOutcome.CONDITIONAL_CONSENSUS,
            )
            else None
        )

        conditions = (
            ("ranking is threshold-bound: flip distance below min_flip_distance",)
            if threshold_bound
            else ()
        )

        total_positions = len(context.agent_positions) or 1
        dissent_count = len([p for p in context.agent_positions if p.stance == "OPPOSE"])
        abstain_count = len([p for p in context.agent_positions if p.stance == "ABSTAIN"])

        derivation.append(
            _derivation(
                "stage7_classify",
                "outcome classified from thresholds and blocking critiques",
                7,
                {
                    "agreement_threshold": str(agreement_threshold),
                    "partial_threshold": str(partial_threshold),
                },
                {
                    "outcome": outcome.value,
                    "leader_support": str(leader_support),
                },
            )
        )

        return ConsensusResult(
            result_id=uuid4(),
            session_id=context.session_id,
            round=context.round,
            strategy=self.name,
            strategy_version=self.version,
            outcome=outcome,
            scores=scores,
            selected_alternative_id=selected,
            support=leader_support,
            dissent_ratio=Decimal(dissent_count) / Decimal(total_positions),
            abstention_ratio=Decimal(abstain_count) / Decimal(total_positions),
            blocking_critiques=blocking,
            conditions=conditions,
            degenerate_input=_degenerate(context),
            input_hash=input_hash,
            contributions=tuple(contributions),
            dissent=tuple(dissent),
            minority_report=tuple(minority),
            derivation=tuple(derivation),
        )

    def explain(self, result: ConsensusResult) -> ConsensusExplanation:
        return _empty_explanation(
            result,
            formula=(
                "Stage1 feasibility; Stage2 evidence floor; "
                "Stage3 dominance a<b iff (all k: v_k(b)>=v_k(a)) and "
                "(exists k: v_k(b)>v_k(a)+eps); Stage4 conflict test -> "
                "PARETO_SET; Stage5 rank by support_ev; Stage6 flip distance; "
                "Stage7 classify as evidence_weighted"
            ),
            weights={},
            thresholds={},
        )


# ---------------------------------------------------------------------------
# StrategyRegistry — T9-06, S-1, FR-608
# ---------------------------------------------------------------------------


class StrategyRegistry:
    """Immutable registry keyed by exact strategy name and version.

    S-1: a strategy is selectable only if its formal document exists.
    No document, no registration.
    """

    def __init__(
        self,
        strategies: Iterable[ConsensusStrategy],
        *,
        documented_names: frozenset[str] | None = None,
    ) -> None:
        registered: dict[tuple[str, str], ConsensusStrategy] = {}
        for strategy in strategies:
            name = _required(strategy.name, "strategy name")
            version = _required(strategy.version, "version")
            if documented_names is not None and name not in documented_names:
                raise ConsensusError(f"strategy {name!r} has no formal document (S-1, FR-608)")
            key = (name, version)
            if key in registered:
                raise ConsensusError(f"duplicate consensus strategy {name}@{version}")
            registered[key] = strategy
        self._strategies = registered

    def resolve(self, name: str, version: str) -> ConsensusStrategy:
        strategy = self._strategies.get((name, version))
        if strategy is None:
            raise ConsensusError(f"unknown consensus strategy {name}@{version}")
        return strategy

    def names(self) -> frozenset[str]:
        return frozenset(name for name, _version in self._strategies)


def _required(value: str, label: str) -> str:
    if not value:
        raise ConsensusError(f"{label} must be non-empty")
    return value


# ---------------------------------------------------------------------------
# ConsensusOrchestrator — T9-05, T9-06, S-2, S-3, FR-601..FR-608
# ---------------------------------------------------------------------------


class ConsensusOrchestrator:
    """Resolves a strategy, evaluates it, persists result + explanation.

    S-2: the session records the strategy and its parameter values.
    S-3: several strategies may run for comparison; results are never
    averaged into a meta-consensus — each call produces one independent
    `ConsensusRunRecord`.
    """

    def __init__(
        self,
        registry: StrategyRegistry,
        store: ConsensusResultStore,
    ) -> None:
        self._registry = registry
        self._store = store

    async def run(
        self,
        workspace_id: UUID,
        context: ConsensusContext,
    ) -> ConsensusResult:
        strategy = self._registry.resolve(
            context.strategy_config.strategy_name,
            context.strategy_config.strategy_version,
        )
        try:
            result = await strategy.evaluate(context)
        except ConsensusError:
            raise
        except Exception as exc:
            raise ConsensusError(
                f"strategy {strategy.name}@{strategy.version} failed: {exc}"
            ) from exc

        explanation = strategy.explain(result)

        record = ConsensusRunRecord(
            id=result.result_id,
            workspace_id=workspace_id,
            session_id=result.session_id,
            round=result.round,
            strategy=result.strategy,
            strategy_version=result.strategy_version,
            outcome=result.outcome,
            selected_alternative_id=result.selected_alternative_id,
            pareto_set=result.pareto_set,
            support=str(result.support) if result.support is not None else None,
            dissent=(str(result.dissent_ratio) if result.dissent_ratio is not None else None),
            abstention=(
                str(result.abstention_ratio) if result.abstention_ratio is not None else None
            ),
            coverage=None,
            constraint_report={
                "blocking_constraints": list(result.blocking_constraints),
                "blocking_critiques": [str(c) for c in result.blocking_critiques],
            },
            conditions=result.conditions,
            input_hash=result.input_hash,
            created_at=datetime.now(UTC),
        )

        await self._store.add_result(record)
        await self._store.add_explanation(workspace_id, result.result_id, explanation)

        return result
