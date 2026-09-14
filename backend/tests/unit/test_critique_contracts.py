"""T7-01 strict Critic assignment, output, and response contracts."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.agent_activity import ArtifactProposal, ProposalBundle
from app.domain.critique import (
    ArtifactRevisionProposal,
    CritiqueAssignment,
    CritiqueResponseDisposition,
    CritiqueResponseProposal,
    validate_critic_bundle,
)
from app.domain.reasoning import ArtifactKind, Confidence, CritiqueType, Resolution, Severity
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{index:012d}") for index in range(1, 40))


def assignment(**changes: Any) -> CritiqueAssignment:
    values: dict[str, Any] = {
        "protocol_version": "1.0",
        "kind": "critique_assignment",
        "workspace_id": U[0],
        "session_id": U[1],
        "critic_definition_id": U[2],
        "critic_definition_version": 3,
        "turn_id": U[3],
        "correlation_id": U[4],
        "causation_id": U[5],
        "round": 2,
        "target_artifact_ids": tuple(U[10:20]),
        "schema_version": 1,
    }
    values.update(changes)
    return CritiqueAssignment.model_validate(values)


def critique(
    target_id: UUID = U[10],
    critique_type: CritiqueType | str = CritiqueType.EVIDENCE_GAP,
    *,
    resolution: Resolution | str = Resolution.OPEN,
    argument: str = "The target has no supporting evidence.",
) -> ArtifactProposal:
    return ArtifactProposal.model_validate(
        {
            "op": "propose",
            "kind": ArtifactKind.CRITIQUE,
            "payload": {
                "target_id": target_id,
                "critique_type": critique_type,
                "severity": Severity.HIGH,
                "argument": argument,
                "resolution": resolution,
            },
        }
    )


def bundle(*artifacts: ArtifactProposal, **changes: Any) -> ProposalBundle:
    values: dict[str, Any] = {
        "protocol_version": "1.0",
        "kind": "proposal_bundle",
        "turn_id": U[3],
        "artifacts": artifacts,
        "evidence_requests": (),
        "simulation_request_refs": (),
        "self_reported_limits": ("Automated criticism may miss domain-specific defects.",),
    }
    values.update(changes)
    return ProposalBundle.model_validate(values)


def revision() -> ArtifactRevisionProposal:
    return ArtifactRevisionProposal(
        op="propose",
        kind=ArtifactKind.CLAIM,
        payload={
            "statement": "Revised claim with explicit evidentiary limits.",
            "claim_type": "FACTUAL",
            "direction": "SUPPORTS",
            "strength": "WEAK",
            "supporting_evidence_ids": [],
            "opposing_evidence_ids": [],
            "review_status": "CONTESTED",
        },
    )


def response(
    disposition: CritiqueResponseDisposition,
    **changes: Any,
) -> CritiqueResponseProposal:
    effects: dict[CritiqueResponseDisposition, dict[str, object]] = {
        CritiqueResponseDisposition.ACCEPT: {},
        CritiqueResponseDisposition.PARTIALLY_ACCEPT: {
            "remaining_issue": "The magnitude remains unsupported."
        },
        CritiqueResponseDisposition.REJECT_WITH_JUSTIFICATION: {"warrant_artifact_ids": (U[20],)},
        CritiqueResponseDisposition.REVISE: {"proposed_revision": revision()},
        CritiqueResponseDisposition.REQUEST_EVIDENCE: {
            "evidence_query": "Find primary evidence for the stated magnitude."
        },
        CritiqueResponseDisposition.REQUEST_SIMULATION: {
            "simulation_request_ref": "simulation-request:transport-cost-v1"
        },
        CritiqueResponseDisposition.ABSTAIN: {},
    }
    values: dict[str, Any] = {
        "protocol_version": "1.0",
        "kind": "critique_response",
        "response_id": U[6],
        "workspace_id": U[0],
        "session_id": U[1],
        "responding_definition_id": U[7],
        "responding_definition_version": 4,
        "turn_id": U[8],
        "correlation_id": U[4],
        "causation_id": U[9],
        "round": 2,
        "critique_id": U[21],
        "critique_version": 1,
        "target_artifact_id": U[10],
        "target_artifact_version": 1,
        "disposition": disposition,
        "rationale": "Explicit response rationale.",
        "schema_version": 1,
        **effects[disposition],
    }
    values.update(changes)
    return CritiqueResponseProposal.model_validate(values)


@req("FR-501")
def test_fr501_exact_taxonomy_and_fr503_exact_response_vocabulary() -> None:
    assert {value.value for value in CritiqueType} == {
        "EVIDENCE_GAP",
        "LOGICAL_FALLACY",
        "HALLUCINATED_SOURCE",
        "MEASUREMENT_ERROR",
        "MODEL_MISUSE",
        "CONSTRAINT_IGNORED",
        "CONFLICT_OF_INTEREST",
        "ALTERNATIVE_OMITTED",
        "UNCERTAINTY_UNDERSTATED",
        "CAUSAL_OVERCLAIM",
    }
    assert {value.value for value in CritiqueResponseDisposition} == {
        "ACCEPT",
        "PARTIALLY_ACCEPT",
        "REJECT_WITH_JUSTIFICATION",
        "REVISE",
        "REQUEST_EVIDENCE",
        "REQUEST_SIMULATION",
        "ABSTAIN",
    }


@req("FR-502")
@pytest.mark.parametrize("critique_type", list(CritiqueType))
def test_critic_bundle_accepts_every_fr501_type_as_new_open_critique(
    critique_type: CritiqueType,
) -> None:
    candidate = bundle(critique(U[10], critique_type))

    assert validate_critic_bundle(candidate, assignment()) is candidate


@req("FR-501")
@pytest.mark.parametrize("alias", ["UNSUPPORTED_CLAIM", "IGNORED_CONSTRAINT", "FALSE_DILEMMA"])
def test_roadmap_aliases_have_no_contract_status(alias: str) -> None:
    with pytest.raises(ValidationError, match="critique_type"):
        critique(critique_type=alias)


@req("FR-501", "FR-502")
def test_assignment_is_closed_frozen_versioned_and_has_unique_targets() -> None:
    value = assignment()
    with pytest.raises(ValidationError):
        value.round = 3  # type: ignore[misc]
    for changes in (
        {"target_artifact_ids": ()},
        {"target_artifact_ids": (U[10], U[10])},
        {"schema_version": 2},
        {"mutation": {"status": "RESOLVED"}},
    ):
        with pytest.raises(ValidationError):
            assignment(**changes)


@req("FR-502")
@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (bundle(), None),
        (bundle(critique(U[20])), "not in the coordinator assignment"),
        (bundle(critique(), critique()), "exact duplicate attack"),
        (bundle(critique(resolution=Resolution.RESOLVED)), "must have OPEN resolution"),
        (bundle(critique(), evidence_requests=("find support",)), "must not carry"),
        (bundle(critique(), simulation_request_refs=("sim:1",)), "must not carry"),
        (bundle(critique(), turn_id=U[30]), "turn_id does not match"),
    ],
)
def test_critic_bundle_rejects_unassigned_duplicate_resolved_or_request_bearing_output(
    candidate: ProposalBundle, message: str | None
) -> None:
    if message is None:
        assert validate_critic_bundle(candidate, assignment()) is candidate
    else:
        with pytest.raises(ValueError, match=message):
            validate_critic_bundle(candidate, assignment())


@req("FR-501", "FR-502")
def test_critic_bundle_rejects_non_critique_and_confidence() -> None:
    with pytest.raises(ValueError, match="only CRITIQUE"):
        validate_critic_bundle(
            bundle(ArtifactProposal.model_validate(revision().model_dump())), assignment()
        )
    confident = critique().model_copy(
        update={
            "confidence": Confidence(
                kind="subjective",
                value="0.5",
                meaning="not part of the Critique contract",
                basis_artifact_ids=(),
            )
        }
    )
    with pytest.raises(ValueError, match="must not carry"):
        validate_critic_bundle(bundle(confident), assignment())


@req("FR-501", "FR-502")
@pytest.mark.parametrize("disposition", list(CritiqueResponseDisposition))
def test_fr503_every_response_disposition_has_one_strict_valid_shape(
    disposition: CritiqueResponseDisposition,
) -> None:
    value = response(disposition)

    assert value.disposition is disposition
    with pytest.raises(ValidationError):
        value.rationale = "changed"  # type: ignore[misc]


@req("FR-501", "FR-502")
@pytest.mark.parametrize(
    ("disposition", "changes", "message"),
    [
        (CritiqueResponseDisposition.PARTIALLY_ACCEPT, {"remaining_issue": None}, "requires"),
        (
            CritiqueResponseDisposition.REJECT_WITH_JUSTIFICATION,
            {"warrant_artifact_ids": ()},
            "requires",
        ),
        (CritiqueResponseDisposition.REVISE, {"proposed_revision": None}, "requires"),
        (CritiqueResponseDisposition.REQUEST_EVIDENCE, {"evidence_query": None}, "requires"),
        (
            CritiqueResponseDisposition.REQUEST_SIMULATION,
            {"simulation_request_ref": None},
            "requires",
        ),
        (
            CritiqueResponseDisposition.ACCEPT,
            {"warrant_artifact_ids": (U[20],)},
            "does not permit",
        ),
        (
            CritiqueResponseDisposition.ABSTAIN,
            {"evidence_query": "hidden request"},
            "does not permit",
        ),
    ],
)
def test_response_disposition_field_matrix_fails_closed(
    disposition: CritiqueResponseDisposition, changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        response(disposition, **changes)


@req("FR-501", "FR-502")
def test_response_rejects_duplicate_warrants_and_mutation_fields() -> None:
    with pytest.raises(ValidationError, match="warrants must be unique"):
        response(
            CritiqueResponseDisposition.REJECT_WITH_JUSTIFICATION,
            warrant_artifact_ids=(U[20], U[20]),
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        response(CritiqueResponseDisposition.ACCEPT, target_status="WITHDRAWN")


@req("FR-501", "FR-502")
def test_revise_may_propose_a_critique_successor_when_a_critique_was_attacked() -> None:
    revision_proposal = ArtifactRevisionProposal.model_validate(critique().model_dump())
    value = response(
        CritiqueResponseDisposition.REVISE,
        proposed_revision=revision_proposal,
    )

    assert value.proposed_revision is not None
    assert value.proposed_revision.kind is ArtifactKind.CRITIQUE


@req("FR-501", "FR-502")
@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": 2},
        {"rationale": " "},
        {"responding_definition_version": 0},
        {"critique_version": 0},
        {"target_artifact_version": 0},
        {"round": 0},
    ],
)
def test_response_rejects_invalid_versions_and_blank_rationale(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        response(CritiqueResponseDisposition.ACCEPT, **changes)
