"""The shipped, immutable metric catalogue — METRICS.md §4, task T13-01.

Every definition is transcribed from `docs/METRICS.md` and additionally carries its own
`inputs` and `interpretation` — the two fields the document's tables abbreviate — so the
code is the executable authority for those.  The catalogue is fixed at import time and
registers through the immutable `MetricCatalogue`; changing a metric is a new definition
version, never a mutation (NFR-019).
"""

from __future__ import annotations

from functools import lru_cache

from app.domain.metrics import MetricCatalogue
from app.ports.metrics import (
    MetricDefinition,
    MetricDimension,
    MetricDirection,
    MetricInputSpec,
    MetricRange,
    MetricRangeKind,
)

__all__ = ["build_metric_catalogue", "metric_catalogue"]


def _interval(
    *,
    lower: float | None = None,
    upper: float | None = None,
    unit: str | None = None,
    meaning: str,
) -> MetricRange:
    return MetricRange(
        kind=MetricRangeKind.INTERVAL,
        lower=lower,
        upper=upper,
        unit=unit,
        bounds_meaning=meaning,
    )


def _enum(meaning: str) -> MetricRange:
    return MetricRange(kind=MetricRangeKind.ENUM, bounds_meaning=meaning)


def _input(
    name: str,
    kind: str,
    fields: tuple[str, ...],
    description: str,
) -> MetricInputSpec:
    return MetricInputSpec(
        name=name,
        kind=kind,
        version="1",
        fields=fields,
        description=description,
    )


# ---------------------------------------------------------------------------
# 4.1 Evidence and provenance
# ---------------------------------------------------------------------------

_DEFINITIONS = (
    MetricDefinition(
        metric_id="ep-01",
        metric_version="1",
        dimension=MetricDimension.EVIDENCE,
        label="evidence coverage",
        formula="claims with >= 1 SUPPORTS / total claims",
        inputs=(
            _input(
                "claims",
                "claim",
                ("id", "kind", "status"),
                "all claims raised in the session at the point of computation",
            ),
            _input(
                "supports_edges",
                "claim_edge",
                ("source_claim_id", "edge_kind", "edge_state"),
                "SUPPORTS edges from claims or evidence toward claims",
            ),
        ),
        range=_interval(lower=0.0, upper=1.0, meaning="ratio of all claims to claims with support"),
        direction=MetricDirection.HIGHER_BETTER,
        interpretation=(
            "How much of the reasoning is tied to at least one piece of supporting evidence."
        ),
        caveats=("rises trivially if agents attach weak evidence; read with EP-03",),
    ),
    MetricDefinition(
        metric_id="ep-02",
        metric_version="1",
        dimension=MetricDimension.EVIDENCE,
        label="provenance completeness",
        formula="artifacts with an unbroken chain to SOURCE / total artifacts",
        inputs=(
            _input(
                "artifacts",
                "reasoning_artifact",
                ("id", "kind"),
                "all committed artifacts attributable in the session",
            ),
            _input(
                "artifact_links",
                "artifact_edge",
                ("source_id", "target_id", "edge_kind"),
                "provenance edges forming the chain toward source nodes",
            ),
            _input(
                "source_nodes",
                "source",
                ("id", "source_status"),
                "terminal SOURCE nodes, including UNATTRIBUTED ones",
            ),
        ),
        range=_interval(
            lower=0.0, upper=1.0, meaning="ratio of artifacts to those with a full chain"
        ),
        direction=MetricDirection.HIGHER_BETTER,
        interpretation=(
            "How much of the produced artifacts trace back, without gaps, to an original source."
        ),
        caveats=("a chain to an UNATTRIBUTED source is still a chain",),
    ),
    MetricDefinition(
        metric_id="ep-03",
        metric_version="1",
        dimension=MetricDimension.EVIDENCE,
        label="verified evidence ratio",
        formula="evidence in SOURCE_VERIFIED or CROSS_CHECKED / all evidence",
        inputs=(
            _input(
                "evidence",
                "evidence",
                ("id", "status"),
                "all evidence cited during the session",
            ),
            _input(
                "evidence_verifications",
                "evidence_verification",
                ("evidence_id", "verification_status"),
                "verification records with the documented verification status",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of all evidence to evidence independently verified",
        ),
        direction=MetricDirection.HIGHER_BETTER,
        interpretation=("Share of the cited evidence that was actually verified or cross-checked."),
        caveats=("low values are normal early in a session",),
    ),
    MetricDefinition(
        metric_id="ep-04",
        metric_version="1",
        dimension=MetricDimension.EVIDENCE,
        label="source independence",
        formula="mean distinct publishers per claim's support set",
        inputs=(
            _input(
                "claims",
                "claim",
                ("id",),
                "claims whose support sets are measured",
            ),
            _input(
                "claim_supports",
                "claim_edge",
                ("source_claim_id", "cited_source_id"),
                "support edges linking claims to cited sources",
            ),
            _input(
                "sources",
                "source",
                ("id", "publisher"),
                "cited sources with their publisher attribution",
            ),
        ),
        range=_interval(
            lower=0.0, meaning="unbounded above; larger means more independent publishers"
        ),
        direction=MetricDirection.HIGHER_BETTER,
        interpretation=("How many independent publishers stand behind a typical claim."),
        caveats=("citation laundering defeats it; see EP-05",),
    ),
    MetricDefinition(
        metric_id="ep-05",
        metric_version="1",
        dimension=MetricDimension.EVIDENCE,
        label="hallucinated source rate",
        formula="sustained HALLUCINATED_SOURCE critiques / cited sources",
        inputs=(
            _input(
                "critiques",
                "critique",
                ("id", "critique_kind", "status"),
                "critiques marked HALLUCINATED_SOURCE and sustained",
            ),
            _input(
                "cited_sources",
                "citation",
                ("id", "source_id"),
                "sources actually cited during the session",
            ),
        ),
        range=_interval(
            lower=0.0, upper=1.0, meaning="ratio of cited sources to sustained fabrications"
        ),
        direction=MetricDirection.LOWER_BETTER,
        interpretation="Share of cited sources that turned out to be made up.",
        caveats=("per-agent breakdown is the useful view",),
    ),
    MetricDefinition(
        metric_id="ep-06",
        metric_version="1",
        dimension=MetricDimension.EVIDENCE,
        label="evidence gap count",
        formula="open EVIDENCE_GAP critiques at terminal round",
        inputs=(
            _input(
                "critiques",
                "critique",
                ("id", "critique_kind", "state"),
                "EVIDENCE_GAP critiques still open at the terminal round",
            ),
            _input(
                "claims",
                "claim",
                ("id", "materiality"),
                "claims whose materiality weights the blocked count",
            ),
        ),
        range=_interval(lower=0.0, meaning="non-negative count of unanswered evidence requests"),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=("Number of evidence requests still unanswered when the session ended."),
        caveats=("count weighted by the materiality of the blocked claim",),
    ),
    # -----------------------------------------------------------------------
    # 4.2 Reasoning rigour
    # -----------------------------------------------------------------------
    MetricDefinition(
        metric_id="rr-01",
        metric_version="1",
        dimension=MetricDimension.RIGOUR,
        label="unsupported claim ratio",
        formula="claims with empty support and empty opposition / total claims",
        inputs=(
            _input(
                "claims",
                "claim",
                ("id", "kind"),
                "all claims, including hypotheses whose kind is recorded",
            ),
            _input(
                "support_edges",
                "claim_edge",
                ("source_claim_id", "edge_kind"),
                "SUPPORTS edges toward claims",
            ),
            _input(
                "opposition_edges",
                "claim_edge",
                ("source_claim_id", "edge_kind"),
                "ATTACKS or CONTRADICTS edges toward claims",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of all claims to claims with neither support nor opposition",
        ),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=("Share of claims with no support and no opposition at all."),
        caveats=("some unsupported claims are honest hypotheses; check claim kind",),
    ),
    MetricDefinition(
        metric_id="rr-02",
        metric_version="1",
        dimension=MetricDimension.RIGOUR,
        label="assumption depth",
        formula="mean assumption_closure size over alternatives",
        inputs=(
            _input(
                "alternatives",
                "alternative",
                ("id",),
                "alternatives whose assumption closures are measured",
            ),
            _input(
                "assumption_closure",
                "assumption_link",
                ("alternative_id", "assumption_id", "transitive"),
                "closure links between alternatives and the assumptions they depend on",
            ),
        ),
        range=_interval(
            lower=0.0, meaning="unbounded above; larger means deeper dependency closures"
        ),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=("How many explicit assumptions a typical alternative depends on."),
        caveats=("deep closures mean fragile conclusions, not wrong ones",),
    ),
    MetricDefinition(
        metric_id="rr-03",
        metric_version="1",
        dimension=MetricDimension.RIGOUR,
        label="inference validity rate",
        formula="inferences whose recorded rule passes the structural check / total inferences",
        inputs=(
            _input(
                "inferences",
                "inference",
                ("id", "rule_id"),
                "all recorded inference steps",
            ),
            _input(
                "inference_rules",
                "reasoning_rule",
                ("rule_id", "schema"),
                "the rule schemata each inference cites",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of all inferences to structurally valid ones",
        ),
        direction=MetricDirection.HIGHER_BETTER,
        interpretation=(
            "Share of inference steps whose rule actually conforms to the structural check."
        ),
        caveats=("structural validity is not soundness",),
    ),
    MetricDefinition(
        metric_id="rr-04",
        metric_version="1",
        dimension=MetricDimension.RIGOUR,
        label="contradiction density",
        formula="CONTRADICTS edges / claim pairs",
        inputs=(
            _input(
                "contradicts_edges",
                "claim_edge",
                ("source_claim_id", "target_claim_id", "edge_kind"),
                "CONTRADICTS edges between claim pairs",
            ),
            _input(
                "claims",
                "claim",
                ("id",),
                "claims forming the pair denominator",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of contradiction edges to claim pairs",
        ),
        direction=MetricDirection.NO_DIRECTION,
        interpretation=("Density of explicit contradictions between claims."),
        caveats=("low density can mean groupthink",),
    ),
    MetricDefinition(
        metric_id="rr-05",
        metric_version="1",
        dimension=MetricDimension.RIGOUR,
        label="formalization rate",
        formula="constraints with authoritative validation_status = VALIDATED / hard constraints",
        inputs=(
            _input(
                "constraints",
                "constraint",
                ("id", "constraint_kind"),
                "hard constraints eligible for formal validation",
            ),
            _input(
                "constraint_validations",
                "constraint_validation",
                ("constraint_id", "validation_status", "authoritative"),
                "authoritative validation records for constraints",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of hard constraints to authoritatively validated ones",
        ),
        direction=MetricDirection.HIGHER_BETTER,
        interpretation=("Share of hard constraints formally validated."),
        caveats=("only meaningful where formalization is possible",),
    ),
    MetricDefinition(
        metric_id="rr-06",
        metric_version="1",
        dimension=MetricDimension.RIGOUR,
        label="feasibility pass rate",
        formula="alternatives SAT / evaluated alternatives",
        inputs=(
            _input(
                "alternatives",
                "alternative",
                ("id",),
                "alternatives subjected to feasibility evaluation",
            ),
            _input(
                "feasibility_verdicts",
                "feasibility_evaluation",
                ("alternative_id", "verdict"),
                "recorded feasibility verdicts for alternatives",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of evaluated alternatives to feasible ones",
        ),
        direction=MetricDirection.NO_DIRECTION,
        interpretation=("Share of alternatives that passed feasibility."),
        caveats=("a low rate may mean honest constraints",),
    ),
    MetricDefinition(
        metric_id="rr-07",
        metric_version="1",
        dimension=MetricDimension.RIGOUR,
        label="solver unknown rate",
        formula="UNKNOWN evaluations / hard-constraint evaluations",
        inputs=(
            _input(
                "constraint_evaluations",
                "constraint_evaluation",
                ("constraint_id", "verdict"),
                "recorded solver verdicts over hard constraints",
            ),
            _input(
                "constraints",
                "constraint",
                ("id", "constraint_kind"),
                "the hard constraints whose evaluations form the denominator",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of constraint evaluations the solver could not decide",
        ),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=("Share of hard-constraint evaluations the solver could not decide."),
        caveats=("rising values signal over-ambitious rule sets",),
    ),
    # -----------------------------------------------------------------------
    # 4.3 Disagreement health
    # -----------------------------------------------------------------------
    MetricDefinition(
        metric_id="dh-01",
        metric_version="1",
        dimension=MetricDimension.DISAGREEMENT,
        label="initial disagreement",
        formula="propositions with a non-degenerate position vector after round 1",
        inputs=(
            _input(
                "propositions",
                "proposition",
                ("id",),
                "propositions put to the group in round 1",
            ),
            _input(
                "position_vectors",
                "position",
                ("proposition_id", "agent_id", "position"),
                "round-1 position vectors over agents",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of propositions with non-degenerate round-1 positions",
        ),
        direction=MetricDirection.HIGHER_BETTER,
        interpretation=("How much genuine disagreement existed right after the first round."),
        caveats=("zero disagreement across five agents is suspicious, not reassuring",),
    ),
    MetricDefinition(
        metric_id="dh-02",
        metric_version="1",
        dimension=MetricDimension.DISAGREEMENT,
        label="disagreement retention",
        formula=(
            "dissenting positions present in the final result / dissenting positions at round 2"
        ),
        inputs=(
            _input(
                "dissents",
                "dissent",
                ("agent_id", "proposition_id", "round_index"),
                "dissenting positions observed per round",
            ),
            _input(
                "results",
                "consensus_result",
                ("id", "round_index", "agent_positions"),
                "final results and their retained agent positions",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of round-2 dissent surviving into the final result",
        ),
        direction=MetricDirection.NO_DIRECTION,
        interpretation=("How much of the early disagreement remained in the final result."),
        caveats=("collapse to zero suggests herding; read with DH-05",),
    ),
    MetricDefinition(
        metric_id="dh-03",
        metric_version="1",
        dimension=MetricDimension.DISAGREEMENT,
        label="attack coverage",
        formula="claims with >= 1 ATTACKS edge / total claims",
        inputs=(
            _input(
                "claims",
                "claim",
                ("id",),
                "claims eligible for attack during the session",
            ),
            _input(
                "attack_edges",
                "claim_edge",
                ("target_claim_id", "edge_kind"),
                "ATTACKS edges directed at claims",
            ),
        ),
        range=_interval(
            lower=0.0, upper=1.0, meaning="ratio of claims to claims actually attacked"
        ),
        direction=MetricDirection.HIGHER_BETTER,
        interpretation=("Share of claims that actually came under attack."),
        caveats=(
            "the critic's own recall metric; a critic that attacks nothing fails its purpose",
        ),
    ),
    MetricDefinition(
        metric_id="dh-04",
        metric_version="1",
        dimension=MetricDimension.DISAGREEMENT,
        label="critique resolution rate",
        formula="critiques in a resolved state / total critiques",
        inputs=(
            _input(
                "critiques",
                "critique",
                ("id", "state", "resolution_warrant"),
                "critiques and their resolution states and warrants",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of all critiques to those in a resolved state",
        ),
        direction=MetricDirection.HIGHER_BETTER,
        interpretation=("Share of critiques that reached a resolved state."),
        caveats=("REJECT_WITH_JUSTIFICATION counts as resolved only with a warrant",),
    ),
    MetricDefinition(
        metric_id="dh-05",
        metric_version="1",
        dimension=MetricDimension.DISAGREEMENT,
        label="herding index",
        formula=(
            "share of round-1 positions that flip toward the majority with no new evidence edge"
        ),
        inputs=(
            _input(
                "positions",
                "position",
                ("agent_id", "proposition_id", "round_index", "position"),
                "round-1 positions eligible to flip",
            ),
            _input(
                "evidence_edges",
                "claim_edge",
                ("source_claim_id", "edge_kind"),
                "evidence edges that would justify a flip if new",
            ),
            _input(
                "majority_flips",
                "position_change",
                ("from_value", "to_value", "majority_direction", "new_evidence_edge"),
                "recorded flips toward the majority with their evidence attribution",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of round-1 positions to unjustified majority flips",
        ),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=(
            "Share of early positions that flipped toward the majority without new evidence."
        ),
        caveats=("the most important anti-sycophancy signal",),
    ),
    MetricDefinition(
        metric_id="dh-06",
        metric_version="1",
        dimension=MetricDimension.DISAGREEMENT,
        label="revision quality",
        formula="flips accompanied by a RESPONDS_TO edge / all flips",
        inputs=(
            _input(
                "position_flips",
                "position_change",
                ("from_value", "to_value"),
                "all recorded position flips",
            ),
            _input(
                "responds_to_edges",
                "claim_edge",
                ("source_claim_id", "target_claim_id", "edge_kind"),
                "RESPONDS_TO edges accompanying flips",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of flips to those with an accompanying response edge",
        ),
        direction=MetricDirection.HIGHER_BETTER,
        interpretation=("Share of position flips that were backed by an explicit response edge."),
        caveats=("distinguishes persuasion from capitulation",),
    ),
    MetricDefinition(
        metric_id="dh-07",
        metric_version="1",
        dimension=MetricDimension.DISAGREEMENT,
        label="minority report substance",
        formula="distinct warrants offered by dissenters",
        inputs=(
            _input(
                "dissents",
                "dissent",
                ("warrant", "agent_id"),
                "dissent records with their warrants",
            ),
        ),
        range=_interval(lower=1.0, meaning="at least one distinct warrant when dissent exists"),
        direction=MetricDirection.NO_DIRECTION,
        interpretation=("Number of distinct warrants minority voices offered."),
        caveats=("descriptive; rendered verbatim",),
    ),
    # -----------------------------------------------------------------------
    # 4.4 Consensus quality
    # -----------------------------------------------------------------------
    MetricDefinition(
        metric_id="cq-01",
        metric_version="1",
        dimension=MetricDimension.CONSENSUS,
        label="support margin",
        formula="top alternative support - runner-up support",
        inputs=(
            _input(
                "alternatives",
                "alternative",
                ("id",),
                "alternatives in the terminal ranking",
            ),
            _input(
                "support_scores",
                "alternative_score",
                ("alternative_id", "support"),
                "final support scores per alternative",
            ),
        ),
        range=_interval(
            lower=0.0, meaning="difference between the top and runner-up support scores"
        ),
        direction=MetricDirection.HIGHER_BETTER,
        interpretation=("How much the leading alternative outranks the runner-up."),
        caveats=("meaningless when the outcome is PARETO_SET",),
    ),
    MetricDefinition(
        metric_id="cq-02",
        metric_version="1",
        dimension=MetricDimension.CONSENSUS,
        label="outcome class",
        formula="ConsensusResult.outcome",
        inputs=(
            _input(
                "consensus_result",
                "consensus_result",
                ("id", "outcome"),
                "the terminal consensus result and its outcome class",
            ),
        ),
        range=_enum(meaning="the declared outcome class, e.g. FULL_CONSENSUS"),
        direction=MetricDirection.NO_DIRECTION,
        interpretation="The declared class of the consensus outcome.",
        caveats=("never reduced to a number",),
    ),
    MetricDefinition(
        metric_id="cq-03",
        metric_version="1",
        dimension=MetricDimension.CONSENSUS,
        label="flip distance",
        formula="smallest input perturbation that changes the ranking",
        inputs=(
            _input(
                "input_perturbations",
                "sensitivity_sweep",
                ("magnitude", "ranking_changed"),
                "recorded sensitivity sweeps over the inputs",
            ),
            _input(
                "ranking_sensitivities",
                "ranking",
                ("run_id", "ordering"),
                "rankings produced per perturbation magnitude",
            ),
        ),
        range=_interval(lower=0.0, meaning="unbounded above; larger means a more robust ranking"),
        direction=MetricDirection.HIGHER_BETTER,
        interpretation=("How much the inputs would need to change before the ranking flips."),
        caveats=("computed by sensitivity sweep; the honesty metric of the ranking",),
    ),
    MetricDefinition(
        metric_id="cq-04",
        metric_version="1",
        dimension=MetricDimension.CONSENSUS,
        label="abstention rate",
        formula="ABSTAIN turns / expected turns",
        inputs=(
            _input(
                "turns",
                "turn",
                ("agent_id", "round_index"),
                "turns in which each agent was expected to participate",
            ),
            _input(
                "votes",
                "turn_vote",
                ("turn_id", "vote_kind"),
                "recorded votes, including explicit ABSTAIN",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of expected turns to explicit abstentions",
        ),
        direction=MetricDirection.NO_DIRECTION,
        interpretation=("Share of turns in which an agent abstained."),
        caveats=("high abstention with high consensus means an under-informed room",),
    ),
    MetricDefinition(
        metric_id="cq-05",
        metric_version="1",
        dimension=MetricDimension.CONSENSUS,
        label="blocking critique carry-over",
        formula="unresolved blocking critiques at terminal round",
        inputs=(
            _input(
                "critiques",
                "critique",
                ("id", "blocking", "state"),
                "critiques marked blocking and their terminal states",
            ),
        ),
        range=_interval(lower=0.0, meaning="non-negative count of unresolved blocking critiques"),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=("Number of blocking critiques still unresolved at the end."),
        caveats=("each must appear in the explanation (FR-504)",),
    ),
    MetricDefinition(
        metric_id="cq-06",
        metric_version="1",
        dimension=MetricDimension.CONSENSUS,
        label="strategy divergence",
        formula="pairwise rank correlation across strategies run on the same inputs",
        inputs=(
            _input(
                "strategy_runs",
                "consensus_run",
                ("strategy_name", "inputs_hash"),
                "runs of distinct strategies over identical inputs",
            ),
            _input(
                "rankings",
                "ranking",
                ("run_id", "ordering"),
                "the ranking each strategy produced",
            ),
        ),
        range=_interval(
            lower=-1.0,
            upper=1.0,
            meaning="pairwise rank correlation, -1 to 1",
        ),
        direction=MetricDirection.NO_DIRECTION,
        interpretation=("How much consensus strategies disagree on the same inputs."),
        caveats=("low correlation is a finding, not an error",),
    ),
    # -----------------------------------------------------------------------
    # 4.5 Robustness
    # -----------------------------------------------------------------------
    MetricDefinition(
        metric_id="rb-01",
        metric_version="1",
        dimension=MetricDimension.ROBUSTNESS,
        label="ranking stability",
        formula="Kendall tau of the ranking across >= 3 seeds or replay modes",
        inputs=(
            _input(
                "ranking_runs",
                "ranking_run",
                ("seed_or_mode", "run_id"),
                "ranking runs across seeds or replay modes",
            ),
            _input(
                "rankings",
                "ranking",
                ("run_id", "ordering"),
                "the ranking produced per run",
            ),
        ),
        range=_interval(
            lower=-1.0,
            upper=1.0,
            meaning="mean pairwise Kendall tau, -1 to 1",
        ),
        direction=MetricDirection.HIGHER_BETTER,
        interpretation=("How stable the ranking is across seeds or replay modes."),
        caveats=("requires the experiment harness",),
    ),
    MetricDefinition(
        metric_id="rb-02",
        metric_version="1",
        dimension=MetricDimension.ROBUSTNESS,
        label="assumption sensitivity",
        formula="share of the recommendation's support that depends on one assumption",
        inputs=(
            _input(
                "support_provenance",
                "recommendation_support",
                ("assumption_id", "support_share"),
                "the support attributed to each assumption",
            ),
            _input(
                "assumptions",
                "assumption",
                ("id",),
                "assumptions the recommendation's support depends on",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="share of support resting on a single assumption",
        ),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=("Share of the recommendation's support resting on one assumption."),
        caveats=("single-point-of-failure detector",),
    ),
    MetricDefinition(
        metric_id="rb-03",
        metric_version="1",
        dimension=MetricDimension.ROBUSTNESS,
        label="model divergence",
        formula="spread of simulated outcomes across engines",
        inputs=(
            _input(
                "simulations",
                "simulation",
                ("engine_id", "outcome_value"),
                "simulated outcomes per engine",
            ),
            _input(
                "intervals",
                "simulation_interval",
                ("engine_id", "interval_low", "interval_high"),
                "the intervals each engine attached to its outcome",
            ),
        ),
        range=_interval(lower=0.0, meaning="non-negative spread across engines in outcome units"),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=("How far simulated outcomes diverge across engines."),
        caveats=("large spread with narrow intervals means over-confidence",),
    ),
    MetricDefinition(
        metric_id="rb-04",
        metric_version="1",
        dimension=MetricDimension.ROBUSTNESS,
        label="retrieval robustness",
        formula="share of cited chunks still retrieved under paraphrased queries",
        inputs=(
            _input(
                "cited_chunks",
                "chunk",
                ("id",),
                "chunks cited by the session",
            ),
            _input(
                "retrieval_reruns",
                "retrieval_evaluation",
                ("chunk_id", "paraphrase_id", "retrieved"),
                "paraphrased-query reruns of retrieval per cited chunk",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of cited chunks to those still retrieved under paraphrase",
        ),
        direction=MetricDirection.HIGHER_BETTER,
        interpretation=("Share of cited chunks still retrieved under paraphrased queries."),
        caveats=("proxy for recall without ground truth",),
    ),
    MetricDefinition(
        metric_id="rb-05",
        metric_version="1",
        dimension=MetricDimension.ROBUSTNESS,
        label="degraded-state frequency",
        formula="count of RAG_FAILED, provider outage and solver timeout events",
        inputs=(
            _input(
                "infra_events",
                "infrastructure_event",
                ("event_kind", "severity"),
                "degradation events of the documented kinds",
            ),
        ),
        range=_interval(lower=0.0, meaning="non-negative count of degradation events"),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=("How often the pipeline degraded mid-session."),
        caveats=("a session that never degraded was probably not stressed",),
    ),
    # -----------------------------------------------------------------------
    # 4.6 Cost and efficiency
    # -----------------------------------------------------------------------
    MetricDefinition(
        metric_id="ce-01",
        metric_version="1",
        dimension=MetricDimension.COST,
        label="tokens per committed artifact",
        formula="total tokens / artifacts committed",
        inputs=(
            _input(
                "token_usage",
                "llm_usage",
                ("request_id", "input_tokens", "output_tokens"),
                "token counts per LLM request of the session",
            ),
            _input(
                "artifacts_committed",
                "reasoning_artifact",
                ("id", "kind"),
                "artifacts actually committed during the session",
            ),
        ),
        range=_interval(lower=0.0, meaning="mean tokens spent per committed artifact"),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=("Average tokens spent per artifact actually committed."),
        caveats=("cheap artifacts are easy to produce; read with RR-01",),
    ),
    MetricDefinition(
        metric_id="ce-02",
        metric_version="1",
        dimension=MetricDimension.COST,
        label="rounds to terminal",
        formula="rounds consumed",
        inputs=(
            _input(
                "session",
                "consensus_session",
                ("round_count", "termination_reason"),
                "the session's round count and termination reason",
            ),
        ),
        range=_interval(lower=1.0, meaning="rounds consumed, at least one"),
        direction=MetricDirection.NO_DIRECTION,
        interpretation=("How many rounds the session consumed."),
        caveats=("budget exhaustion is a termination reason, not efficiency",),
    ),
    MetricDefinition(
        metric_id="ce-03",
        metric_version="1",
        dimension=MetricDimension.COST,
        label="cost per session",
        formula="sum of provider cost estimates",
        inputs=(
            _input(
                "provider_cost_estimates",
                "cost_estimate",
                ("provider", "estimated_cost"),
                "provider cost estimates for the session",
            ),
        ),
        range=_interval(lower=0.0, meaning="non-negative total estimated cost in currency units"),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=("Total estimated cost of the session."),
        caveats=("compare only within a fixed configuration",),
    ),
    MetricDefinition(
        metric_id="ce-04",
        metric_version="1",
        dimension=MetricDimension.COST,
        label="p95 read latency",
        formula="API read latency excluding LLM time",
        inputs=(
            _input(
                "api_latencies",
                "latency_sample",
                ("operation", "latency_ms", "includes_llm"),
                "read-operation latency samples excluding LLM time",
            ),
        ),
        range=_interval(lower=0.0, unit="ms", meaning="95th percentile latency in milliseconds"),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=("95th percentile read latency, excluding LLM time."),
        caveats=("NFR-007 target 300 ms",),
    ),
    MetricDefinition(
        metric_id="ce-05",
        metric_version="1",
        dimension=MetricDimension.COST,
        label="event delivery lag",
        formula="SSE delivery time - ledger commit time",
        inputs=(
            _input(
                "sse_delivery",
                "delivery_sample",
                ("event_id", "delivered_at"),
                "real-time delivery timestamps per event",
            ),
            _input(
                "ledger_commits",
                "ledger_commit",
                ("event_id", "committed_at"),
                "ledger commit timestamps per event",
            ),
        ),
        range=_interval(lower=0.0, unit="ms", meaning="delivery minus commit lag in milliseconds"),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=("Delay between a ledger commit and its delivery to the UI."),
        caveats=("NFR-007 target 1 s",),
    ),
    # -----------------------------------------------------------------------
    # 4.7 Human oversight
    # -----------------------------------------------------------------------
    MetricDefinition(
        metric_id="ho-01",
        metric_version="1",
        dimension=MetricDimension.OVERSIGHT,
        label="intervention rate",
        formula="human events / total events",
        inputs=(
            _input(
                "events",
                "session_event",
                ("id", "actor"),
                "all session events with their actor attribution",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of all events to human-produced events",
        ),
        direction=MetricDirection.NO_DIRECTION,
        interpretation=("Share of events produced by a human."),
        caveats=("both extremes are worth explaining",),
    ),
    MetricDefinition(
        metric_id="ho-02",
        metric_version="1",
        dimension=MetricDimension.OVERSIGHT,
        label="override rate",
        formula="overridden recommendations / recommendations",
        inputs=(
            _input(
                "recommendations",
                "recommendation",
                ("id",),
                "recommendations produced by the session",
            ),
            _input(
                "overrides",
                "human_action",
                ("recommendation_id", "action"),
                "human override actions over recommendations",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of recommendations to those overridden by a human",
        ),
        direction=MetricDirection.NO_DIRECTION,
        interpretation=("Share of recommendations a human overrode."),
        caveats=("every override stays visible downstream (FR-803)",),
    ),
    MetricDefinition(
        metric_id="ho-03",
        metric_version="1",
        dimension=MetricDimension.OVERSIGHT,
        label="explanation engagement",
        formula="drill-downs per recommendation view",
        inputs=(
            _input(
                "drilldown_events",
                "ui_action",
                ("recommendation_id", "action"),
                "explanation drill-down actions per recommendation",
            ),
            _input(
                "recommendation_views",
                "ui_action",
                ("recommendation_id", "action"),
                "recommendation view events",
            ),
        ),
        range=_interval(lower=0.0, meaning="mean drill-downs per recommendation view"),
        direction=MetricDirection.NO_DIRECTION,
        interpretation=("Average number of explanation drill-downs per recommendation view."),
        caveats=("a usage signal, not a quality signal",),
    ),
    MetricDefinition(
        metric_id="ho-04",
        metric_version="1",
        dimension=MetricDimension.OVERSIGHT,
        label="unexamined acceptance",
        formula="recommendations accepted with zero provenance traversal",
        inputs=(
            _input(
                "accepted_recommendations",
                "recommendation",
                ("id", "accepted"),
                "recommendations accepted by a human",
            ),
            _input(
                "provenance_traversals",
                "ui_action",
                ("recommendation_id", "traversed"),
                "provenance traversal actions over recommendations",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of accepted recommendations to those never examined",
        ),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=("Share of recommendations accepted without any provenance traversal."),
        caveats=("the rubber-stamp detector",),
    ),
    # -----------------------------------------------------------------------
    # 4.8 Calibration
    # -----------------------------------------------------------------------
    MetricDefinition(
        metric_id="ca-01",
        metric_version="1",
        dimension=MetricDimension.CALIBRATION,
        label="calibration error",
        formula="mean signed gap between declared confidence and outcome frequency, per agent",
        inputs=(
            _input(
                "calibration_gaps",
                "calibration_sample",
                ("agent_id", "declared_confidence", "outcome_frequency"),
                "per-agent pairs of declared confidence and observed outcome frequency",
            ),
        ),
        range=_interval(
            lower=-1.0,
            upper=1.0,
            meaning="mean signed gap, -1 to 1",
        ),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=(
            "Signed gap between declared confidence and observed outcome frequency, per agent."
        ),
        caveats=("needs checkable outcomes; NOT_APPLICABLE in most MVP sessions",),
    ),
    MetricDefinition(
        metric_id="ca-02",
        metric_version="1",
        dimension=MetricDimension.CALIBRATION,
        label="Brier score",
        formula="mean squared error between declared probability and realized outcome",
        inputs=(
            _input(
                "probability_declarations",
                "probability_declaration",
                ("declared_probability", "event_id"),
                "declared probabilities for checkable events",
            ),
            _input(
                "realized_outcomes",
                "checkable_outcome",
                ("event_id", "occurred"),
                "realized outcomes for the declared events",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=2.0,
            meaning="mean squared probability error, 0 to 2",
        ),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=("Mean squared error between declared probabilities and realized outcomes."),
        caveats=(
            "applies only where a genuine probability was declared, never to confidence (CF-2)",
        ),
    ),
    MetricDefinition(
        metric_id="ca-03",
        metric_version="1",
        dimension=MetricDimension.CALIBRATION,
        label="overreach rate",
        formula="high-confidence claims with provenance_completeness = 0",
        inputs=(
            _input(
                "high_confidence_claims",
                "claim",
                ("id", "confidence"),
                "claims declared with high confidence",
            ),
            _input(
                "provenance_completeness",
                "claim_provenance",
                ("claim_id", "completeness"),
                "recorded provenance completeness per claim",
            ),
        ),
        range=_interval(
            lower=0.0,
            upper=1.0,
            meaning="ratio of high-confidence claims to those without provenance",
        ),
        direction=MetricDirection.LOWER_BETTER,
        interpretation=("Share of high-confidence claims having zero provenance."),
        caveats=("the practical MVP proxy for CA-01",),
    ),
)


# trace: FR-901, FR-902, NFR-019
def build_metric_catalogue() -> MetricCatalogue:
    """Register the shipped catalogue; duplicates and emptiness fail loudly."""
    return MetricCatalogue(_DEFINITIONS)


@lru_cache(maxsize=1)
def metric_catalogue() -> MetricCatalogue:
    """The process-wide immutable catalogue, built once."""
    return build_metric_catalogue()
