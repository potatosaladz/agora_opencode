"""Phase 3 reasoning artifact value-object tests."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from app.domain import reasoning as r
from tests.traceability import req

U = UUID("018f0000-0000-7000-8000-000000000001")
U2 = UUID("018f0000-0000-7000-8000-000000000002")
NOW = datetime(2026, 9, 5, tzinfo=UTC)


def payloads() -> dict[r.ArtifactKind, r.FrozenModel]:
    return {
        r.ArtifactKind.CLAIM: r.ClaimPayload(
            statement="s",
            claim_type=r.ClaimType.FACTUAL,
            direction=r.Bearing.SUPPORTS,
            strength=r.Strength.WEAK,
            supporting_evidence_ids=(),
            opposing_evidence_ids=(),
            review_status=r.ReviewStatus.PROPOSED,
        ),
        r.ArtifactKind.FACT: r.FactPayload(
            statement="s", verification=r.Verification.SOURCE_VERIFIED
        ),
        r.ArtifactKind.ASSUMPTION: r.AssumptionPayload(
            statement="s", basis="b", materiality="m", challengeable=True
        ),
        r.ArtifactKind.INFERENCE: r.InferencePayload(
            premise_ids=(U,),
            conclusion_id=U2,
            rule_kind="DEDUCTIVE",
            rule_text="rule",
            validity="VALID",
        ),
        r.ArtifactKind.PROPOSITION: r.PropositionPayload(
            statement_original="s",
            statement_normalized="s",
            canonicalizer_version="1",
            proposition_kind="FACTUAL",
            modality="ASSERTED",
            normalization_status=r.PropositionNormalizationStatus.VALIDATED,
        ),
        r.ArtifactKind.EVIDENCE: r.EvidencePayload(
            claim_id=U,
            relation=r.EvidenceRelation.SUPPORTS,
            quote="q",
            verification=r.Verification.UNVERIFIED,
            trust_level=r.TrustLevel.PRIMARY,
            weight="0.500",
            provenance_kind=r.EvidenceProvenance.RETRIEVAL,
        ),
        r.ArtifactKind.UNCERTAINTY: r.IntervalUncertaintyPayload(
            target_id=U,
            uncertainty_type=r.UncertaintyType.EPISTEMIC,
            representation="INTERVAL",
            drivers=("missing data",),
            lower="0.10",
            upper="0.90",
            unit="ratio",
        ),
        r.ArtifactKind.RISK: r.RiskPayload(
            statement="s",
            probability="0.25",
            impact="high",
            uncertainty_id=U,
            affected_objective_ids=(U2,),
        ),
        r.ArtifactKind.IMPACT: r.ImpactPayload(
            alternative_id=U,
            objective_id=U2,
            magnitude="-2.500",
            unit="USD",
            timeframe="1y",
            source_artifact_id=U,
        ),
        r.ArtifactKind.OBJECTIVE: r.ObjectivePayload(
            name="n",
            objective_type="COST",
            direction="MINIMIZE",
            weight="1.00",
            weight_rationale="priority",
            time_horizon="1y",
            conflicts_with_ids=(),
        ),
        r.ArtifactKind.CONSTRAINT: r.ConstraintPayload(
            name="n",
            statement="s",
            constraint_type=r.ConstraintType.HARD,
            category="BUDGET",
            evaluation_expression=r.FormalExpression(
                language="json-logic", ast={"<=": [{"var": "cost"}, "10.00"]}
            ),
            formal_status="VALIDATED",
        ),
        r.ArtifactKind.ALTERNATIVE: r.AlternativePayload(
            name="n", summary="s", components=("c",), origin="HUMAN", feasibility_status="UNKNOWN"
        ),
        r.ArtifactKind.POSITION: r.PositionPayload(
            target_id=U, stance=r.Stance.SUPPORT, rationale="r", evidence_ids=(), conditions=()
        ),
        r.ArtifactKind.CRITIQUE: r.CritiquePayload(
            target_id=U,
            critique_type=r.CritiqueType.EVIDENCE_GAP,
            severity=r.Severity.HIGH,
            argument="a",
            resolution=r.Resolution.OPEN,
        ),
    }


def artifact_data(kind: r.ArtifactKind, **changes: object) -> dict[str, object]:
    source = r.SourceReference(
        reference="src", locator={"page": 1}, content_hash="sha256:" + "a" * 64, retrieved_at=NOW
    )
    data: dict[str, object] = {
        "id": U,
        "workspace_id": U,
        "session_id": U,
        "logical_id": U2,
        "kind": kind,
        "schema_version": 1,
        "version": 1,
        "status": r.LifecycleStatus.ACTIVE,
        "supersedes_id": None,
        "owner_actor_class": r.ActorClass.HUMAN,
        "owner_actor_id": U,
        "round": 0,
        "payload": payloads()[kind],
        "provenance": r.Provenance(origin=r.ProvenanceOrigin.HUMAN, reference="author"),
        "source_references": (source,)
        if kind in {r.ArtifactKind.FACT, r.ArtifactKind.EVIDENCE}
        else (),
        "parent_relationships": (),
        "confidence": r.Confidence(
            kind="subjective", value="0.70", meaning="declared strength", basis_artifact_ids=()
        )
        if kind is r.ArtifactKind.POSITION
        else None,
        "metadata": {},
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(changes)
    data["content_hash"] = r.artifact_content_hash(data)
    return data


@req("FR-301")
@pytest.mark.parametrize("kind", list(r.ArtifactKind))
def test_constructs_every_artifact_kind(kind: r.ArtifactKind) -> None:
    artifact = r.validate_artifact(artifact_data(kind))
    assert artifact.kind is kind
    assert artifact.content_hash == r.content_hash(artifact.hash_preimage())


@req("FR-103", "FR-301", "FR-306", "FR-403")
def test_models_are_frozen_closed_and_decimal_strings_normalize() -> None:
    evidence = payloads()[r.ArtifactKind.EVIDENCE]
    assert isinstance(evidence, r.EvidencePayload)
    assert evidence.weight == "0.5"
    with pytest.raises(ValidationError):
        evidence.weight = "1"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        r.Confidence(kind="x", value="1e-1", meaning="m", basis_artifact_ids=())
    with pytest.raises(ValidationError):
        r.FormalExpression(language="x", ast={"x": 0.1})
    with pytest.raises(ValidationError):
        r.FormalExpression(language="x", ast={}, extra="no")  # type: ignore[call-arg]


@req("FR-103", "FR-301", "FR-306", "FR-403")
def test_open_json_values_are_deeply_immutable() -> None:
    expression = r.FormalExpression(language="x", ast={"nested": {"value": 1}})
    nested = expression.ast["nested"]
    assert isinstance(nested, dict)
    with pytest.raises(TypeError, match="cannot be mutated"):
        nested["value"] = 2

    artifact = r.validate_artifact(
        artifact_data(r.ArtifactKind.CLAIM, metadata={"tags": ["initial"]})
    )
    with pytest.raises(TypeError, match="cannot be mutated"):
        artifact.metadata["new"] = "value"
    tags = artifact.metadata["tags"]
    assert isinstance(tags, tuple)
    with pytest.raises(AttributeError):
        tags.append("changed")  # type: ignore[attr-defined]


@req("FR-103", "FR-301", "FR-306", "FR-403")
@pytest.mark.parametrize(
    ("kind", "changes"),
    [
        (r.ArtifactKind.CLAIM, {"version": 2}),
        (r.ArtifactKind.CLAIM, {"version": 1, "supersedes_id": U}),
        (r.ArtifactKind.CLAIM, {"owner_actor_class": r.ActorClass.POLICY}),
        (r.ArtifactKind.FACT, {"owner_actor_class": r.ActorClass.AGENT}),
        (
            r.ArtifactKind.FACT,
            {"provenance": r.Provenance(origin=r.ProvenanceOrigin.LLM, reference="call")},
        ),
        (r.ArtifactKind.FACT, {"source_references": ()}),
        (
            r.ArtifactKind.FACT,
            {
                "confidence": r.Confidence(
                    kind="subjective",
                    value="0.5",
                    meaning="model confidence",
                    basis_artifact_ids=(),
                )
            },
        ),
        (r.ArtifactKind.EVIDENCE, {"source_references": ()}),
        (
            r.ArtifactKind.EVIDENCE,
            {
                "payload": r.EvidencePayload(
                    claim_id=U,
                    relation=r.EvidenceRelation.SUPPORTS,
                    quote="q",
                    verification=r.Verification.SOURCE_VERIFIED,
                    trust_level=r.TrustLevel.PRIMARY,
                    weight="0.5",
                    provenance_kind=r.EvidenceProvenance.RETRIEVAL,
                )
            },
        ),
        (
            r.ArtifactKind.EVIDENCE,
            {
                "provenance": r.Provenance(
                    origin=r.ProvenanceOrigin.HISTORICAL_SESSION, reference="prior session"
                )
            },
        ),
        (r.ArtifactKind.POSITION, {"confidence": None}),
    ],
)
def test_rejects_invalid_envelope_combinations(
    kind: r.ArtifactKind, changes: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        r.validate_artifact(artifact_data(kind, **changes))


@req("FR-103", "FR-301", "FR-306", "FR-403")
def test_rejects_kind_payload_mismatch_and_tampered_hash() -> None:
    with pytest.raises(ValidationError):
        r.validate_artifact(
            artifact_data(r.ArtifactKind.CLAIM, payload=payloads()[r.ArtifactKind.RISK])
        )
    data = artifact_data(r.ArtifactKind.CLAIM)
    data["content_hash"] = "sha256:" + "f" * 64
    with pytest.raises(ValidationError):
        r.validate_artifact(data)


@req("FR-103", "FR-301", "FR-306", "FR-403")
def test_discriminator_selects_variant_and_valid_revision() -> None:
    data = artifact_data(r.ArtifactKind.CLAIM, version=2, supersedes_id=U)
    artifact = r.validate_artifact(data)
    assert isinstance(artifact, r.ClaimArtifact)
    assert artifact.version == 2


@req("FR-103", "FR-301", "FR-306", "FR-403")
def test_immutable_content_changes_hash_but_row_identity_does_not() -> None:
    original = artifact_data(r.ArtifactKind.CLAIM)
    metadata_changed = artifact_data(r.ArtifactKind.CLAIM, metadata={"key": "value"})
    assert original["content_hash"] != metadata_changed["content_hash"]
    id_changed = dict(original, id=U2)
    assert r.artifact_content_hash(id_changed) == original["content_hash"]


@req("FR-103", "FR-301", "FR-306", "FR-403")
def test_uncertainty_representation_is_discriminated() -> None:
    with pytest.raises(ValidationError):
        r.validate_artifact(
            artifact_data(
                r.ArtifactKind.UNCERTAINTY,
                payload={
                    "target_id": U,
                    "uncertainty_type": r.UncertaintyType.MODEL,
                    "drivers": [],
                    "representation": "INTERVAL",
                    "lower": "0",
                    "upper": "1",
                    "unit": "x",
                    "family": "normal",
                },
            )
        )


@req("FR-103", "FR-301", "FR-306", "FR-403")
@pytest.mark.parametrize(
    "payload",
    [
        r.IntervalUncertaintyPayload(
            target_id=U,
            uncertainty_type=r.UncertaintyType.MEASUREMENT,
            representation="INTERVAL",
            drivers=("instrument",),
            lower="-1.0",
            upper="1.0",
            unit="pp",
        ),
        r.DistributionUncertaintyPayload(
            target_id=U,
            uncertainty_type=r.UncertaintyType.ALEATORIC,
            representation="DISTRIBUTION",
            drivers=("variance",),
            family="normal",
            parameters={"mean": "0", "standard_deviation": "1"},
            unit="pp",
        ),
        r.ScenariosUncertaintyPayload(
            target_id=U,
            uncertainty_type=r.UncertaintyType.STRATEGIC,
            representation="SCENARIOS",
            drivers=("actor response",),
            scenarios=(r.Scenario(name="base", probability="1.0", value="stable"),),
        ),
        r.QualitativeUncertaintyPayload(
            target_id=U,
            uncertainty_type=r.UncertaintyType.SEMANTIC,
            representation="QUALITATIVE",
            drivers=("definition",),
            level="HIGH",
            explanation="Term is disputed",
        ),
    ],
)
def test_accepts_each_uncertainty_representation(payload: r.FrozenModel) -> None:
    artifact = r.validate_artifact(artifact_data(r.ArtifactKind.UNCERTAINTY, payload=payload))
    assert artifact.payload.model_dump()["representation"] == payload.model_dump()["representation"]


@req("FR-103", "FR-301", "FR-306", "FR-403")
@pytest.mark.parametrize("value", ["-0.1", "1.1", "1e-1", 0.5])
def test_bounded_decimal_fields_reject_invalid_values(value: object) -> None:
    with pytest.raises(ValidationError):
        r.Confidence.model_validate(
            {
                "kind": "subjective",
                "value": value,
                "meaning": "declared strength",
                "basis_artifact_ids": (),
            }
        )


@req("FR-103", "FR-301", "FR-306", "FR-403")
def test_negative_zero_decimal_is_canonicalized() -> None:
    confidence = r.Confidence(
        kind="subjective", value="-0.00", meaning="declared strength", basis_artifact_ids=()
    )
    assert confidence.value == "0"


def proposition(
    *,
    statement_original: str = "Will unemployment fall?",
    statement_normalized: str = "delta(unemployment,3y)<0",
    canonicalizer_version: str = "canonicalizer@1",
    normalization_status: r.PropositionNormalizationStatus = (
        r.PropositionNormalizationStatus.VALIDATED
    ),
) -> r.PropositionPayload:
    return r.PropositionPayload(
        statement_original=statement_original,
        statement_normalized=statement_normalized,
        canonicalizer_version=canonicalizer_version,
        proposition_kind="PREDICTIVE",
        modality="ASSERTED",
        normalization_status=normalization_status,
    )


@req("FR-103", "FR-306")
def test_proposition_normalization_identity_is_deterministic_and_versioned() -> None:
    normalized = proposition()
    rephrased = proposition(statement_original="Does unemployment decrease?")
    upgraded = proposition(canonicalizer_version="canonicalizer@2")

    assert normalized.normalization_identity() == r.proposition_normalization_identity(rephrased)
    assert normalized.normalization_identity().startswith("sha256:")
    assert upgraded.normalization_identity() != normalized.normalization_identity()


@req("FR-103", "FR-301", "FR-306", "FR-403")
def test_consensus_gate_rejects_ambiguous_propositions() -> None:
    with pytest.raises(ValueError, match="AMBIGUOUS"):
        r.require_consensus_proposition(
            proposition(normalization_status=r.PropositionNormalizationStatus.AMBIGUOUS)
        )


@req("FR-103", "FR-301", "FR-306", "FR-403")
@pytest.mark.parametrize(
    "status",
    [
        r.PropositionNormalizationStatus.PROPOSED,
        r.PropositionNormalizationStatus.VALIDATED,
    ],
)
def test_consensus_gate_returns_non_ambiguous_proposition(
    status: r.PropositionNormalizationStatus,
) -> None:
    candidate = proposition(normalization_status=status)
    assert r.require_consensus_proposition(candidate) is candidate


@req("FR-103", "FR-301", "FR-306", "FR-403")
def test_proposition_normalization_status_is_closed() -> None:
    with pytest.raises(ValidationError):
        r.PropositionPayload(
            statement_original="original",
            statement_normalized="normalized",
            canonicalizer_version="1",
            proposition_kind="FACTUAL",
            modality="ASSERTED",
            normalization_status="ACCEPTED",  # type: ignore[arg-type]
        )


@req("FR-103", "FR-301", "FR-306", "FR-403")
def test_artifact_and_uncertainty_unions_expose_discriminators() -> None:
    schema = TypeAdapter(r.Artifact).json_schema()
    assert schema["discriminator"]["propertyName"] == "kind"
    assert set(schema["discriminator"]["mapping"]) == {kind.value for kind in r.ArtifactKind}
    uncertainty_ref = schema["$defs"]["UncertaintyArtifact"]["properties"]["payload"]["$ref"]
    uncertainty_schema = schema["$defs"][uncertainty_ref.rsplit("/", maxsplit=1)[-1]]
    assert uncertainty_schema["discriminator"]["propertyName"] == "representation"


@req("FR-103", "FR-301", "FR-306", "FR-403")
def test_canonical_json_uses_utf16_order_and_stable_hash() -> None:
    value = {"\ue000": 1, "😀": 2, "a": "é"}
    assert r.canonical_json(value) == '{"a":"é","😀":2,"":1}'.encode()
    assert (
        r.content_hash({"b": 1, "a": 2})
        == "sha256:d3626ac30a87e6f7a6428233b3c68299976865fa5508e4267c5415c76af7a772"
    )
    with pytest.raises(ValueError, match="floats"):
        r.canonical_json({"nested": [1, 0.5]})
    with pytest.raises(ValueError, match="Unicode scalar"):
        r.canonical_json({"bad": "\ud800"})


@req("FR-103", "FR-301", "FR-306", "FR-403")
def test_source_references_are_closed_complete_and_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        r.SourceReference(
            reference="source",
            locator={},
            content_hash="sha256:" + "a" * 64,
            retrieved_at=NOW,
        )
    with pytest.raises(ValidationError):
        r.SourceReference(
            reference="source",
            locator={"page": 1},
            content_hash="sha256:" + "a" * 64,
            retrieved_at=NOW.replace(tzinfo=None),
        )


@req("FR-403")
@pytest.mark.parametrize("trust", [r.TrustLevel.UNATTRIBUTED, r.TrustLevel.SYNTHETIC])
def test_unattributed_or_synthetic_material_is_not_evidence(trust: r.TrustLevel) -> None:
    with pytest.raises(ValidationError):
        r.EvidencePayload(
            claim_id=U,
            relation=r.EvidenceRelation.SUPPORTS,
            quote="q",
            verification=r.Verification.UNVERIFIED,
            trust_level=trust,
            weight="0.5",
            provenance_kind=r.EvidenceProvenance.RETRIEVAL,
        )


@req("FR-103", "FR-301", "FR-306", "FR-403")
def test_lifecycle_fields_do_not_change_content_identity() -> None:
    original = r.validate_artifact(artifact_data(r.ArtifactKind.CLAIM))
    changed = original.model_copy(
        update={
            "status": r.LifecycleStatus.WITHDRAWN,
            "updated_at": datetime(2027, 1, 1, tzinfo=UTC),
        }
    )
    assert changed.canonical_content() == original.canonical_content()
    assert changed.content_hash == original.content_hash
