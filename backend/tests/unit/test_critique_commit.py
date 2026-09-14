"""T7-04 assigned Critique atomic commit and ATTACKS projection tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from app.application.critique_commit import CritiqueProposalCommitter
from app.application.proposal_commit import (
    AgentProposalCommitter,
    AgentTurnCommit,
    agent_turn_commit_id,
)
from app.domain.agent_activity import AgentTurnResult, ArtifactProposal, ProposalBundle
from app.domain.artifact_commit import ArtifactCommitError
from app.domain.critique import CritiqueAssignment
from app.domain.reasoning import (
    ActorClass,
    ArtifactKind,
    Bearing,
    ClaimPayload,
    ClaimType,
    GraphEdgeType,
    LifecycleStatus,
    Provenance,
    ProvenanceOrigin,
    ReasoningArtifact,
    ReviewStatus,
    Strength,
    artifact_content_hash,
    validate_artifact,
)
from app.domain.reasoning_graph import GraphEdge, GraphNode
from app.domain.reasoning_ledger import (
    LedgerAppend,
    LedgerEvent,
    LedgerVerification,
    ledger_event_hash,
    ledger_payload_hash,
)
from app.ports.agent_runtime import (
    ContextArtifact,
    PinnedAgentDefinition,
    ReasoningContext,
    ReasoningPhase,
)
from tests.traceability import req
from tests.unit.test_reasoning import artifact_data

U = tuple(UUID(f"018f6000-0000-7000-8000-{index:012d}") for index in range(1, 50))
NOW = datetime(2026, 9, 7, 15, tzinfo=UTC)


def target(
    *, status: LifecycleStatus = LifecycleStatus.ACTIVE, round_: int = 1
) -> ReasoningArtifact:
    values: dict[str, object] = {
        "id": U[8],
        "workspace_id": U[0],
        "session_id": U[1],
        "logical_id": U[9],
        "kind": ArtifactKind.CLAIM,
        "schema_version": 1,
        "version": 1,
        "status": status,
        "supersedes_id": None,
        "owner_actor_class": ActorClass.AGENT,
        "owner_actor_id": U[10],
        "round": round_,
        "payload": ClaimPayload(
            statement="The option is affordable.",
            claim_type=ClaimType.FACTUAL,
            direction=Bearing.SUPPORTS,
            strength=Strength.MODERATE,
            supporting_evidence_ids=(),
            opposing_evidence_ids=(),
            review_status=ReviewStatus.PROPOSED,
        ),
        "provenance": Provenance(origin=ProvenanceOrigin.LLM, reference="fixture"),
        "source_references": (),
        "parent_relationships": (),
        "confidence": None,
        "metadata": {},
        "created_at": NOW,
        "updated_at": NOW,
    }
    values["content_hash"] = artifact_content_hash(values)
    return validate_artifact(values)


def target_of_kind(kind: ArtifactKind) -> ReasoningArtifact:
    values = artifact_data(kind)
    values.update(
        {
            "id": U[8],
            "workspace_id": U[0],
            "session_id": U[1],
            "logical_id": U[9],
            "owner_actor_class": ActorClass.HUMAN,
            "owner_actor_id": U[10],
            "round": 1,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    values["content_hash"] = artifact_content_hash(values)
    return validate_artifact(values)


def context(value: ReasoningArtifact, **changes: object) -> ReasoningContext:
    definition = PinnedAgentDefinition(
        id=U[2],
        logical_id=U[3],
        version=1,
        name="cross-cutting-critic",
        domain="cross-cutting-critique",
        role_kind="critic",
        strategy_name="cross-cutting-critique",
        strategy_version="1.0.0",
        prompt_ref="prompts/critics/v1.txt",
        prompt_hash="sha256:" + "a" * 64,
    )
    values: dict[str, object] = {
        "workspace_id": U[0],
        "session_id": U[1],
        "agent_definition_id": U[2],
        "agent_definition_version": 1,
        "agent_definition": definition,
        "strategy_name": definition.strategy_name,
        "strategy_version": definition.strategy_version,
        "canonicalizer_version": "canonicalizer@1",
        "turn_id": U[4],
        "correlation_id": U[5],
        "causation_id": U[6],
        "round": 2,
        "phase": ReasoningPhase.CRITIQUE,
        "problem_statement": "Critique the public reasoning record.",
        "visible_artifact_ids": (value.id,),
        "visible_artifacts": (
            ContextArtifact(
                id=value.id,
                kind=value.kind.value,
                owner_actor_class=value.owner_actor_class.value,
                owner_actor_id=value.owner_actor_id,
                round=value.round,
                content_hash=value.content_hash,
                artifact_json=value.model_dump_json(),
            ),
        ),
        "sealed": False,
        "budget_remaining_tokens": 500,
        "budget_remaining_usd": Decimal("2"),
        "timeout_s": 10.0,
    }
    values.update(changes)
    return ReasoningContext.model_validate(values)


def assignment(value: ReasoningContext, **changes: object) -> CritiqueAssignment:
    values: dict[str, object] = {
        "protocol_version": "1.0",
        "kind": "critique_assignment",
        "workspace_id": value.workspace_id,
        "session_id": value.session_id,
        "critic_definition_id": value.agent_definition_id,
        "critic_definition_version": value.agent_definition_version,
        "turn_id": value.turn_id,
        "correlation_id": value.correlation_id,
        "causation_id": value.causation_id,
        "round": value.round,
        "target_artifact_ids": value.visible_artifact_ids,
    }
    values.update(changes)
    return CritiqueAssignment.model_validate(values)


def command(value: ReasoningArtifact, **context_changes: object) -> AgentTurnCommit:
    turn_context = context(value, **context_changes)
    bundle = ProposalBundle(
        protocol_version="1.0",
        kind="proposal_bundle",
        turn_id=turn_context.turn_id,
        artifacts=(
            ArtifactProposal(
                op="propose",
                kind=ArtifactKind.CRITIQUE,
                payload={
                    "target_id": value.id,
                    "critique_type": "EVIDENCE_GAP",
                    "severity": "BLOCKING",
                    "argument": "No supporting Evidence is linked to this material Claim.",
                    "resolution": "OPEN",
                },
            ),
        ),
        self_reported_limits=("Fixture Critic",),
    )
    return AgentTurnCommit(
        context=turn_context,
        result=AgentTurnResult(
            turn_id=turn_context.turn_id,
            agent_definition_id=turn_context.agent_definition_id,
            bundle=bundle,
            provider="mock",
            model="critic-fixture",
            input_tokens=21,
            output_tokens=13,
            cost_usd=Decimal("0"),
            raw_artifact_ref="raw/critic.json#sha256:" + "b" * 64,
        ),
        committed_at=NOW,
    )


class _Artifacts:
    def __init__(self, *values: ReasoningArtifact) -> None:
        self.values = {value.id: value for value in values}
        self.added: list[ReasoningArtifact] = []
        self.locked_turns: list[UUID] = []

    async def lock_agent_turn(self, workspace_id: UUID, session_id: UUID, turn_id: UUID) -> None:
        assert (workspace_id, session_id) == (U[0], U[1])
        self.locked_turns.append(turn_id)

    async def add(self, artifact: ReasoningArtifact) -> None:
        self.values[artifact.id] = artifact
        self.added.append(artifact)

    async def get_for_update(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> ReasoningArtifact | None:
        value = self.values.get(artifact_id)
        if value is None or (value.workspace_id, value.session_id) != (workspace_id, session_id):
            return None
        return value

    async def set_lifecycle(
        self,
        workspace_id: UUID,
        session_id: UUID,
        artifact_id: UUID,
        status: LifecycleStatus,
        *,
        updated_at: datetime,
    ) -> None:
        del workspace_id, session_id, artifact_id, status, updated_at
        raise AssertionError("Critique initial commit never changes lifecycle")


class _Graph:
    def __init__(self, *values: ReasoningArtifact) -> None:
        self.nodes = {
            value.id: GraphNode(
                id=U[20 + index],
                workspace_id=value.workspace_id,
                session_id=value.session_id,
                kind=value.kind,
                ref_id=value.id,
                label=value.kind.value.title(),
            )
            for index, value in enumerate(values)
        }
        self.edges: list[GraphEdge] = []

    async def add_node(self, node: GraphNode) -> None:
        self.nodes[node.ref_id] = node

    async def add_edge(self, edge: GraphEdge) -> None:
        self.edges.append(edge)

    async def node_for_artifact(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> GraphNode | None:
        value = self.nodes.get(artifact_id)
        if value is None or (value.workspace_id, value.session_id) != (workspace_id, session_id):
            return None
        return value


class _Ledger:
    def __init__(self) -> None:
        self.events: list[LedgerEvent] = []

    async def append(self, event: LedgerAppend) -> LedgerEvent:
        prior = await self.get_by_id(event.workspace_id, event.session_id, event.id)
        if prior is not None:
            expected = prior.model_dump(
                exclude={"ledger_seq", "payload_hash", "prev_hash", "event_hash"}
            )
            if expected != event.model_dump():
                raise ValueError("event id reused with different content")
            return prior
        persisted = LedgerEvent(
            **event.model_dump(),
            ledger_seq=len(self.events) + 1,
            payload_hash=ledger_payload_hash(event.payload),
            prev_hash=self.events[-1].event_hash if self.events else "sha256:" + "0" * 64,
            event_hash="sha256:" + "0" * 64,
        )
        persisted = persisted.model_copy(update={"event_hash": ledger_event_hash(persisted)})
        self.events.append(persisted)
        return persisted

    async def get_by_id(
        self, workspace_id: UUID, session_id: UUID, event_id: UUID
    ) -> LedgerEvent | None:
        return next(
            (
                event
                for event in self.events
                if event.id == event_id
                and (event.workspace_id, event.session_id) == (workspace_id, session_id)
            ),
            None,
        )

    async def read(
        self, workspace_id: UUID, session_id: UUID, *, from_seq: int = 1, limit: int = 1000
    ) -> tuple[LedgerEvent, ...]:
        del workspace_id, session_id
        return tuple(self.events[from_seq - 1 :][:limit])

    async def verify(self, workspace_id: UUID, session_id: UUID) -> LedgerVerification:
        del workspace_id, session_id
        head = self.events[-1].event_hash if self.events else "sha256:" + "0" * 64
        return LedgerVerification(valid=True, event_count=len(self.events), head_hash=head)


def service(
    value: ReasoningArtifact,
) -> tuple[CritiqueProposalCommitter, _Artifacts, _Graph, _Ledger]:
    artifacts, graph, ledger = _Artifacts(value), _Graph(value), _Ledger()
    return (
        CritiqueProposalCommitter(AgentProposalCommitter(artifacts, graph, ledger)),
        artifacts,
        graph,
        ledger,
    )


@req("FR-501")
async def test_commits_open_critique_with_one_retry_stable_attack_and_full_attribution() -> None:
    value = target()
    committer, artifacts, graph, ledger = service(value)
    operation = command(value)
    turn_assignment = assignment(operation.context)

    first = await committer.commit(operation, turn_assignment)
    second = await committer.commit(operation, turn_assignment)

    assert first == second
    assert len(first) == 1
    critique = first[0].artifact
    assert critique.kind is ArtifactKind.CRITIQUE
    assert critique.payload.target_id == value.id
    assert critique.parent_relationships[0].edge_type is GraphEdgeType.ATTACKS
    assert critique.parent_relationships[0].target_artifact_id == value.id
    assert critique.metadata["attribution"]["phase"] == ReasoningPhase.CRITIQUE.value
    assert len(artifacts.added) == 1
    assert artifacts.locked_turns == [operation.context.turn_id, operation.context.turn_id]
    assert len(graph.edges) == 1
    attack = graph.edges[0]
    assert attack.id == agent_turn_commit_id(operation.context.turn_id, 0, "relationship-edge", 0)
    assert attack.edge_type is GraphEdgeType.ATTACKS
    assert attack.qualifier == {"type": "EVIDENCE_GAP", "severity": "BLOCKING"}
    assert attack.from_node == graph.nodes[critique.id].id
    assert attack.to_node == graph.nodes[value.id].id
    assert attack.actor_id == operation.context.agent_definition_id
    assert [event.event_type for event in ledger.events] == [
        "ARTIFACT_COMMITTED",
        "AGENT_TURN_COMPLETED",
    ]


@req("FR-205")
@pytest.mark.parametrize("kind", list(ArtifactKind))
async def test_fr205_commits_attack_against_every_artifact_kind(kind: ArtifactKind) -> None:
    value = target_of_kind(kind)
    committer, _, graph, _ = service(value)
    operation = command(value)

    (write,) = await committer.commit(operation, assignment(operation.context))

    assert graph.nodes[value.id].kind is kind
    assert graph.nodes[write.artifact.id].kind is ArtifactKind.CRITIQUE
    assert len(graph.edges) == 1
    assert graph.edges[0].edge_type is GraphEdgeType.ATTACKS
    assert graph.edges[0].to_node == graph.nodes[value.id].id


@req("FR-502")
@pytest.mark.parametrize(
    ("target_value", "context_changes", "message"),
    [
        (None, {}, "does not exist"),
        (target(status=LifecycleStatus.WITHDRAWN), {}, "not ACTIVE"),
        (target(round_=3), {}, "from the future"),
    ],
)
async def test_invalid_target_or_hidden_assignment_leaves_no_partial_write(
    target_value: ReasoningArtifact | None,
    context_changes: dict[str, object],
    message: str,
) -> None:
    proposal_target = target() if target_value is None else target_value
    operation = command(proposal_target, **context_changes)
    artifacts, graph, ledger = (
        _Artifacts(*(value for value in (target_value,) if value is not None)),
        _Graph(*(value for value in (target_value,) if value is not None)),
        _Ledger(),
    )
    committer = CritiqueProposalCommitter(AgentProposalCommitter(artifacts, graph, ledger))

    with pytest.raises((ArtifactCommitError, ValueError), match=message):
        await committer.commit(operation, assignment(operation.context))

    assert artifacts.added == []
    assert graph.edges == []
    assert ledger.events == []


@req("FR-205", "FR-501", "FR-502")
@pytest.mark.parametrize(
    ("context_changes", "resolution", "message"),
    [
        (
            {"phase": ReasoningPhase.ARGUE},
            "OPEN",
            "requires a critic or domain expert in CRITIQUE phase",
        ),
        (
            {
                "agent_definition": context(target()).agent_definition.model_copy(
                    update={"role_kind": "orchestrator"}
                )
            },
            "OPEN",
            "requires a critic or domain expert in CRITIQUE phase",
        ),
        ({}, "RESOLVED", "must have OPEN resolution"),
    ],
)
async def test_generic_committer_cannot_bypass_critic_authority(
    context_changes: dict[str, object], resolution: str, message: str
) -> None:
    value = target()
    operation = command(value, **context_changes)
    original = operation.result.bundle.artifacts[0]
    payload = dict(original.payload)
    payload["resolution"] = resolution
    proposal = ArtifactProposal.model_validate(
        {"op": "propose", "kind": ArtifactKind.CRITIQUE, "payload": payload}
    )
    operation = operation.model_copy(
        update={
            "result": operation.result.model_copy(
                update={
                    "bundle": operation.result.bundle.model_copy(update={"artifacts": (proposal,)})
                }
            )
        }
    )
    _, artifacts, graph, ledger = service(value)

    with pytest.raises(ArtifactCommitError, match=message):
        await AgentProposalCommitter(artifacts, graph, ledger).commit(
            operation,
            critique_assignment=(
                assignment(operation.context) if resolution == "RESOLVED" else None
            ),
        )

    assert artifacts.locked_turns == []
    assert artifacts.added == []
    assert graph.edges == []
    assert ledger.events == []


@req("FR-205", "FR-501", "FR-502")
async def test_generic_committer_requires_assignment_even_for_valid_critic_turn() -> None:
    value = target()
    operation = command(value)
    _, artifacts, graph, ledger = service(value)

    with pytest.raises(ArtifactCommitError, match="requires a coordinator assignment"):
        await AgentProposalCommitter(artifacts, graph, ledger).commit(operation)

    assert artifacts.locked_turns == []
    assert artifacts.added == []
    assert graph.edges == []
    assert ledger.events == []


@req("FR-205", "FR-501", "FR-502")
async def test_domain_expert_peer_may_commit_assigned_visible_attack_in_critique_phase() -> None:
    value = target()
    operation = command(
        value,
        agent_definition=context(value).agent_definition.model_copy(
            update={"role_kind": "domain_expert"}
        ),
    )
    committer, _artifacts, graph, _ledger = service(value)

    (write,) = await committer.commit(operation, assignment(operation.context))

    assert write.artifact.kind is ArtifactKind.CRITIQUE
    assert write.artifact.owner_actor_id == operation.context.agent_definition_id
    assert graph.edges[0].edge_type is GraphEdgeType.ATTACKS


@req("FR-205", "FR-501", "FR-502")
async def test_hidden_target_assignment_leaves_no_partial_write() -> None:
    value = target()
    operation = command(value)
    committer, artifacts, graph, ledger = service(value)
    hidden_assignment = assignment(operation.context, target_artifact_ids=(U[11],))

    with pytest.raises(ValueError, match="does not match authorized reasoning context"):
        await committer.commit(operation, hidden_assignment)

    assert artifacts.locked_turns == []
    assert artifacts.added == []
    assert graph.edges == []
    assert ledger.events == []


@req("FR-205", "FR-501", "FR-502")
@pytest.mark.parametrize(
    ("context_changes", "message"),
    [
        ({"phase": ReasoningPhase.ARGUE}, "requires CRITIQUE phase"),
        (
            {
                "agent_definition": context(target()).agent_definition.model_copy(
                    update={"role_kind": "orchestrator"}
                )
            },
            "requires a critic or domain expert definition",
        ),
        ({"sealed": True}, "requires coordinator-selected public context"),
    ],
)
async def test_wrong_phase_or_role_fails_before_turn_lock(
    context_changes: dict[str, object], message: str
) -> None:
    value = target()
    operation = command(value, **context_changes)
    committer, artifacts, graph, ledger = service(value)

    with pytest.raises(ValueError, match=message):
        await committer.commit(operation, assignment(operation.context))

    assert artifacts.locked_turns == []
    assert artifacts.added == []
    assert graph.edges == []
    assert ledger.events == []
