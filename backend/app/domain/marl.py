"""Deterministic Phase 12 MARL trajectory contracts.

The module is deliberately infrastructure-neutral.  It defines immutable capture facts,
exact arithmetic, canonical preimages, lifecycle invariants, and the two MARL ports.  It
does not train a policy and cannot change coordinator authority.
"""

from __future__ import annotations

import hashlib
import math
import re
from enum import StrEnum
from fractions import Fraction
from typing import Annotated, Any, Literal, Protocol, runtime_checkable
from uuid import UUID, uuid5

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.reasoning import canonical_json

__all__ = [
    "ActionKind",
    "CanonicalDecimal",
    "CoordinatorDecisionV1",
    "CreditAssignmentV1",
    "CreditStatus",
    "DecisionBoundaryV1",
    "EpisodeStatus",
    "ExecutedActionV1",
    "FailureCode",
    "ImplementationRefV1",
    "IncompleteMarkerV1",
    "MarlEnvironment",
    "MarlEpisodeV1",
    "MarlObservationV1",
    "MarlTrajectoryStore",
    "ObservationFeatureV1",
    "ObservationSourceV1",
    "ProposedActionV1",
    "RationalV1",
    "ReplayFailureV1",
    "ReplayOutcome",
    "ReplayVerificationV1",
    "RewardComponentV1",
    "RewardDirection",
    "RewardStatus",
    "SourceSnapshotV1",
    "TrajectoryManifestV1",
    "TransitionV1",
    "VerificationStage",
    "canonical_hash",
    "deterministic_uuid",
    "episode_hash",
    "validate_hash",
]

SCHEMA_VERSION = 1
HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"
_HASH_RE = re.compile(HASH_PATTERN)
_DECIMAL_RE = re.compile(r"^(?:0|-?[1-9][0-9]*)(?:\.[0-9]*[1-9])?$")
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$")
_REASON_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


def _identifier(value: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError("identifier must be lowercase ASCII and version-stable")
    return value


def _reason(value: str) -> str:
    if not _REASON_RE.fullmatch(value):
        raise ValueError("reason must be a stable uppercase code")
    return value


def _version(value: str) -> str:
    if not _VERSION_RE.fullmatch(value):
        raise ValueError("version must be stable ASCII")
    return value


def canonical_hash(value: Any) -> str:
    """Hash one closed JCS preimage using the project-wide identity format."""
    return f"sha256:{hashlib.sha256(canonical_json(value)).hexdigest()}"


def deterministic_uuid(namespace: UUID, kind: str, preimage: dict[str, Any]) -> UUID:
    """Derive a stable UUID identity from a kind-tagged canonical preimage."""
    return uuid5(namespace, f"{kind}:{canonical_hash(preimage)}")


def _dump(model: BaseModel, *, exclude: set[str] | None = None) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude=exclude or set())


def validate_hash(model: BaseModel, field: str) -> None:
    """Validate the rule that only an object's own hash is omitted from its preimage."""
    actual = getattr(model, field)
    expected = canonical_hash(_dump(model, exclude={field}))
    if actual != expected:
        raise ValueError(f"{field} does not match canonical preimage")


class RationalV1(_Frozen):
    """Canonical reduced rational with a positive denominator."""

    numerator: int
    denominator: int = Field(gt=0)

    @model_validator(mode="after")
    def reduced(self) -> RationalV1:
        if math.gcd(self.numerator, self.denominator) != 1:
            raise ValueError("rational must be reduced")
        return self

    @classmethod
    def from_fraction(cls, value: Fraction) -> RationalV1:
        return cls(numerator=value.numerator, denominator=value.denominator)

    @classmethod
    def zero(cls) -> RationalV1:
        return cls(numerator=0, denominator=1)

    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    def __add__(self, other: RationalV1) -> RationalV1:
        return RationalV1.from_fraction(self.fraction() + other.fraction())

    def __mul__(self, other: RationalV1) -> RationalV1:
        return RationalV1.from_fraction(self.fraction() * other.fraction())


def _canonical_decimal(value: str) -> str:
    if not _DECIMAL_RE.fullmatch(value) or value == "-0":
        raise ValueError("decimal must be canonical, finite, plain, and free of trailing zeroes")
    return value


CanonicalDecimal = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=256),
    AfterValidator(_canonical_decimal),
]
Hash = Annotated[str, Field(strict=True, pattern=HASH_PATTERN)]
Identifier = Annotated[str, Field(strict=True, min_length=1, max_length=128)]
ReasonCode = Annotated[str, Field(strict=True, min_length=1, max_length=64)]


class EpisodeStatus(StrEnum):
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class RewardStatus(StrEnum):
    OBSERVED = "OBSERVED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    MISSING_INPUT = "MISSING_INPUT"


class RewardDirection(StrEnum):
    HIGHER_BETTER = "HIGHER_BETTER"
    LOWER_BETTER = "LOWER_BETTER"
    NO_DIRECTION = "NO_DIRECTION"


class CreditStatus(StrEnum):
    DIRECT = "DIRECT"
    SHARED = "SHARED"
    ENVIRONMENT = "ENVIRONMENT"
    NEUTRAL = "NEUTRAL"


class ActionKind(StrEnum):
    SPEAK = "SPEAK"
    REQUEST_RETRIEVAL = "REQUEST_RETRIEVAL"
    REQUEST_SIMULATION = "REQUEST_SIMULATION"
    END_ROUND = "END_ROUND"
    TERMINATE = "TERMINATE"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"


class DecisionOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    NO_PROPOSAL = "NO_PROPOSAL"


class ReplayOutcome(StrEnum):
    VERIFIED = "VERIFIED"
    INCOMPLETE = "INCOMPLETE"
    FAILED = "FAILED"


class FailureCode(StrEnum):
    BUNDLE_ENTRY_SET = "BUNDLE_ENTRY_SET"
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
    INVALID_UTF8 = "INVALID_UTF8"
    INVALID_JSON = "INVALID_JSON"
    UNSUPPORTED_SCHEMA_VERSION = "UNSUPPORTED_SCHEMA_VERSION"
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
    NONCANONICAL_ENCODING = "NONCANONICAL_ENCODING"
    MANIFEST_MISMATCH = "MANIFEST_MISMATCH"
    ORDER_VIOLATION = "ORDER_VIOLATION"
    HASH_MISMATCH = "HASH_MISMATCH"
    REFERENCE_MISMATCH = "REFERENCE_MISMATCH"
    UNKNOWN_IMPLEMENTATION = "UNKNOWN_IMPLEMENTATION"
    REPLAY_MISMATCH = "REPLAY_MISMATCH"
    EPISODE_INCOMPLETE = "EPISODE_INCOMPLETE"


class VerificationStage(StrEnum):
    BUNDLE = "BUNDLE"
    RESOURCE = "RESOURCE"
    DECODE = "DECODE"
    PARSE = "PARSE"
    SCHEMA = "SCHEMA"
    CANONICAL = "CANONICAL"
    MANIFEST = "MANIFEST"
    ORDER = "ORDER"
    HASH = "HASH"
    REFERENCE = "REFERENCE"
    IMPLEMENTATION = "IMPLEMENTATION"
    REPLAY = "REPLAY"
    COMPLETENESS = "COMPLETENESS"


class ImplementationRefV1(_Frozen):
    implementation_id: Identifier
    implementation_version: Identifier

    _id = field_validator("implementation_id")(_identifier)
    _version_value = field_validator("implementation_version")(_version)


class SourceSnapshotV1(_Frozen):
    schema_version: Literal[1] = 1
    source_id: UUID
    source_kind: Identifier
    source_version: int = Field(ge=1)
    payload: dict[str, Any]
    snapshot_hash: Hash

    _kind = field_validator("source_kind")(_identifier)

    @classmethod
    def create(
        cls, *, source_id: UUID, source_kind: str, source_version: int, payload: dict[str, Any]
    ) -> SourceSnapshotV1:
        preimage = {
            "payload": payload,
            "schema_version": 1,
            "source_id": str(source_id),
            "source_kind": source_kind,
            "source_version": source_version,
        }
        return cls(
            source_id=source_id,
            source_kind=source_kind,
            source_version=source_version,
            payload=payload,
            snapshot_hash=canonical_hash(preimage),
        )


class ObservationSourceV1(_Frozen):
    schema_version: Literal[1] = 1
    ordinal: int = Field(ge=0)
    snapshot: SourceSnapshotV1
    source_hash: Hash

    @classmethod
    def create(cls, *, ordinal: int, snapshot: SourceSnapshotV1) -> ObservationSourceV1:
        value = cls(ordinal=ordinal, snapshot=snapshot, source_hash="sha256:" + "0" * 64)
        return value.model_copy(
            update={"source_hash": canonical_hash(_dump(value, exclude={"source_hash"}))}
        )


class ObservationFeatureV1(_Frozen):
    schema_version: Literal[1] = 1
    feature_id: Identifier
    feature_version: Identifier
    value: bool | int | str | tuple[Any, ...] | dict[str, Any] | None
    source_hashes: tuple[Hash, ...]
    feature_hash: Hash

    _feature_id = field_validator("feature_id")(_identifier)
    _feature_version = field_validator("feature_version")(_version)

    @model_validator(mode="after")
    def ordered_sources(self) -> ObservationFeatureV1:
        if tuple(sorted(self.source_hashes)) != self.source_hashes:
            raise ValueError("feature source hashes must be ordered")
        if len(set(self.source_hashes)) != len(self.source_hashes):
            raise ValueError("feature source hashes must be unique")
        canonical_json(self.value)
        return self

    @classmethod
    def create(
        cls,
        *,
        feature_id: str,
        feature_version: str,
        value: bool | int | str | tuple[Any, ...] | dict[str, Any] | None,
        source_hashes: tuple[str, ...],
    ) -> ObservationFeatureV1:
        item = cls(
            feature_id=feature_id,
            feature_version=feature_version,
            value=value,
            source_hashes=source_hashes,
            feature_hash="sha256:" + "0" * 64,
        )
        return item.model_copy(
            update={"feature_hash": canonical_hash(_dump(item, exclude={"feature_hash"}))}
        )


class MarlObservationV1(_Frozen):
    schema_version: Literal[1] = 1
    observation_id: UUID
    episode_id: UUID
    workspace_id: UUID
    session_id: UUID
    decision_index: int = Field(ge=0)
    environment_version: Identifier
    observation_implementation: ImplementationRefV1
    ledger_seq: int = Field(ge=0)
    ledger_event_id: UUID | None
    ledger_hash: Hash
    terminal: bool
    terminal_reason: ReasonCode | None
    sources: tuple[ObservationSourceV1, ...]
    features: tuple[ObservationFeatureV1, ...]
    sources_hash: Hash
    features_hash: Hash
    observation_hash: Hash

    _environment = field_validator("environment_version")(_identifier)

    @model_validator(mode="after")
    def shape_and_order(self) -> MarlObservationV1:
        if self.terminal != (self.terminal_reason is not None):
            raise ValueError("terminal observation shape is inconsistent")
        if tuple(item.ordinal for item in self.sources) != tuple(range(len(self.sources))):
            raise ValueError("observation sources must use gapless ordinals")
        keys = tuple((item.feature_id, item.feature_version) for item in self.features)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("observation features must be uniquely ordered")
        return self

    @classmethod
    def create(
        cls,
        *,
        observation_id: UUID,
        episode_id: UUID,
        workspace_id: UUID,
        session_id: UUID,
        decision_index: int,
        environment_version: str,
        observation_implementation: ImplementationRefV1,
        ledger_seq: int,
        ledger_event_id: UUID | None,
        ledger_hash: str,
        terminal: bool,
        terminal_reason: str | None,
        sources: tuple[ObservationSourceV1, ...],
        features: tuple[ObservationFeatureV1, ...],
    ) -> MarlObservationV1:
        sources_hash = canonical_hash([_dump(item) for item in sources])
        features_hash = canonical_hash([_dump(item) for item in features])
        item = cls(
            observation_id=observation_id,
            episode_id=episode_id,
            workspace_id=workspace_id,
            session_id=session_id,
            decision_index=decision_index,
            environment_version=environment_version,
            observation_implementation=observation_implementation,
            ledger_seq=ledger_seq,
            ledger_event_id=ledger_event_id,
            ledger_hash=ledger_hash,
            terminal=terminal,
            terminal_reason=terminal_reason,
            sources=sources,
            features=features,
            sources_hash=sources_hash,
            features_hash=features_hash,
            observation_hash="sha256:" + "0" * 64,
        )
        return item.model_copy(
            update={"observation_hash": canonical_hash(_dump(item, exclude={"observation_hash"}))}
        )


class ProposedActionV1(_Frozen):
    schema_version: Literal[1] = 1
    proposal_id: UUID
    episode_id: UUID
    decision_index: int = Field(ge=0)
    observation_id: UUID
    observation_hash: Hash
    policy_implementation: ImplementationRefV1
    seed: int
    kind: ActionKind
    agent_definition_ids: tuple[UUID, ...] = ()
    payload: dict[str, Any]
    action_hash: Hash

    @model_validator(mode="after")
    def ordered_agents(self) -> ProposedActionV1:
        if self.agent_definition_ids != tuple(
            sorted(self.agent_definition_ids, key=lambda x: x.bytes)
        ):
            raise ValueError("agent definition ids must be ordered")
        if len(set(self.agent_definition_ids)) != len(self.agent_definition_ids):
            raise ValueError("agent definition ids must be unique")
        canonical_json(self.payload)
        return self

    @classmethod
    def create(cls, **values: Any) -> ProposedActionV1:
        item = cls(**values, action_hash="sha256:" + "0" * 64)
        return item.model_copy(
            update={"action_hash": canonical_hash(_dump(item, exclude={"action_hash"}))}
        )


class ExecutedActionV1(_Frozen):
    schema_version: Literal[1] = 1
    execution_id: UUID
    episode_id: UUID
    decision_index: int = Field(ge=0)
    kind: ActionKind
    agent_definition_ids: tuple[UUID, ...] = ()
    payload: dict[str, Any]
    executed_action_hash: Hash

    @model_validator(mode="after")
    def ordered_agents(self) -> ExecutedActionV1:
        if self.agent_definition_ids != tuple(
            sorted(self.agent_definition_ids, key=lambda x: x.bytes)
        ):
            raise ValueError("agent definition ids must be ordered")
        canonical_json(self.payload)
        return self

    @classmethod
    def create(cls, **values: Any) -> ExecutedActionV1:
        item = cls(**values, executed_action_hash="sha256:" + "0" * 64)
        return item.model_copy(
            update={
                "executed_action_hash": canonical_hash(
                    _dump(item, exclude={"executed_action_hash"})
                )
            }
        )


class CoordinatorDecisionV1(_Frozen):
    schema_version: Literal[1] = 1
    decision_id: UUID
    episode_id: UUID
    decision_index: int = Field(ge=0)
    observation_hash: Hash
    proposal_hash: Hash | None
    outcome: DecisionOutcome
    reason: ReasonCode
    coordinator_implementation: ImplementationRefV1
    executed_action_hash: Hash | None
    feasibility_status: Literal["SAT", "UNSAT", "UNKNOWN"]
    decision_hash: Hash

    _reason = field_validator("reason")(_reason)

    @model_validator(mode="after")
    def decision_shape(self) -> CoordinatorDecisionV1:
        if self.outcome is DecisionOutcome.NO_PROPOSAL and self.proposal_hash is not None:
            raise ValueError("NO_PROPOSAL cannot reference a proposal")
        if self.outcome is DecisionOutcome.ACCEPTED and self.executed_action_hash is None:
            raise ValueError("accepted decision requires executed action")
        if self.outcome is not DecisionOutcome.ACCEPTED and self.executed_action_hash is not None:
            raise ValueError("only accepted decision may execute an action")
        if self.feasibility_status == "UNSAT" and self.outcome is DecisionOutcome.ACCEPTED:
            raise ValueError("UNSAT proposals cannot be accepted")
        if self.feasibility_status == "UNKNOWN" and self.outcome is DecisionOutcome.ACCEPTED:
            raise ValueError("UNKNOWN proposals must remain deferred")
        return self

    @classmethod
    def create(cls, **values: Any) -> CoordinatorDecisionV1:
        item = cls(**values, decision_hash="sha256:" + "0" * 64)
        return item.model_copy(
            update={"decision_hash": canonical_hash(_dump(item, exclude={"decision_hash"}))}
        )


class RewardComponentV1(_Frozen):
    schema_version: Literal[1] = 1
    component_id: UUID
    episode_id: UUID
    decision_index: int = Field(ge=0)
    ordinal: int = Field(ge=0, le=4)
    metric_id: Identifier
    metric_version: Identifier
    reward_implementation: ImplementationRefV1
    direction: RewardDirection
    pre_metric_value: RationalV1 | None
    post_metric_value: RationalV1 | None
    reward_value: RationalV1
    status: RewardStatus
    neutral_reason: ReasonCode | None
    source_hashes: tuple[Hash, ...]
    component_hash: Hash

    _metric_id = field_validator("metric_id")(_identifier)
    _metric_version = field_validator("metric_version")(_version)

    @model_validator(mode="after")
    def reward_shape(self) -> RewardComponentV1:
        if tuple(sorted(self.source_hashes)) != self.source_hashes:
            raise ValueError("reward sources must be ordered")
        if self.status is RewardStatus.OBSERVED:
            if self.pre_metric_value is None or self.post_metric_value is None:
                raise ValueError("observed reward requires exact pre/post values")
            if self.neutral_reason is not None:
                raise ValueError("observed reward cannot have neutral reason")
        elif self.reward_value != RationalV1.zero() or self.neutral_reason is None:
            raise ValueError("neutral reward must be zero and have a reason")
        return self

    @classmethod
    def create(cls, **values: Any) -> RewardComponentV1:
        item = cls(**values, component_hash="sha256:" + "0" * 64)
        return item.model_copy(
            update={"component_hash": canonical_hash(_dump(item, exclude={"component_hash"}))}
        )


class CreditAssignmentV1(_Frozen):
    schema_version: Literal[1] = 1
    credit_id: UUID
    episode_id: UUID
    decision_index: int = Field(ge=0)
    reward_component_id: UUID
    reward_component_hash: Hash
    status: CreditStatus
    agent_definition_ids: tuple[UUID, ...]
    source_hashes: tuple[Hash, ...]
    share: RationalV1
    credited_value: RationalV1
    credit_implementation: ImplementationRefV1
    credit_hash: Hash

    @model_validator(mode="after")
    def credit_shape(self) -> CreditAssignmentV1:
        if self.agent_definition_ids != tuple(
            sorted(self.agent_definition_ids, key=lambda x: x.bytes)
        ):
            raise ValueError("credit agent ids must be ordered")
        if tuple(sorted(self.source_hashes)) != self.source_hashes:
            raise ValueError("credit source hashes must be ordered")
        if self.status is CreditStatus.NEUTRAL and (
            self.agent_definition_ids or self.credited_value != RationalV1.zero()
        ):
            raise ValueError("neutral credit has no agents and exactly zero value")
        if self.status is CreditStatus.SHARED and len(self.agent_definition_ids) < 2:
            raise ValueError("shared credit requires at least two agents")
        return self

    @classmethod
    def create(cls, **values: Any) -> CreditAssignmentV1:
        item = cls(**values, credit_hash="sha256:" + "0" * 64)
        return item.model_copy(
            update={"credit_hash": canonical_hash(_dump(item, exclude={"credit_hash"}))}
        )


class DecisionBoundaryV1(_Frozen):
    schema_version: Literal[1] = 1
    record_type: Literal["decision_boundary"] = "decision_boundary"
    episode_id: UUID
    decision_index: int = Field(ge=0)
    observation: MarlObservationV1
    proposed_action: ProposedActionV1 | None
    coordinator_decision: CoordinatorDecisionV1
    executed_action: ExecutedActionV1 | None
    boundary_hash: Hash

    @model_validator(mode="after")
    def references(self) -> DecisionBoundaryV1:
        episode_refs = [
            self.observation.episode_id,
            self.coordinator_decision.episode_id,
            *([self.proposed_action.episode_id] if self.proposed_action is not None else []),
            *([self.executed_action.episode_id] if self.executed_action is not None else []),
        ]
        index_refs = [
            self.observation.decision_index,
            self.coordinator_decision.decision_index,
            *([self.proposed_action.decision_index] if self.proposed_action is not None else []),
            *([self.executed_action.decision_index] if self.executed_action is not None else []),
        ]
        if any(item != self.episode_id for item in episode_refs):
            raise ValueError("boundary episode references differ")
        if any(item != self.decision_index for item in index_refs):
            raise ValueError("boundary decision indices differ")
        if self.observation.terminal:
            raise ValueError("decision boundary observation cannot be terminal")
        if (self.proposed_action is None) != (
            self.coordinator_decision.outcome is DecisionOutcome.NO_PROPOSAL
        ):
            raise ValueError("proposal and coordinator decision shape differ")
        if (self.executed_action is None) != (
            self.coordinator_decision.outcome is not DecisionOutcome.ACCEPTED
        ):
            raise ValueError("execution and coordinator decision shape differ")
        return self

    @classmethod
    def create(cls, **values: Any) -> DecisionBoundaryV1:
        item = cls(**values, boundary_hash="sha256:" + "0" * 64)
        return item.model_copy(
            update={"boundary_hash": canonical_hash(_dump(item, exclude={"boundary_hash"}))}
        )


class TransitionV1(_Frozen):
    schema_version: Literal[1] = 1
    record_type: Literal["transition"] = "transition"
    episode_id: UUID
    decision_index: int = Field(ge=0)
    boundary: DecisionBoundaryV1
    post_observation: MarlObservationV1
    rewards: tuple[RewardComponentV1, ...]
    credits: tuple[CreditAssignmentV1, ...]
    terminal: bool
    transition_hash: Hash

    @model_validator(mode="after")
    def transition_shape(self) -> TransitionV1:
        if self.boundary.episode_id != self.episode_id:
            raise ValueError("transition boundary episode differs")
        if self.boundary.decision_index != self.decision_index:
            raise ValueError("transition boundary index differs")
        if self.post_observation.episode_id != self.episode_id:
            raise ValueError("post-observation episode differs")
        if self.post_observation.decision_index != self.decision_index + 1:
            raise ValueError("post-observation index must follow the boundary")
        if self.post_observation.ledger_seq < self.boundary.observation.ledger_seq:
            raise ValueError("post-observation watermark cannot move backwards")
        if self.terminal != self.post_observation.terminal:
            raise ValueError("terminal transition requires terminal post-observation")
        if tuple(item.ordinal for item in self.rewards) != tuple(range(5)):
            raise ValueError("reward vector must contain exactly five ordered components")
        if len({item.component_id for item in self.rewards}) != 5:
            raise ValueError("reward component identities must be unique")
        self._validate_credit_conservation()
        return self

    def _validate_credit_conservation(self) -> None:
        by_component = {item.component_id: item for item in self.rewards}
        grouped: dict[UUID, list[CreditAssignmentV1]] = {item: [] for item in by_component}
        for credit in self.credits:
            component = by_component.get(credit.reward_component_id)
            if component is None or component.component_hash != credit.reward_component_hash:
                raise ValueError("credit must reference an exact reward component")
            grouped[credit.reward_component_id].append(credit)
        for component_id, component in by_component.items():
            credits = grouped[component_id]
            if component.status is not RewardStatus.OBSERVED:
                if len(credits) != 1 or credits[0].status is not CreditStatus.NEUTRAL:
                    raise ValueError("neutral component requires one explicit neutral credit")
            elif not credits:
                raise ValueError("observed component requires credit")
            total = sum((item.credited_value.fraction() for item in credits), Fraction())
            if total != component.reward_value.fraction():
                raise ValueError("credits must conserve the exact component reward")

    @classmethod
    def create(cls, **values: Any) -> TransitionV1:
        item = cls(**values, transition_hash="sha256:" + "0" * 64)
        return item.model_copy(
            update={"transition_hash": canonical_hash(_dump(item, exclude={"transition_hash"}))}
        )


class IncompleteMarkerV1(_Frozen):
    schema_version: Literal[1] = 1
    record_type: Literal["incomplete"] = "incomplete"
    marker_id: UUID
    episode_id: UUID
    open_decision_index: int = Field(ge=0)
    reason: ReasonCode
    boundary_hash: Hash | None
    incomplete_hash: Hash

    _reason = field_validator("reason")(_reason)

    @classmethod
    def create(cls, **values: Any) -> IncompleteMarkerV1:
        item = cls(**values, incomplete_hash="sha256:" + "0" * 64)
        return item.model_copy(
            update={"incomplete_hash": canonical_hash(_dump(item, exclude={"incomplete_hash"}))}
        )


class MarlEpisodeV1(_Frozen):
    schema_version: Literal[1] = 1
    episode_id: UUID
    workspace_id: UUID
    session_id: UUID
    environment_version: Identifier
    code_identity: Hash
    status: EpisodeStatus
    transitions: tuple[TransitionV1, ...] = ()
    pending_boundary: DecisionBoundaryV1 | None = None
    incomplete_marker: IncompleteMarkerV1 | None = None

    _environment = field_validator("environment_version")(_identifier)

    @field_validator("transitions")
    @classmethod
    def unique_transition_identities(
        cls, values: tuple[TransitionV1, ...]
    ) -> tuple[TransitionV1, ...]:
        hashes = tuple(item.transition_hash for item in values)
        if len(hashes) != len(set(hashes)):
            raise ValueError("transition identities must be unique")
        return values

    @model_validator(mode="after")
    def lifecycle(self) -> MarlEpisodeV1:
        indexes = tuple(item.decision_index for item in self.transitions)
        if indexes != tuple(range(len(indexes))):
            raise ValueError("transition decision indices must be gapless and ordered")
        if any(item.episode_id != self.episode_id for item in self.transitions):
            raise ValueError("transition belongs to another episode")
        if any(
            item.boundary.observation.workspace_id != self.workspace_id
            or item.boundary.observation.session_id != self.session_id
            or item.post_observation.workspace_id != self.workspace_id
            or item.post_observation.session_id != self.session_id
            for item in self.transitions
        ):
            raise ValueError("transition scope differs from episode scope")
        if self.pending_boundary is not None and (
            self.pending_boundary.observation.workspace_id != self.workspace_id
            or self.pending_boundary.observation.session_id != self.session_id
        ):
            raise ValueError("pending boundary scope differs from episode scope")
        if self.status is EpisodeStatus.OPEN:
            if self.incomplete_marker is not None:
                raise ValueError("open episode cannot contain incomplete marker")
            if self.pending_boundary is not None and self.pending_boundary.decision_index != len(
                self.transitions
            ):
                raise ValueError("pending boundary must be the next decision")
        elif self.status is EpisodeStatus.COMPLETE:
            if not self.transitions or not self.transitions[-1].terminal:
                raise ValueError("complete episode requires a terminal final transition")
            if self.pending_boundary is not None or self.incomplete_marker is not None:
                raise ValueError("complete episode cannot have open state")
        else:
            if self.incomplete_marker is None:
                raise ValueError("incomplete episode requires marker")
            if self.incomplete_marker.open_decision_index != len(self.transitions):
                raise ValueError("incomplete marker must identify the first unclosed decision")
            if (self.pending_boundary is None) != (self.incomplete_marker.boundary_hash is None):
                raise ValueError("incomplete marker boundary identity is inconsistent")
            if self.pending_boundary is not None and (
                self.pending_boundary.boundary_hash != self.incomplete_marker.boundary_hash
            ):
                raise ValueError("incomplete marker does not identify pending boundary")
        return self


def episode_hash(episode: MarlEpisodeV1) -> str:
    """Hash the closed episode identity preimage (metadata plus ordered record identities)."""
    return canonical_hash(
        {
            "code_identity": episode.code_identity,
            "environment_version": episode.environment_version,
            "episode_id": str(episode.episode_id),
            "incomplete_hash": (
                episode.incomplete_marker.incomplete_hash
                if episode.incomplete_marker is not None
                else None
            ),
            "pending_boundary_hash": (
                episode.pending_boundary.boundary_hash
                if episode.pending_boundary is not None
                else None
            ),
            "schema_version": episode.schema_version,
            "session_id": str(episode.session_id),
            "status": episode.status.value,
            "transition_hashes": [item.transition_hash for item in episode.transitions],
            "workspace_id": str(episode.workspace_id),
        }
    )


class TrajectoryManifestV1(_Frozen):
    schema_version: Literal[1] = 1
    episode_id: UUID
    episode_status: EpisodeStatus
    environment_version: Identifier
    code_identity: Hash
    observation_implementations: tuple[ImplementationRefV1, ...]
    reward_implementations: tuple[ImplementationRefV1, ...]
    credit_implementations: tuple[ImplementationRefV1, ...]
    coordinator_implementations: tuple[ImplementationRefV1, ...]
    trajectory_sha256: Hash
    trajectory_byte_length: int = Field(ge=0)
    record_count: int = Field(ge=0)
    episode_hash: Hash

    _environment = field_validator("environment_version")(_identifier)


class ReplayFailureV1(_Frozen):
    code: FailureCode
    stage: VerificationStage
    file: Literal["bundle", "manifest.json", "trajectory.jsonl"]
    line: int | None = Field(default=None, ge=1)
    decision_index: int | None = Field(default=None, ge=0)
    json_pointer: str | None = None
    detail: str
    expected_hash: Hash | None = None
    actual_hash: Hash | None = None


class ReplayVerificationV1(_Frozen):
    schema_version: Literal[1] = 1
    outcome: ReplayOutcome
    integrity_valid: bool
    replay_verified: bool
    episode_id: UUID | None
    checked_record_count: int = Field(ge=0)
    expected_trajectory_hash: Hash | None = None
    actual_trajectory_hash: Hash | None = None
    expected_episode_hash: Hash | None = None
    actual_episode_hash: Hash | None = None
    first_failure: ReplayFailureV1 | None = None

    @model_validator(mode="after")
    def result_shape(self) -> ReplayVerificationV1:
        if self.outcome is ReplayOutcome.VERIFIED and (
            not self.integrity_valid or not self.replay_verified or self.first_failure is not None
        ):
            raise ValueError("verified result shape is invalid")
        if self.outcome is not ReplayOutcome.VERIFIED and self.first_failure is None:
            raise ValueError("non-verified result requires one first failure")
        return self


class MarlDomainError(RuntimeError):
    """Safe deterministic trajectory-domain failure."""


class MarlConflictError(MarlDomainError):
    """An immutable identity was reused with different canonical content."""


@runtime_checkable
class MarlEnvironment(Protocol):
    async def observe(self, episode: MarlEpisodeV1, decision_index: int) -> MarlObservationV1: ...

    async def propose(self, observation: MarlObservationV1) -> ProposedActionV1 | None: ...


@runtime_checkable
class MarlTrajectoryStore(Protocol):
    async def create(self, episode: MarlEpisodeV1) -> MarlEpisodeV1: ...

    async def get(self, workspace_id: UUID, episode_id: UUID) -> MarlEpisodeV1 | None: ...

    async def capture(self, workspace_id: UUID, boundary: DecisionBoundaryV1) -> MarlEpisodeV1: ...

    async def close(self, workspace_id: UUID, transition: TransitionV1) -> MarlEpisodeV1: ...

    async def finalize_complete(self, workspace_id: UUID, episode_id: UUID) -> MarlEpisodeV1: ...

    async def finalize_incomplete(
        self, workspace_id: UUID, marker: IncompleteMarkerV1
    ) -> MarlEpisodeV1: ...
