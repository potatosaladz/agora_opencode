"""Exhaustive properties over the finite Phase 3 contract vocabularies."""

from datetime import UTC, datetime
from uuid import UUID

from app.domain import reasoning as r
from tests.traceability import req

U1 = UUID("018f0000-0000-7000-8000-000000000001")
U2 = UUID("018f0000-0000-7000-8000-000000000002")
NOW = datetime(2026, 9, 5, tzinfo=UTC)


@req("FR-302")
def test_fr302_property_every_revision_preserves_logical_identity() -> None:
    for version in range(2, 51):
        data: dict[str, object] = {
            "id": UUID(int=version),
            "workspace_id": U1,
            "session_id": U2,
            "logical_id": U1,
            "kind": r.ArtifactKind.CLAIM,
            "version": version,
            "supersedes_id": UUID(int=version - 1),
            "owner_actor_class": r.ActorClass.HUMAN,
            "owner_actor_id": U1,
            "payload": r.ClaimPayload(
                statement=f"Revision {version}",
                claim_type=r.ClaimType.FACTUAL,
                direction=r.Bearing.SUPPORTS,
                strength=r.Strength.WEAK,
                supporting_evidence_ids=(),
                opposing_evidence_ids=(),
                review_status=r.ReviewStatus.PROPOSED,
            ),
            "provenance": r.Provenance(origin=r.ProvenanceOrigin.HUMAN, reference="property"),
            "created_at": NOW,
            "updated_at": NOW,
        }
        data["content_hash"] = r.artifact_content_hash(data)
        artifact = r.validate_artifact(data)
        assert artifact.logical_id == U1
        assert artifact.supersedes_id is not None
        assert artifact.version == version


@req("FR-309")
def test_fr309_property_every_type_accepts_every_uncertainty_representation() -> None:
    for uncertainty_type in r.UncertaintyType:
        values: tuple[r.UncertaintyPayload, ...] = (
            r.IntervalUncertaintyPayload(
                target_id=U1,
                uncertainty_type=uncertainty_type,
                representation="INTERVAL",
                drivers=(),
                lower="0",
                upper="1",
                unit="ratio",
            ),
            r.DistributionUncertaintyPayload(
                target_id=U1,
                uncertainty_type=uncertainty_type,
                representation="DISTRIBUTION",
                drivers=(),
                family="uniform",
                parameters={"lower": "0", "upper": "1"},
                unit="ratio",
            ),
            r.ScenariosUncertaintyPayload(
                target_id=U1,
                uncertainty_type=uncertainty_type,
                representation="SCENARIOS",
                drivers=(),
                scenarios=(r.Scenario(name="base", probability="1", value="stable"),),
            ),
            r.QualitativeUncertaintyPayload(
                target_id=U1,
                uncertainty_type=uncertainty_type,
                representation="QUALITATIVE",
                drivers=(),
                level="UNKNOWN",
                explanation="No quantified distribution is available",
            ),
        )
        assert {value.representation for value in values} == {
            "INTERVAL",
            "DISTRIBUTION",
            "SCENARIOS",
            "QUALITATIVE",
        }
