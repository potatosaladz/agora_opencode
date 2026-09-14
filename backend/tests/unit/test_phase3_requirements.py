"""Requirement-level acceptance properties for the frozen Phase 3 model."""

from itertools import permutations
from uuid import UUID

import pytest

from app.domain import reasoning as r
from tests.traceability import req
from tests.unit.test_reasoning import U, artifact_data, payloads


@req("FR-312")
def test_fr301_fr312_closed_taxonomy_distinguishes_semantic_categories() -> None:
    artifacts = {kind: r.validate_artifact(artifact_data(kind)) for kind in r.ArtifactKind}

    assert len(artifacts) == 14
    assert isinstance(artifacts[r.ArtifactKind.FACT].payload, r.FactPayload)
    assert isinstance(artifacts[r.ArtifactKind.CLAIM].payload, r.ClaimPayload)
    assert isinstance(artifacts[r.ArtifactKind.ASSUMPTION].payload, r.AssumptionPayload)
    assert isinstance(artifacts[r.ArtifactKind.INFERENCE].payload, r.InferencePayload)
    assert isinstance(artifacts[r.ArtifactKind.POSITION].payload, r.PositionPayload)
    hypothesis = r.ClaimPayload(
        statement="A testable hypothesis",
        claim_type=r.ClaimType.HYPOTHESIS,
        direction=r.Bearing.SUPPORTS,
        strength=r.Strength.WEAK,
        supporting_evidence_ids=(),
        opposing_evidence_ids=(),
        review_status=r.ReviewStatus.PROPOSED,
    )
    assert hypothesis.claim_type is r.ClaimType.HYPOTHESIS


@req("FR-304")
def test_fr304_claim_always_declares_both_evidence_directions() -> None:
    claim = payloads()[r.ArtifactKind.CLAIM]
    assert isinstance(claim, r.ClaimPayload)
    assert claim.model_fields_set >= {
        "supporting_evidence_ids",
        "opposing_evidence_ids",
    }


@req("FR-307")
def test_fr307_objective_conflicts_are_order_independent() -> None:
    for ordering in permutations((U, UUID(int=2), UUID(int=3))):
        objective = r.ObjectivePayload(
            name="Balance outcomes",
            objective_type="UTILITY",
            direction="MAXIMIZE",
            weight="0.5",
            weight_rationale="Declared trade-off",
            time_horizon="one year",
            conflicts_with_ids=ordering,
        )
        assert set(objective.conflicts_with_ids) == set(ordering)


@req("FR-308")
@pytest.mark.parametrize("constraint_type", list(r.ConstraintType))
def test_fr308_every_constraint_class_requires_machine_expression(
    constraint_type: r.ConstraintType,
) -> None:
    constraint = r.ConstraintPayload(
        name="Budget boundary",
        statement="Cost must remain bounded",
        constraint_type=constraint_type,
        category="BUDGET",
        evaluation_expression=r.FormalExpression(
            language="json-logic", ast={"<=": [{"var": "cost"}, "10"]}
        ),
        formal_status="VALIDATED",
    )
    assert constraint.evaluation_expression.ast


@req("FR-309")
@pytest.mark.parametrize("uncertainty_type", list(r.UncertaintyType))
def test_fr309_every_uncertainty_type_is_representable(
    uncertainty_type: r.UncertaintyType,
) -> None:
    uncertainty = r.IntervalUncertaintyPayload(
        target_id=U,
        uncertainty_type=uncertainty_type,
        representation="INTERVAL",
        drivers=("measurement",),
        lower="0",
        upper="1",
        unit="ratio",
    )
    assert uncertainty.uncertainty_type is uncertainty_type


@req("FR-310")
def test_fr310_risk_requires_probability_impact_uncertainty_and_objectives() -> None:
    risk = payloads()[r.ArtifactKind.RISK]
    assert isinstance(risk, r.RiskPayload)
    assert risk.model_fields_set >= {
        "probability",
        "impact",
        "uncertainty_id",
        "affected_objective_ids",
    }


@req("FR-311")
def test_fr311_assumption_is_attributable_and_critique_can_attack_it() -> None:
    assumption = r.validate_artifact(artifact_data(r.ArtifactKind.ASSUMPTION))
    critique = r.CritiquePayload(
        target_id=assumption.id,
        critique_type=r.CritiqueType.EVIDENCE_GAP,
        severity=r.Severity.HIGH,
        argument="Basis needs independent support",
        resolution=r.Resolution.OPEN,
    )

    assert assumption.owner_actor_id == U
    assert isinstance(assumption.payload, r.AssumptionPayload)
    assert assumption.payload.challengeable is True
    assert critique.target_id == assumption.id
