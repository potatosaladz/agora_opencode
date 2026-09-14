"""T6-01 strict logical-agent runtime and strategy tests."""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.adapters.inmemory.reasoning_strategy import DeterministicReasoningStrategy
from app.application.agent_runtime import (
    ActivityReasoningStrategy,
    StatelessAgentRuntime,
    StrategyRegistry,
)
from app.domain.agent_activity import (
    AgentActivityRunner,
    AgentTurnInput,
    AgentTurnResult,
    ArtifactProposal,
    EvidenceDisposition,
    ProposalBundle,
)
from app.domain.reasoning import (
    ArtifactKind,
    Bearing,
    ClaimType,
    Confidence,
    ReviewStatus,
    Stance,
    Strength,
)
from app.ports.agent_runtime import (
    AgentRuntime,
    AuthorizedKnowledge,
    ContextArtifact,
    PinnedAgentDefinition,
    ReasoningContext,
    ReasoningPhase,
    ReasoningStrategy,
    TurnExecutionResult,
)
from app.ports.errors import PermanentPortError
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 12))


def context(**changes: object) -> ReasoningContext:
    values: dict[str, object] = {
        "workspace_id": U[0],
        "session_id": U[1],
        "agent_definition_id": U[2],
        "agent_definition_version": 3,
        "strategy_name": "evidence-first",
        "strategy_version": "1.0.0",
        "canonicalizer_version": "canonicalizer@1",
        "turn_id": U[3],
        "correlation_id": U[4],
        "causation_id": U[5],
        "round": 1,
        "phase": ReasoningPhase.ASSESS,
        "problem_statement": "Choose a defensible intervention.",
        "objective_summaries": ("Protect vulnerable households",),
        "constraint_summaries": ("Stay within the legal budget ceiling",),
        "visible_artifact_ids": (),
        "sealed": True,
        "budget_remaining_tokens": 900,
        "budget_remaining_usd": Decimal("1.25"),
        "timeout_s": 12.0,
    }
    values.update(changes)
    if "agent_definition" not in changes:
        values["agent_definition"] = PinnedAgentDefinition(
            id=U[2],
            logical_id=U[6],
            version=3,
            name="fiscal-analyst",
            domain="fiscal",
            role_kind="domain_expert",
            objectives=("Assess fiscal sustainability",),
            constraints=("Never claim coordinator authority",),
            strategy_name=str(values["strategy_name"]),
            strategy_version=str(values["strategy_version"]),
            prompt_ref="prompts/fiscal-analyst/v3.txt",
            prompt_hash="sha256:" + "a" * 64,
        )
    return ReasoningContext.model_validate(values)


def bundle(turn_id: UUID = U[3]) -> ProposalBundle:
    return ProposalBundle(
        protocol_version="1.0",
        kind="proposal_bundle",
        turn_id=turn_id,
        artifacts=(),
        self_reported_limits=("No local outcome data",),
    )


def position(
    disposition: EvidenceDisposition | None, evidence_ids: tuple[UUID, ...]
) -> ArtifactProposal:
    return ArtifactProposal(
        op="propose",
        kind=ArtifactKind.POSITION,
        evidence_disposition=disposition,
        confidence=Confidence(
            kind="subjective",
            value="0.65",
            meaning="declared confidence",
            basis_artifact_ids=evidence_ids,
        ),
        payload={
            "target_id": U[6],
            "stance": Stance.CONDITIONALLY_SUPPORT,
            "rationale": "Support only if financing remains within the ceiling.",
            "evidence_ids": evidence_ids,
            "conditions": ("financing remains within the ceiling",),
        },
    )


@req("FR-209")
def test_context_is_strict_versioned_frozen_and_seals_round_one() -> None:
    valid = context()
    with pytest.raises(ValidationError, match="frozen"):
        valid.sealed = False  # type: ignore[misc]
    with pytest.raises(ValidationError, match="sealed from other agents"):
        context(sealed=False)
    with pytest.raises(ValidationError, match="unique hydrated artifacts"):
        context(visible_artifact_ids=(U[7],))
    artifact = ContextArtifact(
        id=U[7],
        kind="CLAIM",
        owner_actor_class="AGENT",
        owner_actor_id=U[2],
        round=0,
        content_hash="sha256:" + "a" * 64,
        artifact_json='{"kind":"CLAIM"}',
    )
    with pytest.raises(ValidationError, match="sealed from other agents"):
        context(visible_artifact_ids=(artifact.id,), visible_artifacts=(artifact,))
    with pytest.raises(ValidationError, match="schema_version"):
        context(schema_version=2)
    with pytest.raises(ValidationError, match="Extra inputs"):
        context(peer_agent_channel="forbidden")


@req("FR-209")
@pytest.mark.parametrize(
    ("disposition", "evidence_ids", "message"),
    [
        (None, (), "explicit evidence disposition"),
        (EvidenceDisposition.CITED, (), "at least one evidence ID"),
        (EvidenceDisposition.NO_EVIDENCE, (U[7],), "must not declare evidence IDs"),
    ],
)
def test_position_evidence_disposition_fails_closed(
    disposition: EvidenceDisposition | None,
    evidence_ids: tuple[UUID, ...],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        position(disposition, evidence_ids)


@req("FR-209")
def test_position_accepts_exact_cited_or_no_evidence_states() -> None:
    assert position(EvidenceDisposition.CITED, (U[7],)).evidence_disposition == "CITED"
    assert position(EvidenceDisposition.NO_EVIDENCE, ()).evidence_disposition == "NO_EVIDENCE"
    with pytest.raises(ValidationError, match="only valid for POSITION"):
        ArtifactProposal(
            op="propose",
            kind=ArtifactKind.CLAIM,
            evidence_disposition=EvidenceDisposition.NO_EVIDENCE,
            payload={
                "statement": "Unsupported claim",
                "claim_type": ClaimType.EVALUATIVE,
                "direction": Bearing.SUPPORTS,
                "strength": Strength.WEAK,
                "supporting_evidence_ids": (),
                "opposing_evidence_ids": (),
                "review_status": ReviewStatus.PROPOSED,
            },
        )


@req("FR-209")
async def test_runtime_resolves_exact_strategy_and_conforms_to_ports() -> None:
    strategy = DeterministicReasoningStrategy(
        "evidence-first", "1.0.0", lambda value: bundle(value.turn_id)
    )
    registry = StrategyRegistry((strategy,))
    runtime = StatelessAgentRuntime(registry)

    assert isinstance(strategy, ReasoningStrategy)
    assert isinstance(runtime, AgentRuntime)
    assert await runtime.run_turn(context()) == TurnExecutionResult(proposal=bundle())
    assert strategy.contexts == [context()]


@req("FR-209")
async def test_registry_and_runtime_reject_ambiguous_or_wrong_strategy_results() -> None:
    first = DeterministicReasoningStrategy(
        "evidence-first", "1.0.0", lambda value: bundle(value.turn_id)
    )
    duplicate = DeterministicReasoningStrategy(
        "evidence-first", "1.0.0", lambda value: bundle(value.turn_id)
    )
    with pytest.raises(ValueError, match="duplicate reasoning strategy"):
        StrategyRegistry((first, duplicate))

    runtime = StatelessAgentRuntime(StrategyRegistry((first,)))
    with pytest.raises(PermanentPortError, match="unknown reasoning strategy"):
        await runtime.run_turn(context(strategy_version="2.0.0"))

    wrong = DeterministicReasoningStrategy("wrong-turn", "1.0.0", lambda _value: bundle(U[8]))
    with pytest.raises(PermanentPortError, match="another turn"):
        await StatelessAgentRuntime(StrategyRegistry((wrong,))).run_turn(
            context(strategy_name="wrong-turn")
        )


class RecordingActivity:
    def __init__(self) -> None:
        self.commands: list[AgentTurnInput] = []

    async def run(self, command: AgentTurnInput) -> AgentTurnResult:
        self.commands.append(command)
        return AgentTurnResult(
            turn_id=command.turn_id,
            agent_definition_id=command.agent_definition_id,
            bundle=bundle(command.turn_id),
            provider="mock",
            model="fixture-model",
            input_tokens=10,
            output_tokens=4,
            cost_usd=Decimal("0.0001"),
            raw_artifact_ref="artifacts/trace.json#sha256:" + "a" * 64,
        )


@req("FR-209")
async def test_activity_strategy_adapts_context_without_mutation_or_peer_channel() -> None:
    activity = RecordingActivity()
    strategy = ActivityReasoningStrategy(
        "evidence-first", "1.0.0", cast(AgentActivityRunner, activity)
    )

    result = await strategy.propose(context())

    assert result.proposal == bundle()
    assert result.provider == "mock"
    assert result.model == "fixture-model"
    assert result.input_tokens == 10
    assert result.output_tokens == 4
    assert result.cost_usd == Decimal("0.0001")
    assert result.raw_artifact_ref == "artifacts/trace.json#sha256:" + "a" * 64
    assert len(activity.commands) == 1
    command = activity.commands[0]
    assert command.timeout_s == 12.0
    assert command.agent_definition_version == 3
    assert PinnedAgentDefinition.model_validate_json(command.agent_definition_json) == (
        context().agent_definition
    )
    assert command.canonicalizer_version == "canonicalizer@1"
    assert command.sealed is True
    assert command.visible_artifact_ids == ()
    assert command.constraint_summaries == ("Stay within the legal budget ceiling",)
    assert not hasattr(command, "peer_agent_channel")

    await strategy.propose(context(round=2, phase=ReasoningPhase.DECOMPOSE, sealed=False))
    assert activity.commands[-1].phase.value == "DECOMPOSE"


@req("FR-209")
async def test_activity_strategy_propagates_artifact_and_zero_hit_retrieval_snapshots() -> None:
    activity = RecordingActivity()
    strategy = ActivityReasoningStrategy(
        "evidence-first", "1.0.0", cast(AgentActivityRunner, activity)
    )
    artifact = ContextArtifact(
        id=U[7],
        kind="CLAIM",
        owner_actor_class="AGENT",
        owner_actor_id=U[2],
        round=1,
        content_hash="sha256:" + "b" * 64,
        artifact_json='{"kind":"CLAIM","statement":"Prior finding"}',
    )
    retrieval = AuthorizedKnowledge(
        query_hash="sha256:" + "c" * 64,
        requested_namespace_ids=(U[8],),
        searched_namespace_ids=(U[8],),
        index_version="index@1",
        embedding_model="embed",
        embedding_version="1",
        reranker_version="rrf@1",
        lexical_count=0,
        vector_count=0,
        degradation="NONE",
        chunks=(),
    )

    await strategy.propose(
        context(
            round=2,
            phase=ReasoningPhase.ARGUE,
            sealed=False,
            visible_artifact_ids=(artifact.id,),
            visible_artifacts=(artifact,),
            retrieval=retrieval,
        )
    )

    command = activity.commands[0]
    assert command.visible_artifact_json == (artifact.artifact_json,)
    assert command.authorized_knowledge_json is not None
    assert AuthorizedKnowledge.model_validate_json(command.authorized_knowledge_json) == retrieval
