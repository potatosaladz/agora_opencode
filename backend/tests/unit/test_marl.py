"""Focused deterministic Phase 12 MARL acceptance tests."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from app.adapters.inmemory.marl import InMemoryMarlTrajectoryStore
from app.application.marl import (
    BundleLimits,
    ImplementationRegistry,
    MarlTrajectoryService,
    RewardInputV1,
    build_reward_vector,
    exact_delta,
    export_episode,
    verify_bundle,
)
from app.domain.marl import (
    ActionKind,
    CanonicalDecimal,
    CoordinatorDecisionV1,
    CreditAssignmentV1,
    CreditStatus,
    DecisionBoundaryV1,
    DecisionOutcome,
    EpisodeStatus,
    ExecutedActionV1,
    FailureCode,
    ImplementationRefV1,
    IncompleteMarkerV1,
    MarlConflictError,
    MarlDomainError,
    MarlEpisodeV1,
    MarlObservationV1,
    MarlTrajectoryStore,
    ObservationFeatureV1,
    ObservationSourceV1,
    ProposedActionV1,
    RationalV1,
    ReplayOutcome,
    RewardStatus,
    SourceSnapshotV1,
    TransitionV1,
    canonical_hash,
)
from tests.traceability import req

U = UUID
WORKSPACE = U("00000000-0000-0000-0000-000000000001")
SESSION = U("00000000-0000-0000-0000-000000000002")
EPISODE = U("00000000-0000-0000-0000-000000000003")
AGENT = U("00000000-0000-0000-0000-000000000004")
ZERO_HASH = "sha256:" + "0" * 64
CODE_HASH = "sha256:" + "c" * 64
FIXTURES = Path(__file__).parents[1] / "fixtures" / "marl"
OBS_IMPL = ImplementationRefV1(
    implementation_id="agora.observation.scalar", implementation_version="1"
)
COORD_IMPL = ImplementationRefV1(
    implementation_id="agora.coordinator.rules", implementation_version="1"
)
CREDIT_IMPL = ImplementationRefV1(
    implementation_id="agora.credit.provenance", implementation_version="1"
)


def _observation(
    index: int,
    value: int,
    *,
    terminal: bool = False,
    workspace_id: UUID = WORKSPACE,
    session_id: UUID = SESSION,
) -> MarlObservationV1:
    snapshot = SourceSnapshotV1.create(
        source_id=U(f"00000000-0000-0000-0001-{index + 1:012d}"),
        source_kind="scalar",
        source_version=1,
        payload={"value": value},
    )
    source = ObservationSourceV1.create(ordinal=0, snapshot=snapshot)
    feature = ObservationFeatureV1.create(
        feature_id="agora.observation.scalar",
        feature_version="1",
        value=value,
        source_hashes=(source.source_hash,),
    )
    return MarlObservationV1.create(
        observation_id=U(f"00000000-0000-0000-0002-{index + 1:012d}"),
        episode_id=EPISODE,
        workspace_id=workspace_id,
        session_id=session_id,
        decision_index=index,
        environment_version="agora-marl-v1",
        observation_implementation=OBS_IMPL,
        ledger_seq=index,
        ledger_event_id=None,
        ledger_hash=ZERO_HASH,
        terminal=terminal,
        terminal_reason="SESSION_COMPLETE" if terminal else None,
        sources=(source,),
        features=(feature,),
    )


def _boundary(index: int, observation: MarlObservationV1) -> DecisionBoundaryV1:
    proposal = ProposedActionV1.create(
        proposal_id=U(f"00000000-0000-0000-0003-{index + 1:012d}"),
        episode_id=EPISODE,
        decision_index=index,
        observation_id=observation.observation_id,
        observation_hash=observation.observation_hash,
        policy_implementation=ImplementationRefV1(
            implementation_id="agora.policy.fixture", implementation_version="1"
        ),
        seed=7,
        kind=ActionKind.SPEAK,
        agent_definition_ids=(AGENT,),
        payload={"turn_type": "ARGUE"},
    )
    executed = ExecutedActionV1.create(
        execution_id=U(f"00000000-0000-0000-0004-{index + 1:012d}"),
        episode_id=EPISODE,
        decision_index=index,
        kind=ActionKind.SPEAK,
        agent_definition_ids=(AGENT,),
        payload={"turn_type": "ARGUE"},
    )
    decision = CoordinatorDecisionV1.create(
        decision_id=U(f"00000000-0000-0000-0005-{index + 1:012d}"),
        episode_id=EPISODE,
        decision_index=index,
        observation_hash=observation.observation_hash,
        proposal_hash=proposal.action_hash,
        outcome=DecisionOutcome.ACCEPTED,
        reason="POLICY_VALID",
        coordinator_implementation=COORD_IMPL,
        executed_action_hash=executed.executed_action_hash,
        feasibility_status="SAT",
    )
    return DecisionBoundaryV1.create(
        episode_id=EPISODE,
        decision_index=index,
        observation=observation,
        proposed_action=proposal,
        coordinator_decision=decision,
        executed_action=executed,
    )


def _transition(
    index: int,
    *,
    terminal: bool,
    workspace_id: UUID = WORKSPACE,
    session_id: UUID = SESSION,
) -> TransitionV1:
    before = _observation(index, index, workspace_id=workspace_id, session_id=session_id)
    after = _observation(
        index + 1,
        index + 1,
        terminal=terminal,
        workspace_id=workspace_id,
        session_id=session_id,
    )
    boundary = _boundary(index, before)
    reward_input = RewardInputV1(
        pre_value=RationalV1(numerator=index, denominator=1),
        post_value=RationalV1(numerator=index + 1, denominator=1),
        status=RewardStatus.OBSERVED,
        neutral_reason=None,
        source_hashes=tuple(sorted((before.sources[0].source_hash, after.sources[0].source_hash))),
    )
    inputs = (reward_input, reward_input, reward_input, reward_input, reward_input)
    rewards = build_reward_vector(
        episode_id=EPISODE,
        decision_index=index,
        component_ids=(
            U(f"00000000-0000-0000-0006-{index * 5 + 1:012d}"),
            U(f"00000000-0000-0000-0006-{index * 5 + 2:012d}"),
            U(f"00000000-0000-0000-0006-{index * 5 + 3:012d}"),
            U(f"00000000-0000-0000-0006-{index * 5 + 4:012d}"),
            U(f"00000000-0000-0000-0006-{index * 5 + 5:012d}"),
        ),
        inputs=inputs,
    )
    credits = tuple(
        CreditAssignmentV1.create(
            credit_id=U(f"00000000-0000-0000-0007-{index * 5 + ordinal + 1:012d}"),
            episode_id=EPISODE,
            decision_index=index,
            reward_component_id=reward.component_id,
            reward_component_hash=reward.component_hash,
            status=CreditStatus.DIRECT,
            agent_definition_ids=(AGENT,),
            source_hashes=reward.source_hashes,
            share=RationalV1(numerator=1, denominator=1),
            credited_value=reward.reward_value,
            credit_implementation=CREDIT_IMPL,
        )
        for ordinal, reward in enumerate(rewards)
    )
    return TransitionV1.create(
        episode_id=EPISODE,
        decision_index=index,
        boundary=boundary,
        post_observation=after,
        rewards=rewards,
        credits=credits,
        terminal=terminal,
    )


def complete_episode() -> MarlEpisodeV1:
    return MarlEpisodeV1(
        episode_id=EPISODE,
        workspace_id=WORKSPACE,
        session_id=SESSION,
        environment_version="agora-marl-v1",
        code_identity=CODE_HASH,
        status=EpisodeStatus.COMPLETE,
        transitions=(_transition(0, terminal=False), _transition(1, terminal=True)),
    )


def registry() -> ImplementationRegistry:
    value = ImplementationRegistry()
    value.register_feature(OBS_IMPL, lambda snapshot: snapshot.payload["value"])
    for _, _, implementation_id, _ in (
        ("ep-02", "1", "agora.reward.provenance-delta", None),
        ("dh-03", "1", "agora.reward.attack-coverage-delta", None),
        ("dh-02", "1", "agora.reward.disagreement-retention-delta", None),
        ("cq-03", "1", "agora.reward.flip-distance-delta", None),
        ("ce-03", "1", "agora.reward.cost-delta", None),
    ):
        value.register_reward(
            ImplementationRefV1(implementation_id=implementation_id, implementation_version="1"),
            exact_delta,
        )
    value.register_credit(CREDIT_IMPL)
    value.register_coordinator(COORD_IMPL, lambda boundary: boundary.coordinator_decision)
    return value


@req("FR-906", "NFR-003", "NFR-016", "NFR-019")
def test_exact_values_and_hashes_are_strict_and_deterministic() -> None:
    assert RationalV1.from_fraction(Fraction(2, 4)) == RationalV1(numerator=1, denominator=2)
    assert RationalV1(numerator=1, denominator=3) + RationalV1(
        numerator=1, denominator=6
    ) == RationalV1(numerator=1, denominator=2)
    with pytest.raises(ValidationError):
        RationalV1(numerator=2, denominator=4)
    with pytest.raises(ValidationError):
        RationalV1(numerator=1, denominator=-2)
    with pytest.raises(ValueError, match="non-finite"):
        canonical_hash({"value": float("nan")})
    decimal = TypeAdapter(CanonicalDecimal)
    assert decimal.validate_python("12.34") == "12.34"
    for invalid in ("1.0", "01", "-0", "1e2"):
        with pytest.raises(ValidationError):
            decimal.validate_python(invalid)
    first = complete_episode()
    assert complete_episode() == first
    assert export_episode(complete_episode()) == export_episode(first)


@req("FR-906", "NFR-019")
def test_reward_vector_is_five_exact_metric_linked_components_and_neutral_is_explicit() -> None:
    neutral = RewardInputV1(
        pre_value=None,
        post_value=None,
        status=RewardStatus.MISSING_INPUT,
        neutral_reason="SOURCE_ABSENT",
        source_hashes=(),
    )
    values = build_reward_vector(
        episode_id=EPISODE,
        decision_index=0,
        component_ids=(
            U("00000000-0000-0000-0010-000000000000"),
            U("00000000-0000-0000-0010-000000000001"),
            U("00000000-0000-0000-0010-000000000002"),
            U("00000000-0000-0000-0010-000000000003"),
            U("00000000-0000-0000-0010-000000000004"),
        ),
        inputs=(neutral, neutral, neutral, neutral, neutral),
    )
    assert [item.metric_id for item in values] == ["ep-02", "dh-03", "dh-02", "cq-03", "ce-03"]
    assert all(item.reward_value == RationalV1.zero() for item in values)
    assert all(item.neutral_reason == "SOURCE_ABSENT" for item in values)


@req("FR-906")
def test_symbolic_feasibility_cannot_be_overridden_by_reward() -> None:
    observation = _observation(0, 0)
    values = _boundary(0, observation).model_dump(mode="python")
    values["coordinator_decision"] = {
        **values["coordinator_decision"],
        "feasibility_status": "UNSAT",
        "decision_hash": ZERO_HASH,
    }
    with pytest.raises(ValidationError, match="UNSAT proposals cannot be accepted"):
        DecisionBoundaryV1.model_validate(values)


@req("FR-906", "NFR-016")
async def test_inmemory_store_lifecycle_idempotency_conflict_and_isolation() -> None:
    store = InMemoryMarlTrajectoryStore()
    service = MarlTrajectoryService(store)
    opened = MarlEpisodeV1(
        episode_id=EPISODE,
        workspace_id=WORKSPACE,
        session_id=SESSION,
        environment_version="agora-marl-v1",
        code_identity=CODE_HASH,
        status=EpisodeStatus.OPEN,
    )
    await service.open(opened)
    transition = _transition(0, terminal=True)
    await service.capture(WORKSPACE, transition.boundary)
    closed = await service.close(WORKSPACE, transition)
    assert await service.close(WORKSPACE, transition) == closed
    complete = await service.complete(WORKSPACE, EPISODE)
    assert complete.status is EpisodeStatus.COMPLETE
    assert await store.get(U("00000000-0000-0000-0000-000000000099"), EPISODE) is None
    with pytest.raises(MarlConflictError):
        await service.capture(WORKSPACE, _boundary(1, _observation(1, 9)))


@req("FR-906", "NFR-003", "NFR-016")
def test_complete_export_and_hermetic_replay_are_byte_deterministic() -> None:
    bundle = export_episode(complete_episode())
    assert bundle.manifest == (FIXTURES / "complete_manifest.json").read_bytes()
    assert bundle.trajectory == (FIXTURES / "complete_trajectory.jsonl").read_bytes()
    assert set(bundle.entries) == {"manifest.json", "trajectory.jsonl"}
    assert bundle.manifest.endswith(b"\n")
    assert bundle.trajectory.endswith(b"\n")
    assert b"\r" not in bundle.manifest + bundle.trajectory
    manifest = json.loads(bundle.manifest)
    assert manifest["record_count"] == 2
    result = verify_bundle(bundle.manifest, bundle.trajectory, registry())
    assert (result.outcome, result.integrity_valid, result.replay_verified) == (
        ReplayOutcome.VERIFIED,
        True,
        True,
    )


@req("FR-906", "NFR-003")
def test_incomplete_export_is_authentic_but_never_replay_success() -> None:
    transition = _transition(0, terminal=False)
    boundary = _boundary(1, transition.post_observation)
    marker = IncompleteMarkerV1.create(
        marker_id=U("00000000-0000-0000-0008-000000000001"),
        episode_id=EPISODE,
        open_decision_index=1,
        reason="WORKER_INTERRUPTED",
        boundary_hash=boundary.boundary_hash,
    )
    episode = MarlEpisodeV1(
        episode_id=EPISODE,
        workspace_id=WORKSPACE,
        session_id=SESSION,
        environment_version="agora-marl-v1",
        code_identity=CODE_HASH,
        status=EpisodeStatus.INCOMPLETE,
        transitions=(transition,),
        pending_boundary=boundary,
        incomplete_marker=marker,
    )
    bundle = export_episode(episode)
    assert bundle.manifest == (FIXTURES / "incomplete_manifest.json").read_bytes()
    assert bundle.trajectory == (FIXTURES / "incomplete_trajectory.jsonl").read_bytes()
    assert len(bundle.trajectory.splitlines()) == 3
    result = verify_bundle(bundle.manifest, bundle.trajectory, registry())
    assert result.outcome is ReplayOutcome.INCOMPLETE
    assert result.first_failure is not None
    assert result.first_failure.code is FailureCode.EPISODE_INCOMPLETE


@req("FR-906", "NFR-010")
@pytest.mark.parametrize(
    ("manifest", "trajectory", "entries", "limits", "code"),
    [
        (b"{}\n", b"{}\n", ("manifest.json",), BundleLimits(), FailureCode.BUNDLE_ENTRY_SET),
        (
            b"{}\n",
            b"{}\n",
            ("manifest.json", "trajectory.jsonl"),
            BundleLimits(max_manifest_bytes=1),
            FailureCode.RESOURCE_LIMIT_EXCEEDED,
        ),
        (
            b"\xff",
            b"{}\n",
            ("manifest.json", "trajectory.jsonl"),
            BundleLimits(),
            FailureCode.INVALID_UTF8,
        ),
        (
            b"{",
            b"{}\n",
            ("manifest.json", "trajectory.jsonl"),
            BundleLimits(),
            FailureCode.INVALID_JSON,
        ),
    ],
)
def test_failure_precedence_prefix(
    manifest: bytes,
    trajectory: bytes,
    entries: tuple[str, ...],
    limits: BundleLimits,
    code: FailureCode,
) -> None:
    result = verify_bundle(manifest, trajectory, registry(), entry_names=entries, limits=limits)
    assert result.first_failure is not None
    assert result.first_failure.code is code


@req("FR-906", "NFR-010")
def test_mutations_fail_closed_and_precedence_is_deterministic() -> None:
    bundle = export_episode(complete_episode())
    bom = verify_bundle(b"\xef\xbb\xbf" + bundle.manifest, b"{", registry())
    assert bom.first_failure is not None
    assert bom.first_failure.code is FailureCode.NONCANONICAL_ENCODING
    pretty = json.dumps(json.loads(bundle.manifest), indent=2).encode() + b"\n"
    noncanonical = verify_bundle(pretty, bundle.trajectory, registry())
    assert noncanonical.first_failure is not None
    assert noncanonical.first_failure.code is FailureCode.NONCANONICAL_ENCODING
    manifest = json.loads(bundle.manifest)
    manifest["record_count"] = 99
    mutated = canonical_bytes(manifest)
    mismatch = verify_bundle(mutated, bundle.trajectory, registry())
    assert mismatch.first_failure is not None
    assert mismatch.first_failure.code is FailureCode.MANIFEST_MISMATCH


def canonical_bytes(value: object) -> bytes:
    from app.domain.reasoning import canonical_json

    return canonical_json(value) + b"\n"


@req("FR-906", "NFR-016")
def test_unknown_implementation_fails_closed_after_integrity() -> None:
    bundle = export_episode(complete_episode())
    result = verify_bundle(bundle.manifest, bundle.trajectory, ImplementationRegistry())
    assert result.first_failure is not None
    assert result.first_failure.code is FailureCode.UNKNOWN_IMPLEMENTATION
    assert result.integrity_valid is True


@req("FR-906", "NFR-016")
async def test_shared_store_contract_for_inmemory_adapter() -> None:
    await assert_store_contract(InMemoryMarlTrajectoryStore())


async def assert_store_contract(store: MarlTrajectoryStore) -> None:
    """Shared observable contract; the PostgreSQL integration invokes the same helper."""
    service = MarlTrajectoryService(store)
    opened = MarlEpisodeV1(
        episode_id=EPISODE,
        workspace_id=WORKSPACE,
        session_id=SESSION,
        environment_version="agora-marl-v1",
        code_identity=CODE_HASH,
        status=EpisodeStatus.OPEN,
    )
    assert await service.open(opened) == opened
    transition = _transition(0, terminal=True)
    captured = await service.capture(WORKSPACE, transition.boundary)
    assert captured.pending_boundary == transition.boundary
    assert await service.capture(WORKSPACE, transition.boundary) == captured
    closed = await service.close(WORKSPACE, transition)
    assert closed.transitions == (transition,)
    assert await service.close(WORKSPACE, transition) == closed
    complete = await service.complete(WORKSPACE, EPISODE)
    assert complete.status is EpisodeStatus.COMPLETE
    with pytest.raises((MarlConflictError, MarlDomainError)):
        await service.capture(WORKSPACE, _boundary(1, _observation(1, 9)))
