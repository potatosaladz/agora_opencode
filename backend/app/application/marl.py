"""Phase 12 trajectory lifecycle, canonical export, and hermetic verification."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.domain.marl import (
    SCHEMA_VERSION,
    CoordinatorDecisionV1,
    DecisionBoundaryV1,
    EpisodeStatus,
    FailureCode,
    ImplementationRefV1,
    IncompleteMarkerV1,
    MarlEpisodeV1,
    MarlTrajectoryStore,
    ReplayFailureV1,
    ReplayOutcome,
    ReplayVerificationV1,
    RewardComponentV1,
    RewardDirection,
    RewardStatus,
    SourceSnapshotV1,
    TrajectoryManifestV1,
    TransitionV1,
    VerificationStage,
    canonical_hash,
    episode_hash,
    validate_hash,
)
from app.domain.reasoning import canonical_json

__all__ = [
    "BundleLimits",
    "CanonicalTrajectoryBundle",
    "ImplementationRegistry",
    "MarlTrajectoryService",
    "RewardInputV1",
    "build_reward_vector",
    "export_episode",
    "verify_bundle",
]

TRAJECTORY_FILE = "trajectory.jsonl"
MANIFEST_FILE = "manifest.json"
REWARD_SPECS = (
    ("ep-02", "1", "agora.reward.provenance-delta", RewardDirection.HIGHER_BETTER),
    ("dh-03", "1", "agora.reward.attack-coverage-delta", RewardDirection.HIGHER_BETTER),
    ("dh-02", "1", "agora.reward.disagreement-retention-delta", RewardDirection.NO_DIRECTION),
    ("cq-03", "1", "agora.reward.flip-distance-delta", RewardDirection.HIGHER_BETTER),
    ("ce-03", "1", "agora.reward.cost-delta", RewardDirection.LOWER_BETTER),
)


@dataclass(frozen=True, slots=True)
class BundleLimits:
    max_manifest_bytes: int = 256 * 1024
    max_trajectory_bytes: int = 64 * 1024 * 1024
    max_records: int = 100_000
    max_json_depth: int = 64
    max_string_length: int = 1_048_576
    max_array_items: int = 100_000


@dataclass(frozen=True, slots=True)
class CanonicalTrajectoryBundle:
    manifest: bytes
    trajectory: bytes

    @property
    def entries(self) -> Mapping[str, bytes]:
        return {MANIFEST_FILE: self.manifest, TRAJECTORY_FILE: self.trajectory}


@dataclass(frozen=True, slots=True)
class RewardInputV1:
    pre_value: Any | None
    post_value: Any | None
    status: RewardStatus
    neutral_reason: str | None
    source_hashes: tuple[str, ...]


def _dump(model: BaseModel, *, exclude: set[str] | None = None) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude=exclude or set())


FeatureImplementation = Callable[[SourceSnapshotV1], Any]
RewardImplementation = Callable[[Any, Any, RewardDirection], Any]
CoordinatorImplementation = Callable[[DecisionBoundaryV1], CoordinatorDecisionV1]


class ImplementationRegistry:
    """Caller-provided, immutable-by-convention local replay implementation registry."""

    def __init__(self) -> None:
        self._features: dict[tuple[str, str], FeatureImplementation] = {}
        self._rewards: dict[tuple[str, str], RewardImplementation] = {}
        self._coordinators: dict[tuple[str, str], CoordinatorImplementation] = {}
        self._credits: set[tuple[str, str]] = set()

    def register_feature(self, ref: ImplementationRefV1, function: FeatureImplementation) -> None:
        self._insert(self._features, ref, function)

    def register_reward(self, ref: ImplementationRefV1, function: RewardImplementation) -> None:
        self._insert(self._rewards, ref, function)

    def register_coordinator(
        self, ref: ImplementationRefV1, function: CoordinatorImplementation
    ) -> None:
        self._insert(self._coordinators, ref, function)

    def register_credit(self, ref: ImplementationRefV1) -> None:
        key = self._key(ref)
        if key in self._credits:
            raise ValueError("duplicate credit implementation")
        self._credits.add(key)

    @staticmethod
    def _key(ref: ImplementationRefV1) -> tuple[str, str]:
        return ref.implementation_id, ref.implementation_version

    @staticmethod
    def _insert(
        target: dict[tuple[str, str], Any], ref: ImplementationRefV1, function: Any
    ) -> None:
        key = ImplementationRegistry._key(ref)
        if key in target:
            raise ValueError("duplicate implementation")
        target[key] = function

    def feature(self, ref: ImplementationRefV1) -> FeatureImplementation | None:
        return self._features.get(self._key(ref))

    def reward(self, ref: ImplementationRefV1) -> RewardImplementation | None:
        return self._rewards.get(self._key(ref))

    def coordinator(self, ref: ImplementationRefV1) -> CoordinatorImplementation | None:
        return self._coordinators.get(self._key(ref))

    def has_credit(self, ref: ImplementationRefV1) -> bool:
        return self._key(ref) in self._credits


def exact_delta(pre: Any, post: Any, direction: RewardDirection) -> Any:
    """Default exact rational delta implementation used by the five Phase 12 components."""
    from app.domain.marl import RationalV1

    if not isinstance(pre, RationalV1) or not isinstance(post, RationalV1):
        raise TypeError("reward implementation requires exact rationals")
    difference = post.fraction() - pre.fraction()
    if direction is RewardDirection.LOWER_BETTER:
        difference = -difference
    return RationalV1.from_fraction(difference)


def build_reward_vector(
    *,
    episode_id: UUID,
    decision_index: int,
    component_ids: tuple[UUID, UUID, UUID, UUID, UUID],
    inputs: tuple[RewardInputV1, RewardInputV1, RewardInputV1, RewardInputV1, RewardInputV1],
) -> tuple[RewardComponentV1, ...]:
    """Compute the fixed five-component vector without a scalar aggregate."""
    from app.domain.marl import RationalV1

    values: list[RewardComponentV1] = []
    for ordinal, (identity, reward_input, spec) in enumerate(
        zip(component_ids, inputs, REWARD_SPECS, strict=True)
    ):
        metric_id, metric_version, implementation_id, direction = spec
        value = RationalV1.zero()
        if reward_input.status is RewardStatus.OBSERVED:
            value = exact_delta(reward_input.pre_value, reward_input.post_value, direction)
        values.append(
            RewardComponentV1.create(
                component_id=identity,
                episode_id=episode_id,
                decision_index=decision_index,
                ordinal=ordinal,
                metric_id=metric_id,
                metric_version=metric_version,
                reward_implementation=ImplementationRefV1(
                    implementation_id=implementation_id, implementation_version="1"
                ),
                direction=direction,
                pre_metric_value=reward_input.pre_value,
                post_metric_value=reward_input.post_value,
                reward_value=value,
                status=reward_input.status,
                neutral_reason=reward_input.neutral_reason,
                source_hashes=reward_input.source_hashes,
            )
        )
    return tuple(values)


class MarlTrajectoryService:
    """Caller-transaction-owned state-machine orchestration."""

    def __init__(self, store: MarlTrajectoryStore) -> None:
        self._store = store

    async def open(self, episode: MarlEpisodeV1) -> MarlEpisodeV1:
        return await self._store.create(episode)

    async def capture(self, workspace_id: UUID, boundary: DecisionBoundaryV1) -> MarlEpisodeV1:
        return await self._store.capture(workspace_id, boundary)

    async def close(self, workspace_id: UUID, transition: TransitionV1) -> MarlEpisodeV1:
        return await self._store.close(workspace_id, transition)

    async def complete(self, workspace_id: UUID, episode_id: UUID) -> MarlEpisodeV1:
        return await self._store.finalize_complete(workspace_id, episode_id)

    async def incomplete(self, workspace_id: UUID, marker: IncompleteMarkerV1) -> MarlEpisodeV1:
        return await self._store.finalize_incomplete(workspace_id, marker)


def _unique_refs(episode: MarlEpisodeV1, attribute: str) -> tuple[ImplementationRefV1, ...]:
    values: dict[tuple[str, str], ImplementationRefV1] = {}
    for transition in episode.transitions:
        items: tuple[Any, ...]
        if attribute == "observation":
            items = (transition.boundary.observation, transition.post_observation)
            refs = tuple(item.observation_implementation for item in items)
        elif attribute == "reward":
            refs = tuple(item.reward_implementation for item in transition.rewards)
        elif attribute == "credit":
            refs = tuple(item.credit_implementation for item in transition.credits)
        else:
            refs = (transition.boundary.coordinator_decision.coordinator_implementation,)
        for ref in refs:
            values[(ref.implementation_id, ref.implementation_version)] = ref
    return tuple(values[key] for key in sorted(values))


def export_episode(episode: MarlEpisodeV1) -> CanonicalTrajectoryBundle:
    """Export exactly the two canonical Phase 12 files."""
    if episode.status is EpisodeStatus.OPEN:
        raise ValueError("OPEN episode cannot be exported")
    records: list[BaseModel] = list(episode.transitions)
    if episode.pending_boundary is not None:
        records.append(episode.pending_boundary)
    if episode.incomplete_marker is not None:
        records.append(episode.incomplete_marker)
    trajectory = b"".join(canonical_json(_dump(record)) + b"\n" for record in records)
    manifest = TrajectoryManifestV1(
        episode_id=episode.episode_id,
        episode_status=episode.status,
        environment_version=episode.environment_version,
        code_identity=episode.code_identity,
        observation_implementations=_unique_refs(episode, "observation"),
        reward_implementations=_unique_refs(episode, "reward"),
        credit_implementations=_unique_refs(episode, "credit"),
        coordinator_implementations=_unique_refs(episode, "coordinator"),
        trajectory_sha256=f"sha256:{hashlib.sha256(trajectory).hexdigest()}",
        trajectory_byte_length=len(trajectory),
        record_count=len(records),
        episode_hash=episode_hash(episode),
    )
    return CanonicalTrajectoryBundle(
        manifest=canonical_json(_dump(manifest)) + b"\n", trajectory=trajectory
    )


def _failure(
    code: FailureCode,
    stage: VerificationStage,
    file: str,
    detail: str,
    *,
    episode_id: UUID | None = None,
    checked: int = 0,
    line: int | None = None,
    decision_index: int | None = None,
    pointer: str | None = None,
    expected_trajectory: str | None = None,
    actual_trajectory: str | None = None,
    expected_episode: str | None = None,
    actual_episode: str | None = None,
    integrity_valid: bool = False,
    outcome: ReplayOutcome = ReplayOutcome.FAILED,
) -> ReplayVerificationV1:
    return ReplayVerificationV1(
        outcome=outcome,
        integrity_valid=integrity_valid,
        replay_verified=False,
        episode_id=episode_id,
        checked_record_count=checked,
        expected_trajectory_hash=expected_trajectory,
        actual_trajectory_hash=actual_trajectory,
        expected_episode_hash=expected_episode,
        actual_episode_hash=actual_episode,
        first_failure=ReplayFailureV1(
            code=code,
            stage=stage,
            file=cast(Any, file),
            line=line,
            decision_index=decision_index,
            json_pointer=pointer,
            detail=detail,
            expected_hash=expected_episode if code is FailureCode.HASH_MISMATCH else None,
            actual_hash=actual_episode if code is FailureCode.HASH_MISMATCH else None,
        ),
    )


def _depth_and_size(value: Any, *, depth: int, limits: BundleLimits) -> None:
    if depth > limits.max_json_depth:
        raise OverflowError("JSON nesting exceeds limit")
    if isinstance(value, str) and len(value) > limits.max_string_length:
        raise OverflowError("JSON string exceeds limit")
    if isinstance(value, list):
        if len(value) > limits.max_array_items:
            raise OverflowError("JSON array exceeds limit")
        for item in value:
            _depth_and_size(item, depth=depth + 1, limits=limits)
    elif isinstance(value, dict):
        if len(value) > limits.max_array_items:
            raise OverflowError("JSON object exceeds limit")
        for key, item in value.items():
            _depth_and_size(key, depth=depth + 1, limits=limits)
            _depth_and_size(item, depth=depth + 1, limits=limits)


def _parse_file(
    data: bytes, file: str, limits: BundleLimits
) -> tuple[str, Any] | ReplayVerificationV1:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return _failure(FailureCode.INVALID_UTF8, VerificationStage.DECODE, file, "invalid UTF-8")
    has_bom = text.startswith("\ufeff")
    parse_text = text.removeprefix("\ufeff")
    try:
        value = json.loads(
            parse_text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value))
        )
        _depth_and_size(value, depth=0, limits=limits)
    except OverflowError as exc:
        return _failure(
            FailureCode.RESOURCE_LIMIT_EXCEEDED,
            VerificationStage.RESOURCE,
            file,
            str(exc),
        )
    except (json.JSONDecodeError, ValueError):
        return _failure(FailureCode.INVALID_JSON, VerificationStage.PARSE, file, "invalid JSON")
    if has_bom:
        return _failure(
            FailureCode.NONCANONICAL_ENCODING,
            VerificationStage.CANONICAL,
            file,
            "UTF-8 BOM is forbidden",
        )
    return text, value


def _schema_version(value: Any) -> int | None:
    return value.get("schema_version") if isinstance(value, dict) else None


def _validate_child_hashes(transition: TransitionV1) -> None:
    boundary = transition.boundary
    for source in (*boundary.observation.sources, *transition.post_observation.sources):
        validate_hash(source.snapshot, "snapshot_hash")
        validate_hash(source, "source_hash")
    for observation in (boundary.observation, transition.post_observation):
        for feature in observation.features:
            validate_hash(feature, "feature_hash")
        if observation.sources_hash != canonical_hash(
            [_dump(item) for item in observation.sources]
        ):
            raise ValueError("sources hash mismatch")
        if observation.features_hash != canonical_hash(
            [_dump(item) for item in observation.features]
        ):
            raise ValueError("features hash mismatch")
        validate_hash(observation, "observation_hash")
    if boundary.proposed_action is not None:
        validate_hash(boundary.proposed_action, "action_hash")
    if boundary.executed_action is not None:
        validate_hash(boundary.executed_action, "executed_action_hash")
    validate_hash(boundary.coordinator_decision, "decision_hash")
    validate_hash(boundary, "boundary_hash")
    for reward in transition.rewards:
        validate_hash(reward, "component_hash")
    for credit in transition.credits:
        validate_hash(credit, "credit_hash")
    validate_hash(transition, "transition_hash")


def _validate_boundary_hashes(boundary: DecisionBoundaryV1) -> None:
    for source in boundary.observation.sources:
        validate_hash(source.snapshot, "snapshot_hash")
        validate_hash(source, "source_hash")
    for feature in boundary.observation.features:
        validate_hash(feature, "feature_hash")
    validate_hash(boundary.observation, "observation_hash")
    if boundary.proposed_action is not None:
        validate_hash(boundary.proposed_action, "action_hash")
    if boundary.executed_action is not None:
        validate_hash(boundary.executed_action, "executed_action_hash")
    validate_hash(boundary.coordinator_decision, "decision_hash")
    validate_hash(boundary, "boundary_hash")


def _validate_incomplete_hashes(
    boundary: DecisionBoundaryV1, marker: IncompleteMarkerV1 | None
) -> None:
    _validate_boundary_hashes(boundary)
    if marker is None or marker.boundary_hash != boundary.boundary_hash:
        raise ValueError("incomplete marker boundary reference mismatch")
    validate_hash(marker, "incomplete_hash")


def _replay_transition(transition: TransitionV1, registry: ImplementationRegistry) -> None:
    for observation in (transition.boundary.observation, transition.post_observation):
        snapshots = {item.source_hash: item.snapshot for item in observation.sources}
        for feature in observation.features:
            function = registry.feature(
                ImplementationRefV1(
                    implementation_id=feature.feature_id,
                    implementation_version=feature.feature_version,
                )
            )
            if function is None:
                raise LookupError("unknown observation implementation")
            if len(feature.source_hashes) != 1 or feature.source_hashes[0] not in snapshots:
                raise ReferenceError("feature source reference mismatch")
            if function(snapshots[feature.source_hashes[0]]) != feature.value:
                raise RuntimeError("observation feature replay mismatch")
    coordinator = registry.coordinator(
        transition.boundary.coordinator_decision.coordinator_implementation
    )
    if coordinator is None:
        raise LookupError("unknown coordinator implementation")
    if coordinator(transition.boundary) != transition.boundary.coordinator_decision:
        raise RuntimeError("coordinator replay mismatch")
    for reward in transition.rewards:
        reward_function = registry.reward(reward.reward_implementation)
        if reward_function is None:
            raise LookupError("unknown reward implementation")
        if reward.status is RewardStatus.OBSERVED:
            computed = reward_function(
                reward.pre_metric_value, reward.post_metric_value, reward.direction
            )
            if computed != reward.reward_value:
                raise RuntimeError("reward replay mismatch")
    for credit in transition.credits:
        if not registry.has_credit(credit.credit_implementation):
            raise LookupError("unknown credit implementation")


def verify_bundle(
    manifest_bytes: bytes,
    trajectory_bytes: bytes,
    registry: ImplementationRegistry,
    *,
    entry_names: tuple[str, ...] = (MANIFEST_FILE, TRAJECTORY_FILE),
    limits: BundleLimits | None = None,
) -> ReplayVerificationV1:
    """Hermetically verify untrusted canonical bytes with deterministic first failure."""
    limits = limits or BundleLimits()
    if tuple(sorted(entry_names)) != (MANIFEST_FILE, TRAJECTORY_FILE) or len(entry_names) != 2:
        return _failure(
            FailureCode.BUNDLE_ENTRY_SET,
            VerificationStage.BUNDLE,
            "bundle",
            "bundle must contain exactly manifest.json and trajectory.jsonl",
        )
    if (
        len(manifest_bytes) > limits.max_manifest_bytes
        or len(trajectory_bytes) > limits.max_trajectory_bytes
    ):
        return _failure(
            FailureCode.RESOURCE_LIMIT_EXCEEDED,
            VerificationStage.RESOURCE,
            MANIFEST_FILE if len(manifest_bytes) > limits.max_manifest_bytes else TRAJECTORY_FILE,
            "file exceeds configured byte limit",
        )
    parsed_manifest = _parse_file(manifest_bytes, MANIFEST_FILE, limits)
    if isinstance(parsed_manifest, ReplayVerificationV1):
        return parsed_manifest
    _, manifest_value = parsed_manifest
    lines = trajectory_bytes.splitlines(keepends=True)
    if len(lines) > limits.max_records:
        return _failure(
            FailureCode.RESOURCE_LIMIT_EXCEEDED,
            VerificationStage.RESOURCE,
            TRAJECTORY_FILE,
            "record count exceeds configured limit",
        )
    records_raw: list[Any] = []
    for line_number, raw in enumerate(lines, start=1):
        parsed = _parse_file(raw, TRAJECTORY_FILE, limits)
        if isinstance(parsed, ReplayVerificationV1):
            return parsed.model_copy(
                update={
                    "first_failure": parsed.first_failure.model_copy(update={"line": line_number})
                    if parsed.first_failure is not None
                    else None
                }
            )
        _, value = parsed
        records_raw.append(value)
    versions = [
        (MANIFEST_FILE, None, _schema_version(manifest_value)),
        *(
            (TRAJECTORY_FILE, index, _schema_version(value))
            for index, value in enumerate(records_raw, 1)
        ),
    ]
    for version_file, version_line, version in versions:
        if version is not None and version != SCHEMA_VERSION:
            return _failure(
                FailureCode.UNSUPPORTED_SCHEMA_VERSION,
                VerificationStage.SCHEMA,
                version_file,
                "unsupported schema version",
                line=version_line,
            )
    try:
        if (
            not isinstance(manifest_value, dict)
            or manifest_value.get("schema_version") != SCHEMA_VERSION
        ):
            return _failure(
                FailureCode.UNSUPPORTED_SCHEMA_VERSION,
                VerificationStage.SCHEMA,
                MANIFEST_FILE,
                "unsupported schema version",
            )
        manifest = TrajectoryManifestV1.model_validate_json(canonical_json(manifest_value))
        records: list[TransitionV1 | DecisionBoundaryV1 | IncompleteMarkerV1] = []
        for raw in records_raw:
            if not isinstance(raw, dict):
                return _failure(
                    FailureCode.SCHEMA_VIOLATION,
                    VerificationStage.SCHEMA,
                    TRAJECTORY_FILE,
                    "record must be an object",
                )
            record_type = raw.get("record_type")
            if record_type == "incomplete":
                records.append(IncompleteMarkerV1.model_validate_json(canonical_json(raw)))
            elif record_type == "decision_boundary":
                records.append(DecisionBoundaryV1.model_validate_json(canonical_json(raw)))
            else:
                records.append(TransitionV1.model_validate_json(canonical_json(raw)))
    except (ValidationError, ValueError):
        return _failure(
            FailureCode.SCHEMA_VIOLATION,
            VerificationStage.SCHEMA,
            MANIFEST_FILE,
            "closed schema validation failed",
        )
    if manifest_bytes != canonical_json(_dump(manifest)) + b"\n":
        return _failure(
            FailureCode.NONCANONICAL_ENCODING,
            VerificationStage.CANONICAL,
            MANIFEST_FILE,
            "manifest is not one JCS object with final LF",
            episode_id=manifest.episode_id,
        )
    if any(not line.endswith(b"\n") for line in lines) or trajectory_bytes != b"".join(
        canonical_json(raw) + b"\n" for raw in records_raw
    ):
        return _failure(
            FailureCode.NONCANONICAL_ENCODING,
            VerificationStage.CANONICAL,
            TRAJECTORY_FILE,
            "trajectory records must be JCS with LF",
            episode_id=manifest.episode_id,
        )
    actual_trajectory = f"sha256:{hashlib.sha256(trajectory_bytes).hexdigest()}"
    if (
        manifest.trajectory_sha256 != actual_trajectory
        or manifest.trajectory_byte_length != len(trajectory_bytes)
        or manifest.record_count != len(records)
    ):
        return _failure(
            FailureCode.MANIFEST_MISMATCH,
            VerificationStage.MANIFEST,
            MANIFEST_FILE,
            "trajectory digest, length, or count differs",
            episode_id=manifest.episode_id,
            expected_trajectory=manifest.trajectory_sha256,
            actual_trajectory=actual_trajectory,
        )
    transitions = tuple(item for item in records if isinstance(item, TransitionV1))
    boundaries = tuple(item for item in records if isinstance(item, DecisionBoundaryV1))
    markers = tuple(item for item in records if isinstance(item, IncompleteMarkerV1))
    record_episode_ids = (
        *(item.episode_id for item in transitions),
        *(item.episode_id for item in boundaries),
        *(item.episode_id for item in markers),
    )
    if (
        tuple(item.decision_index for item in transitions) != tuple(range(len(transitions)))
        or len(boundaries) > 1
        or len(markers) > 1
        or (boundaries and boundaries[0].decision_index != len(transitions))
        or (boundaries and (not markers or records[-2:] != [boundaries[0], markers[0]]))
        or (markers and records[-1] is not markers[0])
    ):
        return _failure(
            FailureCode.ORDER_VIOLATION,
            VerificationStage.ORDER,
            TRAJECTORY_FILE,
            "decision indices must be gapless and incomplete marker last",
            episode_id=manifest.episode_id,
        )
    for index, transition in enumerate(transitions):
        try:
            _validate_child_hashes(transition)
        except ValueError as exc:
            return _failure(
                FailureCode.HASH_MISMATCH,
                VerificationStage.HASH,
                TRAJECTORY_FILE,
                str(exc),
                episode_id=manifest.episode_id,
                checked=index,
                line=index + 1,
                decision_index=transition.decision_index,
                expected_trajectory=manifest.trajectory_sha256,
                actual_trajectory=actual_trajectory,
            )
    if boundaries:
        try:
            _validate_incomplete_hashes(boundaries[0], markers[0] if markers else None)
        except ValueError as exc:
            return _failure(
                FailureCode.HASH_MISMATCH,
                VerificationStage.HASH,
                TRAJECTORY_FILE,
                str(exc),
                episode_id=manifest.episode_id,
                checked=len(transitions),
                line=len(transitions) + 1,
                decision_index=boundaries[0].decision_index,
                expected_trajectory=manifest.trajectory_sha256,
                actual_trajectory=actual_trajectory,
            )
    if any(item != manifest.episode_id for item in record_episode_ids):
        return _failure(
            FailureCode.REFERENCE_MISMATCH,
            VerificationStage.REFERENCE,
            TRAJECTORY_FILE,
            "record episode id differs from manifest",
            episode_id=manifest.episode_id,
        )
    if transitions and any(
        item.boundary.observation.environment_version != manifest.environment_version
        or item.post_observation.environment_version != manifest.environment_version
        for item in transitions
    ):
        return _failure(
            FailureCode.REFERENCE_MISMATCH,
            VerificationStage.REFERENCE,
            TRAJECTORY_FILE,
            "record environment version differs from manifest",
            episode_id=manifest.episode_id,
        )
    pending = boundaries[0] if boundaries else None
    marker = markers[0] if markers else None
    try:
        episode = MarlEpisodeV1(
            episode_id=manifest.episode_id,
            workspace_id=transitions[0].boundary.observation.workspace_id,
            session_id=transitions[0].boundary.observation.session_id,
            environment_version=manifest.environment_version,
            code_identity=manifest.code_identity,
            status=manifest.episode_status,
            transitions=transitions,
            pending_boundary=pending,
            incomplete_marker=marker,
        )
    except (ValidationError, IndexError):
        return _failure(
            FailureCode.REFERENCE_MISMATCH,
            VerificationStage.REFERENCE,
            TRAJECTORY_FILE,
            "episode references or lifecycle are inconsistent",
            episode_id=manifest.episode_id,
        )
    actual_episode = episode_hash(episode)
    if actual_episode != manifest.episode_hash:
        return _failure(
            FailureCode.HASH_MISMATCH,
            VerificationStage.HASH,
            MANIFEST_FILE,
            "episode hash differs",
            episode_id=manifest.episode_id,
            checked=len(transitions),
            expected_trajectory=manifest.trajectory_sha256,
            actual_trajectory=actual_trajectory,
            expected_episode=manifest.episode_hash,
            actual_episode=actual_episode,
        )
    for index, transition in enumerate(transitions):
        try:
            _replay_transition(transition, registry)
        except LookupError as exc:
            return _failure(
                FailureCode.UNKNOWN_IMPLEMENTATION,
                VerificationStage.IMPLEMENTATION,
                TRAJECTORY_FILE,
                str(exc),
                episode_id=manifest.episode_id,
                checked=index,
                line=index + 1,
                decision_index=transition.decision_index,
                expected_trajectory=manifest.trajectory_sha256,
                actual_trajectory=actual_trajectory,
                expected_episode=manifest.episode_hash,
                actual_episode=actual_episode,
                integrity_valid=True,
            )
        except (ReferenceError, RuntimeError) as exc:
            return _failure(
                FailureCode.REPLAY_MISMATCH,
                VerificationStage.REPLAY,
                TRAJECTORY_FILE,
                str(exc),
                episode_id=manifest.episode_id,
                checked=index,
                line=index + 1,
                decision_index=transition.decision_index,
                expected_trajectory=manifest.trajectory_sha256,
                actual_trajectory=actual_trajectory,
                expected_episode=manifest.episode_hash,
                actual_episode=actual_episode,
                integrity_valid=True,
            )
    if episode.status is EpisodeStatus.INCOMPLETE:
        return _failure(
            FailureCode.EPISODE_INCOMPLETE,
            VerificationStage.COMPLETENESS,
            TRAJECTORY_FILE,
            "trajectory is authentic but episode is incomplete",
            episode_id=manifest.episode_id,
            checked=len(records),
            line=len(records),
            expected_trajectory=manifest.trajectory_sha256,
            actual_trajectory=actual_trajectory,
            expected_episode=manifest.episode_hash,
            actual_episode=actual_episode,
            integrity_valid=True,
            outcome=ReplayOutcome.INCOMPLETE,
        )
    return ReplayVerificationV1(
        outcome=ReplayOutcome.VERIFIED,
        integrity_valid=True,
        replay_verified=True,
        episode_id=manifest.episode_id,
        checked_record_count=len(records),
        expected_trajectory_hash=manifest.trajectory_sha256,
        actual_trajectory_hash=actual_trajectory,
        expected_episode_hash=manifest.episode_hash,
        actual_episode_hash=actual_episode,
        first_failure=None,
    )
