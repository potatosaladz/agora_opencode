"""Immutable Phase 3 reasoning artifacts and canonical content identity."""

# ruff: noqa: E501 -- trace annotations must remain single-line machine-readable records.

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)

__all__ = [
    "ActorClass",
    "AlternativeArtifact",
    "AlternativePayload",
    "Artifact",
    "ArtifactEnvelope",
    "ArtifactKind",
    "ArtifactPayload",
    "AssumptionArtifact",
    "AssumptionPayload",
    "Bearing",
    "ClaimArtifact",
    "ClaimPayload",
    "ClaimType",
    "Confidence",
    "ConstraintArtifact",
    "ConstraintPayload",
    "ConstraintType",
    "CritiqueArtifact",
    "CritiquePayload",
    "CritiqueType",
    "DistributionUncertaintyPayload",
    "EvidenceArtifact",
    "EvidencePayload",
    "EvidenceProvenance",
    "EvidenceRelation",
    "FactArtifact",
    "FactPayload",
    "FormalExpression",
    "GraphEdgeType",
    "ImpactArtifact",
    "ImpactPayload",
    "InferenceArtifact",
    "InferencePayload",
    "IntervalUncertaintyPayload",
    "LifecycleStatus",
    "ObjectiveArtifact",
    "ObjectivePayload",
    "ParentRelationship",
    "PositionArtifact",
    "PositionPayload",
    "PropositionArtifact",
    "PropositionNormalizationStatus",
    "PropositionPayload",
    "Provenance",
    "ProvenanceOrigin",
    "QualitativeUncertaintyPayload",
    "ReasoningArtifact",
    "Resolution",
    "ReviewStatus",
    "RiskArtifact",
    "RiskPayload",
    "Scenario",
    "ScenariosUncertaintyPayload",
    "Severity",
    "SourceReference",
    "Stance",
    "Strength",
    "TrustLevel",
    "UncertaintyArtifact",
    "UncertaintyPayload",
    "UncertaintyType",
    "Verification",
    "artifact_content_hash",
    "canonical_json",
    "content_hash",
    "proposition_normalization_identity",
    "require_consensus_proposition",
    "validate_artifact",
    "validate_artifact_json",
    "validate_artifact_payload",
]


# trace: FR-103, FR-301, FR-304, FR-306, FR-307, FR-308, FR-309, FR-310, FR-311, FR-312, FR-403, FR-501
def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


NonEmpty = Annotated[str, Field(strict=True, min_length=1), AfterValidator(_not_blank)]
DecimalString = Annotated[str, Field(strict=True, pattern=r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")]
UnitDecimalString = Annotated[DecimalString, Field(pattern=r"^(?:-?0(?:\.0+)?|0\.\d+|1(?:\.0+)?)$")]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class FrozenDict(dict[str, Any]):
    """Dict-compatible recursively immutable JSON object."""

    def _immutable(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("frozen JSON object cannot be mutated")

    __delitem__ = _immutable
    __setitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable  # type: ignore[assignment]
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable  # type: ignore[assignment]


def _decimal(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("must be a decimal string")  # noqa: TRY004
    if "e" in value.lower() or not re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?", value):
        raise ValueError("must be a plain decimal string without exponent notation")
    result = value.rstrip("0").rstrip(".") if "." in value else value
    if result in {"-0", ""}:
        return "0"
    return result


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError("JSON strings must contain Unicode scalar values")
        return value
    if value is None or type(value) in {bool, int}:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite numbers are not JSON values")
        raise ValueError("floats are forbidden; use canonical decimal strings")  # noqa: TRY004
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        return {key: _json_value(item) for key, item in value.items()}
    raise ValueError(f"unsupported JSON value: {type(value).__name__}")


def _frozen_json(value: Any) -> Any:
    validated = _json_value(value)
    if isinstance(validated, list):
        return tuple(_frozen_json(item) for item in validated)
    if isinstance(validated, dict):
        return FrozenDict({key: _frozen_json(item) for key, item in validated.items()})
    return validated


def _utf16_key(value: str) -> bytes:
    return value.encode("utf-16-be", errors="surrogatepass")


def _canonical(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value, key=_utf16_key)
        return "{" + ",".join(f"{_canonical(key)}:{_canonical(value[key])}" for key in keys) + "}"
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    """Serialize supported JSON deterministically with RFC 8785 UTF-16 key ordering."""
    return _canonical(_json_value(value)).encode()


def content_hash(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_json(value)).hexdigest()}"


def _valid_revision(version: int, supersedes_id: UUID | None) -> bool:
    return (version == 1 and supersedes_id is None) or (version > 1 and supersedes_id is not None)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an RFC 3339 offset")
    return value.astimezone(UTC)


class ArtifactKind(StrEnum):
    CLAIM = "CLAIM"
    FACT = "FACT"
    ASSUMPTION = "ASSUMPTION"
    INFERENCE = "INFERENCE"
    PROPOSITION = "PROPOSITION"
    EVIDENCE = "EVIDENCE"
    UNCERTAINTY = "UNCERTAINTY"
    RISK = "RISK"
    IMPACT = "IMPACT"
    OBJECTIVE = "OBJECTIVE"
    CONSTRAINT = "CONSTRAINT"
    ALTERNATIVE = "ALTERNATIVE"
    POSITION = "POSITION"
    CRITIQUE = "CRITIQUE"


class LifecycleStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class ActorClass(StrEnum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"
    SERVICE = "SERVICE"
    POLICY = "POLICY"


class ProvenanceOrigin(StrEnum):
    HUMAN = "HUMAN"
    LLM = "LLM"
    RETRIEVAL = "RETRIEVAL"
    TOOL = "TOOL"
    SIMULATION = "SIMULATION"
    SYMBOLIC = "SYMBOLIC"
    IMPORT = "IMPORT"
    HISTORICAL_SESSION = "HISTORICAL_SESSION"


class Verification(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    SOURCE_VERIFIED = "SOURCE_VERIFIED"
    CROSS_CHECKED = "CROSS_CHECKED"
    DISPUTED = "DISPUTED"
    REJECTED = "REJECTED"


class GraphEdgeType(StrEnum):
    SUPPORTS = "SUPPORTS"
    OPPOSES = "OPPOSES"
    CONTRADICTS = "CONTRADICTS"
    DERIVED_FROM = "DERIVED_FROM"
    BASED_ON_ASSUMPTION = "BASED_ON_ASSUMPTION"
    FORMALIZES = "FORMALIZES"
    QUANTIFIES = "QUANTIFIES"
    IMPACTS = "IMPACTS"
    CONSTRAINS = "CONSTRAINS"
    VIOLATES = "VIOLATES"
    SATISFIES = "SATISFIES"
    INFEASIBLE_UNKNOWN = "INFEASIBLE_UNKNOWN"
    ATTACKS = "ATTACKS"
    RESPONDS_TO = "RESPONDS_TO"
    SUPERSEDES = "SUPERSEDES"
    ADVOCATES = "ADVOCATES"


class Provenance(FrozenModel):
    origin: ProvenanceOrigin
    reference: NonEmpty
    model_call_id: UUID | None = None
    activity_id: UUID | None = None


class SourceReference(FrozenModel):
    reference: NonEmpty
    locator: dict[str, Any]
    content_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    retrieved_at: datetime
    source_timestamp: datetime | None = None
    _locator_json = field_validator("locator")(_frozen_json)
    _timestamps_aware = field_validator("retrieved_at", "source_timestamp")(_aware)

    @field_validator("locator")
    @classmethod
    def locator_not_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("locator must not be empty")
        return value


class ParentRelationship(FrozenModel):
    edge_type: GraphEdgeType
    target_artifact_id: UUID


class Confidence(FrozenModel):
    kind: NonEmpty
    value: UnitDecimalString
    meaning: NonEmpty
    basis_artifact_ids: tuple[UUID, ...]
    _normalize = field_validator("value")(_decimal)


class FormalExpression(FrozenModel):
    language: NonEmpty
    ast: dict[str, Any]
    _ast_json = field_validator("ast")(_frozen_json)

    @field_validator("ast")
    @classmethod
    def ast_not_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("ast must not be empty")
        return value


class ClaimType(StrEnum):
    FACTUAL = "FACTUAL"
    CAUSAL = "CAUSAL"
    PREDICTIVE = "PREDICTIVE"
    EVALUATIVE = "EVALUATIVE"
    PROCEDURAL = "PROCEDURAL"
    HYPOTHESIS = "HYPOTHESIS"


class Bearing(StrEnum):
    SUPPORTS = "SUPPORTS"
    OPPOSES = "OPPOSES"


class EvidenceRelation(StrEnum):
    SUPPORTS = "SUPPORTS"
    OPPOSES = "OPPOSES"
    QUALIFIES = "QUALIFIES"


class Strength(StrEnum):
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"
    DECISIVE = "DECISIVE"


class ReviewStatus(StrEnum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    CONTESTED = "CONTESTED"
    REJECTED = "REJECTED"


class PropositionNormalizationStatus(StrEnum):
    """Review state of a deterministic, versioned proposition normalization."""

    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    AMBIGUOUS = "AMBIGUOUS"


class TrustLevel(StrEnum):
    PRIMARY = "PRIMARY"
    AUTHORITATIVE = "AUTHORITATIVE"
    SECONDARY = "SECONDARY"
    COMMERCIAL = "COMMERCIAL"
    UNATTRIBUTED = "UNATTRIBUTED"
    SYNTHETIC = "SYNTHETIC"


class EvidenceProvenance(StrEnum):
    RETRIEVAL = "RETRIEVAL"
    TOOL = "TOOL"
    SIMULATION = "SIMULATION"
    SYMBOLIC = "SYMBOLIC"
    HUMAN = "HUMAN"
    IMPORT = "IMPORT"


class UncertaintyType(StrEnum):
    EPISTEMIC = "EPISTEMIC"
    ALEATORIC = "ALEATORIC"
    MODEL = "MODEL"
    MEASUREMENT = "MEASUREMENT"
    SEMANTIC = "SEMANTIC"
    STRATEGIC = "STRATEGIC"


class ConstraintType(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"
    NON_NEGOTIABLE = "NON_NEGOTIABLE"


class Stance(StrEnum):
    SUPPORT = "SUPPORT"
    OPPOSE = "OPPOSE"
    CONDITIONALLY_SUPPORT = "CONDITIONALLY_SUPPORT"
    ABSTAIN = "ABSTAIN"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    BLOCKING = "BLOCKING"


class Resolution(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    DISPUTED = "DISPUTED"


class CritiqueType(StrEnum):
    EVIDENCE_GAP = "EVIDENCE_GAP"
    LOGICAL_FALLACY = "LOGICAL_FALLACY"
    HALLUCINATED_SOURCE = "HALLUCINATED_SOURCE"
    MEASUREMENT_ERROR = "MEASUREMENT_ERROR"
    MODEL_MISUSE = "MODEL_MISUSE"
    CONSTRAINT_IGNORED = "CONSTRAINT_IGNORED"
    CONFLICT_OF_INTEREST = "CONFLICT_OF_INTEREST"
    ALTERNATIVE_OMITTED = "ALTERNATIVE_OMITTED"
    UNCERTAINTY_UNDERSTATED = "UNCERTAINTY_UNDERSTATED"
    CAUSAL_OVERCLAIM = "CAUSAL_OVERCLAIM"


class ClaimPayload(FrozenModel):
    statement: NonEmpty
    claim_type: ClaimType
    direction: Bearing
    strength: Strength
    supporting_evidence_ids: tuple[UUID, ...]
    opposing_evidence_ids: tuple[UUID, ...]
    review_status: ReviewStatus


class FactPayload(FrozenModel):
    statement: NonEmpty
    verification: Literal[Verification.SOURCE_VERIFIED, Verification.CROSS_CHECKED]


class AssumptionPayload(FrozenModel):
    statement: NonEmpty
    basis: NonEmpty
    materiality: NonEmpty
    challengeable: bool


class InferencePayload(FrozenModel):
    premise_ids: tuple[UUID, ...]
    conclusion_id: UUID
    rule_kind: NonEmpty
    rule_text: NonEmpty
    validity: NonEmpty


class PropositionPayload(FrozenModel):
    statement_original: NonEmpty
    statement_normalized: NonEmpty
    canonicalizer_version: NonEmpty
    proposition_kind: NonEmpty
    modality: NonEmpty
    normalization_status: PropositionNormalizationStatus

    def normalization_identity(self) -> str:
        """Return identity used to compare normalized consensus propositions."""
        return proposition_normalization_identity(self)


def proposition_normalization_identity(proposition: PropositionPayload) -> str:
    """Hash normalized meaning together with its canonicalizer version.

    Original prose and review status are intentionally excluded. A canonicalizer
    upgrade creates a distinct identity even when it emits the same text.
    """
    return content_hash(
        {
            "canonicalizer_version": proposition.canonicalizer_version,
            "statement_normalized": proposition.statement_normalized,
            "proposition_kind": proposition.proposition_kind,
            "modality": proposition.modality,
        }
    )


def require_consensus_proposition(proposition: PropositionPayload) -> PropositionPayload:
    """Reject ambiguous proposition normalizations from consensus use."""
    if proposition.normalization_status is PropositionNormalizationStatus.AMBIGUOUS:
        raise ValueError("AMBIGUOUS proposition normalization cannot enter consensus")
    return proposition


class EvidencePayload(FrozenModel):
    claim_id: UUID
    relation: EvidenceRelation
    quote: NonEmpty
    verification: Verification
    trust_level: TrustLevel
    weight: UnitDecimalString
    provenance_kind: EvidenceProvenance
    _normalize = field_validator("weight", mode="before")(_decimal)

    @model_validator(mode="after")
    def attributable_source(self) -> EvidencePayload:
        if self.trust_level in {TrustLevel.UNATTRIBUTED, TrustLevel.SYNTHETIC}:
            raise ValueError("UNATTRIBUTED and SYNTHETIC material may not be EVIDENCE")
        return self


class UncertaintyFields(FrozenModel):
    target_id: UUID
    uncertainty_type: UncertaintyType
    drivers: tuple[NonEmpty, ...]


class IntervalUncertaintyPayload(UncertaintyFields):
    representation: Literal["INTERVAL"]
    lower: DecimalString
    upper: DecimalString
    unit: NonEmpty
    _normalize = field_validator("lower", "upper", mode="before")(_decimal)

    @model_validator(mode="after")
    def ordered(self) -> IntervalUncertaintyPayload:
        from decimal import Decimal

        if Decimal(self.lower) > Decimal(self.upper):
            raise ValueError("lower must not exceed upper")
        return self


class DistributionUncertaintyPayload(UncertaintyFields):
    representation: Literal["DISTRIBUTION"]
    family: NonEmpty
    parameters: dict[str, Any]
    unit: NonEmpty
    _parameters_json = field_validator("parameters")(_frozen_json)


class Scenario(FrozenModel):
    name: NonEmpty
    probability: UnitDecimalString
    value: Any
    _probability = field_validator("probability", mode="before")(_decimal)
    _value_json = field_validator("value")(_frozen_json)


class ScenariosUncertaintyPayload(UncertaintyFields):
    representation: Literal["SCENARIOS"]
    scenarios: tuple[Scenario, ...]

    @field_validator("scenarios")
    @classmethod
    def non_empty(cls, value: tuple[Scenario, ...]) -> tuple[Scenario, ...]:
        if not value:
            raise ValueError("scenarios must not be empty")
        return value


class QualitativeUncertaintyPayload(UncertaintyFields):
    representation: Literal["QUALITATIVE"]
    level: NonEmpty
    explanation: NonEmpty


type UncertaintyPayload = Annotated[
    IntervalUncertaintyPayload
    | DistributionUncertaintyPayload
    | ScenariosUncertaintyPayload
    | QualitativeUncertaintyPayload,
    Field(discriminator="representation"),
]


class RiskPayload(FrozenModel):
    statement: NonEmpty
    probability: UnitDecimalString
    impact: NonEmpty
    uncertainty_id: UUID
    affected_objective_ids: tuple[UUID, ...]
    _normalize = field_validator("probability", mode="before")(_decimal)


class ImpactPayload(FrozenModel):
    alternative_id: UUID
    objective_id: UUID
    magnitude: DecimalString
    unit: NonEmpty
    timeframe: NonEmpty
    source_artifact_id: UUID
    _normalize = field_validator("magnitude", mode="before")(_decimal)


class ObjectivePayload(FrozenModel):
    name: NonEmpty
    objective_type: NonEmpty
    direction: NonEmpty
    weight: UnitDecimalString
    weight_rationale: NonEmpty
    time_horizon: NonEmpty
    conflicts_with_ids: tuple[UUID, ...]
    _normalize = field_validator("weight", mode="before")(_decimal)


class ConstraintPayload(FrozenModel):
    name: NonEmpty
    statement: NonEmpty
    constraint_type: ConstraintType
    category: NonEmpty
    evaluation_expression: FormalExpression
    formal_status: NonEmpty


class AlternativePayload(FrozenModel):
    name: NonEmpty
    summary: NonEmpty
    components: tuple[NonEmpty, ...]
    origin: NonEmpty
    feasibility_status: NonEmpty


class PositionPayload(FrozenModel):
    target_id: UUID
    stance: Stance
    rationale: NonEmpty
    evidence_ids: tuple[UUID, ...]
    conditions: tuple[NonEmpty, ...]


class CritiquePayload(FrozenModel):
    target_id: UUID
    critique_type: CritiqueType
    severity: Severity
    argument: NonEmpty
    resolution: Resolution


type ArtifactPayload = (
    ClaimPayload
    | FactPayload
    | AssumptionPayload
    | InferencePayload
    | PropositionPayload
    | EvidencePayload
    | UncertaintyPayload
    | RiskPayload
    | ImpactPayload
    | ObjectivePayload
    | ConstraintPayload
    | AlternativePayload
    | PositionPayload
    | CritiquePayload
)

_PAYLOAD_ADAPTERS: dict[ArtifactKind, TypeAdapter[Any]] = {
    ArtifactKind.CLAIM: TypeAdapter(ClaimPayload),
    ArtifactKind.FACT: TypeAdapter(FactPayload),
    ArtifactKind.ASSUMPTION: TypeAdapter(AssumptionPayload),
    ArtifactKind.INFERENCE: TypeAdapter(InferencePayload),
    ArtifactKind.PROPOSITION: TypeAdapter(PropositionPayload),
    ArtifactKind.EVIDENCE: TypeAdapter(EvidencePayload),
    ArtifactKind.UNCERTAINTY: TypeAdapter(UncertaintyPayload),
    ArtifactKind.RISK: TypeAdapter(RiskPayload),
    ArtifactKind.IMPACT: TypeAdapter(ImpactPayload),
    ArtifactKind.OBJECTIVE: TypeAdapter(ObjectivePayload),
    ArtifactKind.CONSTRAINT: TypeAdapter(ConstraintPayload),
    ArtifactKind.ALTERNATIVE: TypeAdapter(AlternativePayload),
    ArtifactKind.POSITION: TypeAdapter(PositionPayload),
    ArtifactKind.CRITIQUE: TypeAdapter(CritiquePayload),
}


def validate_artifact_payload(kind: ArtifactKind, value: Any) -> ArtifactPayload:
    """Validate untrusted JSON through the selected kind's strict payload contract."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return cast(
        ArtifactPayload,
        _PAYLOAD_ADAPTERS[kind].validate_json(json.dumps(value, default=str)),
    )


class ArtifactEnvelope(FrozenModel):
    id: UUID
    workspace_id: UUID
    session_id: UUID
    logical_id: UUID
    kind: ArtifactKind
    schema_version: Annotated[int, Field(gt=0)] = 1
    version: Annotated[int, Field(gt=0)] = 1
    status: LifecycleStatus = LifecycleStatus.ACTIVE
    supersedes_id: UUID | None = None
    owner_actor_class: ActorClass
    owner_actor_id: UUID
    round: Annotated[int, Field(ge=0)] = 0
    payload: ArtifactPayload
    provenance: Provenance
    source_references: tuple[SourceReference, ...] = ()
    parent_relationships: tuple[ParentRelationship, ...] = ()
    confidence: Confidence | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    content_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]

    _metadata_json = field_validator("metadata")(_frozen_json)
    _timestamps_aware = field_validator("created_at", "updated_at")(_aware)

    @model_validator(mode="after")
    def invariants(self, info: ValidationInfo) -> ArtifactEnvelope:
        payload_types: dict[ArtifactKind, type[FrozenModel] | tuple[type[FrozenModel], ...]] = {
            ArtifactKind.CLAIM: ClaimPayload,
            ArtifactKind.FACT: FactPayload,
            ArtifactKind.ASSUMPTION: AssumptionPayload,
            ArtifactKind.INFERENCE: InferencePayload,
            ArtifactKind.PROPOSITION: PropositionPayload,
            ArtifactKind.EVIDENCE: EvidencePayload,
            ArtifactKind.UNCERTAINTY: (
                IntervalUncertaintyPayload,
                DistributionUncertaintyPayload,
                ScenariosUncertaintyPayload,
                QualitativeUncertaintyPayload,
            ),
            ArtifactKind.RISK: RiskPayload,
            ArtifactKind.IMPACT: ImpactPayload,
            ArtifactKind.OBJECTIVE: ObjectivePayload,
            ArtifactKind.CONSTRAINT: ConstraintPayload,
            ArtifactKind.ALTERNATIVE: AlternativePayload,
            ArtifactKind.POSITION: PositionPayload,
            ArtifactKind.CRITIQUE: CritiquePayload,
        }
        if not isinstance(self.payload, payload_types[self.kind]):
            raise ValueError(f"payload does not match kind {self.kind}")  # noqa: TRY004
        if not _valid_revision(self.version, self.supersedes_id):
            raise ValueError("version 1 must not supersede; later versions must supersede")
        if self.owner_actor_class is ActorClass.POLICY:
            raise ValueError("POLICY may not own content artifacts")
        if self.kind is ArtifactKind.FACT and self.owner_actor_class is ActorClass.AGENT:
            raise ValueError("AGENT may not own FACT")
        if self.kind is ArtifactKind.FACT and self.provenance.origin is ProvenanceOrigin.LLM:
            raise ValueError("LLM output may not be classified directly as FACT")
        if self.kind in {ArtifactKind.FACT, ArtifactKind.EVIDENCE} and not self.source_references:
            raise ValueError(f"{self.kind} requires source references")
        if (
            self.kind is ArtifactKind.EVIDENCE
            and self.provenance.origin is ProvenanceOrigin.HISTORICAL_SESSION
        ):
            raise ValueError("historical sessions may not produce EVIDENCE")
        if (
            self.kind is ArtifactKind.EVIDENCE
            and self.version == 1
            and isinstance(self.payload, EvidencePayload)
            and self.payload.verification is not Verification.UNVERIFIED
        ):
            raise ValueError("new EVIDENCE must start UNVERIFIED")
        if self.kind is ArtifactKind.POSITION and self.confidence is None:
            raise ValueError("POSITION requires confidence")
        if self.kind is ArtifactKind.FACT and self.confidence is not None:
            raise ValueError("FACT may not carry model confidence")
        verify_hash = not info.context or not info.context.get("skip_content_hash", False)
        if verify_hash and self.content_hash != content_hash(self.hash_preimage()):
            raise ValueError("content_hash does not match immutable content")
        return self

    def hash_preimage(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        return {
            key: data[key]
            for key in (
                "workspace_id",
                "session_id",
                "logical_id",
                "kind",
                "schema_version",
                "version",
                "supersedes_id",
                "owner_actor_class",
                "owner_actor_id",
                "round",
                "payload",
                "provenance",
                "source_references",
                "parent_relationships",
                "confidence",
                "metadata",
            )
        }

    def canonical_content(self) -> bytes:
        return canonical_json(self.hash_preimage())


class ClaimArtifact(ArtifactEnvelope):
    kind: Literal[ArtifactKind.CLAIM]
    payload: ClaimPayload


class FactArtifact(ArtifactEnvelope):
    kind: Literal[ArtifactKind.FACT]
    payload: FactPayload


class AssumptionArtifact(ArtifactEnvelope):
    kind: Literal[ArtifactKind.ASSUMPTION]
    payload: AssumptionPayload


class InferenceArtifact(ArtifactEnvelope):
    kind: Literal[ArtifactKind.INFERENCE]
    payload: InferencePayload


class PropositionArtifact(ArtifactEnvelope):
    kind: Literal[ArtifactKind.PROPOSITION]
    payload: PropositionPayload


class EvidenceArtifact(ArtifactEnvelope):
    kind: Literal[ArtifactKind.EVIDENCE]
    payload: EvidencePayload


class UncertaintyArtifact(ArtifactEnvelope):
    kind: Literal[ArtifactKind.UNCERTAINTY]
    payload: UncertaintyPayload


class RiskArtifact(ArtifactEnvelope):
    kind: Literal[ArtifactKind.RISK]
    payload: RiskPayload


class ImpactArtifact(ArtifactEnvelope):
    kind: Literal[ArtifactKind.IMPACT]
    payload: ImpactPayload


class ObjectiveArtifact(ArtifactEnvelope):
    kind: Literal[ArtifactKind.OBJECTIVE]
    payload: ObjectivePayload


class ConstraintArtifact(ArtifactEnvelope):
    kind: Literal[ArtifactKind.CONSTRAINT]
    payload: ConstraintPayload


class AlternativeArtifact(ArtifactEnvelope):
    kind: Literal[ArtifactKind.ALTERNATIVE]
    payload: AlternativePayload


class PositionArtifact(ArtifactEnvelope):
    kind: Literal[ArtifactKind.POSITION]
    payload: PositionPayload


class CritiqueArtifact(ArtifactEnvelope):
    kind: Literal[ArtifactKind.CRITIQUE]
    payload: CritiquePayload


type Artifact = Annotated[
    ClaimArtifact
    | FactArtifact
    | AssumptionArtifact
    | InferenceArtifact
    | PropositionArtifact
    | EvidenceArtifact
    | UncertaintyArtifact
    | RiskArtifact
    | ImpactArtifact
    | ObjectiveArtifact
    | ConstraintArtifact
    | AlternativeArtifact
    | PositionArtifact
    | CritiqueArtifact,
    Field(discriminator="kind"),
]
type ReasoningArtifact = Artifact

_ARTIFACT_ADAPTER: TypeAdapter[Artifact] = TypeAdapter(Artifact)


def validate_artifact(value: Any) -> Artifact:
    """Validate an untrusted value as one of the 14 artifact envelopes."""
    return _ARTIFACT_ADAPTER.validate_python(value)


def validate_artifact_json(value: str | bytes) -> Artifact:
    """Validate a JSON envelope while retaining strict Python-domain construction."""
    return _ARTIFACT_ADAPTER.validate_json(value)


def artifact_content_hash(value: dict[str, Any]) -> str:
    """Validate, normalize, and hash the exact normative immutable envelope keys."""
    candidate = _ARTIFACT_ADAPTER.validate_python(
        {**value, "content_hash": "sha256:" + "0" * 64},
        context={"skip_content_hash": True},
    )
    return content_hash(candidate.hash_preimage())
