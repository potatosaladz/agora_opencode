"""T7-05/T7-06 atomic Critique response and immutable revision tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.critique_response import (
    CritiqueResponseCommand,
    CritiqueResponseCommitter,
    response_commit_id,
)
from app.db.critique_response import SqlAlchemyCritiqueResponseStore
from app.db.models.critique_response import CritiqueResponseRequestRow, CritiqueResponseResultRow
from app.domain.agent_activity import ArtifactProposal
from app.domain.artifact_commit import ArtifactCommitError, ReasoningArtifactStore
from app.domain.critique import (
    ArtifactRevisionProposal,
    CritiqueResponseDisposition,
    CritiqueResponseProposal,
    CritiqueResponseRequest,
    CritiqueResponseResult,
    CritiqueResponseResultStatus,
    CritiqueResponseStore,
)
from app.domain.reasoning import (
    ActorClass,
    ArtifactKind,
    CritiquePayload,
    CritiqueType,
    GraphEdgeType,
    LifecycleStatus,
    ParentRelationship,
    ReasoningArtifact,
    Resolution,
    Severity,
    artifact_content_hash,
    validate_artifact,
)
from app.domain.reasoning_graph import GraphEdge, GraphNode, ReasoningGraphWriter
from app.domain.reasoning_ledger import (
    AgentProposalLedger,
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
    TurnExecutionResult,
)
from tests.traceability import req
from tests.unit.test_reasoning import artifact_data

U = tuple(UUID(f"018f9000-0000-7000-8000-{value:012d}") for value in range(1, 100))
NOW = datetime(2026, 9, 7, 18, tzinfo=UTC)


def artifact(kind: ArtifactKind, *, artifact_id: UUID, owner_id: UUID) -> ReasoningArtifact:
    values = artifact_data(kind)
    values.update(
        {
            "id": artifact_id,
            "workspace_id": U[0],
            "session_id": U[1],
            "logical_id": U[50 + artifact_id.int % 20],
            "owner_actor_class": ActorClass.AGENT,
            "owner_actor_id": owner_id,
            "round": 1,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    values["content_hash"] = artifact_content_hash(values)
    return validate_artifact(values)


def response_artifacts() -> tuple[ReasoningArtifact, ReasoningArtifact, ReasoningArtifact]:
    target = artifact(ArtifactKind.CLAIM, artifact_id=U[10], owner_id=U[2])
    values = artifact_data(ArtifactKind.CRITIQUE)
    values.update(
        {
            "id": U[11],
            "workspace_id": U[0],
            "session_id": U[1],
            "logical_id": U[61],
            "owner_actor_class": ActorClass.AGENT,
            "owner_actor_id": U[3],
            "round": 1,
            "payload": CritiquePayload(
                target_id=target.id,
                critique_type=CritiqueType.EVIDENCE_GAP,
                severity=Severity.HIGH,
                argument="The Claim lacks supporting evidence.",
                resolution=Resolution.OPEN,
            ),
            "parent_relationships": (
                ParentRelationship(edge_type=GraphEdgeType.ATTACKS, target_artifact_id=target.id),
            ),
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    values["content_hash"] = artifact_content_hash(values)
    critique = validate_artifact(values)
    warrant = artifact(ArtifactKind.CLAIM, artifact_id=U[12], owner_id=U[4])
    return target, critique, warrant


def context(values: tuple[ReasoningArtifact, ...]) -> ReasoningContext:
    definition = PinnedAgentDefinition(
        id=U[2],
        logical_id=U[6],
        version=2,
        name="responding-expert",
        domain="fiscal",
        role_kind="domain_expert",
        strategy_name="evidence-first",
        strategy_version="2.0.0",
        prompt_ref="prompts/responding-expert/v2.txt",
        prompt_hash="sha256:" + "a" * 64,
    )
    snapshots = tuple(
        ContextArtifact(
            id=value.id,
            kind=value.kind.value,
            owner_actor_class=value.owner_actor_class.value,
            owner_actor_id=value.owner_actor_id,
            round=value.round,
            content_hash=value.content_hash,
            artifact_json=value.model_dump_json(),
        )
        for value in values
    )
    return ReasoningContext(
        workspace_id=U[0],
        session_id=U[1],
        agent_definition_id=definition.id,
        agent_definition_version=definition.version,
        agent_definition=definition,
        strategy_name=definition.strategy_name,
        strategy_version=definition.strategy_version,
        canonicalizer_version="canonicalizer@1",
        turn_id=U[7],
        correlation_id=U[8],
        causation_id=U[9],
        round=2,
        phase=ReasoningPhase.REVISE,
        problem_statement="Address the assigned Critique.",
        visible_artifact_ids=tuple(value.id for value in values),
        visible_artifacts=snapshots,
        sealed=True,
        budget_remaining_tokens=500,
        budget_remaining_usd=Decimal("1"),
        timeout_s=10,
    )


def target_revision() -> ArtifactRevisionProposal:
    return ArtifactRevisionProposal(
        op="propose",
        kind=ArtifactKind.CLAIM,
        payload={
            "statement": "The option may be affordable, but current evidence is limited.",
            "claim_type": "FACTUAL",
            "direction": "SUPPORTS",
            "strength": "WEAK",
            "supporting_evidence_ids": [],
            "opposing_evidence_ids": [],
            "review_status": "CONTESTED",
        },
    )


def proposal(disposition: CritiqueResponseDisposition, **changes: Any) -> CritiqueResponseProposal:
    effects: dict[CritiqueResponseDisposition, dict[str, object]] = {
        CritiqueResponseDisposition.ACCEPT: {},
        CritiqueResponseDisposition.PARTIALLY_ACCEPT: {
            "remaining_issue": "The magnitude remains uncertain."
        },
        CritiqueResponseDisposition.REJECT_WITH_JUSTIFICATION: {"warrant_artifact_ids": (U[12],)},
        CritiqueResponseDisposition.REVISE: {"proposed_revision": target_revision()},
        CritiqueResponseDisposition.REQUEST_EVIDENCE: {
            "evidence_query": "Find audited cost evidence."
        },
        CritiqueResponseDisposition.REQUEST_SIMULATION: {
            "simulation_request_ref": "simulation-spec:cost-sensitivity-v1"
        },
        CritiqueResponseDisposition.ABSTAIN: {},
    }
    values: dict[str, Any] = {
        "protocol_version": "1.0",
        "kind": "critique_response",
        "response_id": U[13],
        "workspace_id": U[0],
        "session_id": U[1],
        "responding_definition_id": U[2],
        "responding_definition_version": 2,
        "turn_id": U[7],
        "correlation_id": U[8],
        "causation_id": U[9],
        "round": 2,
        "critique_id": U[11],
        "critique_version": 1,
        "target_artifact_id": U[10],
        "target_artifact_version": 1,
        "disposition": disposition,
        "rationale": f"Response disposition is {disposition.value}.",
        **effects[disposition],
    }
    values.update(changes)
    return CritiqueResponseProposal.model_validate(values)


def command(
    disposition: CritiqueResponseDisposition,
    values: tuple[ReasoningArtifact, ...],
    **proposal_changes: Any,
) -> CritiqueResponseCommand:
    return CritiqueResponseCommand(
        context=context(values),
        execution=TurnExecutionResult(
            proposal=proposal(disposition, **proposal_changes),
            provider="mock",
            model="critic-response-model",
            input_tokens=21,
            output_tokens=8,
            cost_usd=Decimal("0.0021"),
            raw_artifact_ref="raw/responses/trace.json#sha256:" + "b" * 64,
        ),
        committed_at=NOW,
    )


class MemoryArtifacts:
    def __init__(self, *values: ReasoningArtifact) -> None:
        self.values = {value.id: value for value in values}
        self.added: list[ReasoningArtifact] = []
        self.lifecycle: list[tuple[UUID, LifecycleStatus]] = []

    async def add(self, value: ReasoningArtifact) -> None:
        self.values[value.id] = value
        self.added.append(value)

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
        value = self.values[artifact_id]
        assert (value.workspace_id, value.session_id) == (workspace_id, session_id)
        self.values[artifact_id] = value.model_copy(
            update={"status": status, "updated_at": updated_at}
        )
        self.lifecycle.append((artifact_id, status))


class MemoryGraph:
    def __init__(self, *values: ReasoningArtifact) -> None:
        self.nodes = {
            value.id: GraphNode(
                id=U[30 + index],
                workspace_id=value.workspace_id,
                session_id=value.session_id,
                kind=value.kind,
                ref_id=value.id,
                label=value.kind.value.title(),
            )
            for index, value in enumerate(values)
        }
        self.edges: list[GraphEdge] = []

    async def add_node(self, value: GraphNode) -> None:
        self.nodes[value.ref_id] = value

    async def add_edge(self, value: GraphEdge) -> None:
        self.edges.append(value)

    async def node_for_artifact(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> GraphNode | None:
        value = self.nodes.get(artifact_id)
        if value is None or (value.workspace_id, value.session_id) != (workspace_id, session_id):
            return None
        return value


class MemoryLedger:
    def __init__(self) -> None:
        self.events: list[LedgerEvent] = []

    async def append(self, value: LedgerAppend) -> LedgerEvent:
        existing = await self.get_by_id(value.workspace_id, value.session_id, value.id)
        if existing is not None:
            return existing
        event = LedgerEvent(
            **value.model_dump(),
            ledger_seq=len(self.events) + 1,
            payload_hash=ledger_payload_hash(value.payload),
            prev_hash=self.events[-1].event_hash if self.events else "sha256:" + "0" * 64,
            event_hash="sha256:" + "0" * 64,
        )
        event = event.model_copy(update={"event_hash": ledger_event_hash(event)})
        self.events.append(event)
        return event

    async def get_by_id(
        self, workspace_id: UUID, session_id: UUID, event_id: UUID
    ) -> LedgerEvent | None:
        return next(
            (
                value
                for value in self.events
                if value.id == event_id
                and (value.workspace_id, value.session_id) == (workspace_id, session_id)
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


class MemoryResponses:
    def __init__(self) -> None:
        self.locked: list[UUID] = []
        self.requests: dict[UUID, CritiqueResponseRequest] = {}
        self.results: dict[UUID, CritiqueResponseResult] = {}

    async def lock_response(self, workspace_id: UUID, session_id: UUID, response_id: UUID) -> None:
        assert (workspace_id, session_id) == (U[0], U[1])
        self.locked.append(response_id)

    async def get_request(
        self, workspace_id: UUID, session_id: UUID, response_id: UUID
    ) -> CritiqueResponseRequest | None:
        del workspace_id, session_id
        return self.requests.get(response_id)

    async def get_result(
        self, workspace_id: UUID, session_id: UUID, response_id: UUID
    ) -> CritiqueResponseResult | None:
        del workspace_id, session_id
        return self.results.get(response_id)

    async def add_request(self, value: CritiqueResponseRequest) -> None:
        self.requests[value.response_id] = value

    async def add_result(self, value: CritiqueResponseResult) -> None:
        self.results[value.response_id] = value


def service(
    values: tuple[ReasoningArtifact, ...],
) -> tuple[
    CritiqueResponseCommitter,
    MemoryArtifacts,
    MemoryGraph,
    MemoryLedger,
    MemoryResponses,
]:
    artifacts = MemoryArtifacts(*values)
    graph = MemoryGraph(*values)
    ledger = MemoryLedger()
    responses = MemoryResponses()
    return (
        CritiqueResponseCommitter(
            cast(ReasoningArtifactStore, artifacts),
            cast(ReasoningGraphWriter, graph),
            cast(AgentProposalLedger, ledger),
            cast(CritiqueResponseStore, responses),
        ),
        artifacts,
        graph,
        ledger,
        responses,
    )


@req("FR-503")
@pytest.mark.parametrize(
    ("disposition", "resolution", "status"),
    [
        (
            CritiqueResponseDisposition.ACCEPT,
            Resolution.RESOLVED,
            CritiqueResponseResultStatus.RESOLVED,
        ),
        (
            CritiqueResponseDisposition.PARTIALLY_ACCEPT,
            Resolution.UNRESOLVED,
            CritiqueResponseResultStatus.UNRESOLVED,
        ),
        (
            CritiqueResponseDisposition.REJECT_WITH_JUSTIFICATION,
            Resolution.DISPUTED,
            CritiqueResponseResultStatus.DISPUTED,
        ),
        (
            CritiqueResponseDisposition.REVISE,
            Resolution.RESOLVED,
            CritiqueResponseResultStatus.REVISED,
        ),
        (
            CritiqueResponseDisposition.REQUEST_EVIDENCE,
            Resolution.UNRESOLVED,
            CritiqueResponseResultStatus.EVIDENCE_REQUESTED,
        ),
        (
            CritiqueResponseDisposition.REQUEST_SIMULATION,
            Resolution.UNRESOLVED,
            CritiqueResponseResultStatus.SIMULATION_DEFERRED,
        ),
        (
            CritiqueResponseDisposition.ABSTAIN,
            Resolution.UNRESOLVED,
            CritiqueResponseResultStatus.ABSTAINED,
        ),
    ],
)
async def test_all_seven_dispositions_append_resolution_and_explicit_result(
    disposition: CritiqueResponseDisposition,
    resolution: Resolution,
    status: CritiqueResponseResultStatus,
) -> None:
    values = response_artifacts()
    committer, artifacts, graph, ledger, responses = service(values)

    result = await committer.commit(command(disposition, values))

    assert result.resolution is resolution
    assert result.status is status
    critique_revision = artifacts.values[result.critique_revision_id]
    assert isinstance(critique_revision.payload, CritiquePayload)
    assert critique_revision.payload.resolution is resolution
    assert critique_revision.logical_id == values[1].logical_id
    assert critique_revision.version == 2
    assert critique_revision.supersedes_id == values[1].id
    metadata = responses.requests[result.response_id].execution_metadata
    assert metadata["provider"] == "mock"
    assert metadata["model"] == "critic-response-model"
    assert metadata["input_tokens"] == 21
    assert metadata["output_tokens"] == 8
    assert metadata["cost_usd"] == "0.0021"
    assert metadata["raw_artifact_ref"] == "raw/responses/trace.json#sha256:" + "b" * 64
    assert metadata["prompt_hash"] == "sha256:" + "a" * 64
    assert metadata["phase"] == "REVISE"
    assert metadata["context_hash"].startswith("sha256:")
    assert metadata["response_hash"].startswith("sha256:")
    response_event = ledger.events[-1]
    assert response_event.event_type == "CRITIQUE_RESPONDED"
    assert response_event.payload["result_status"] == status.value
    assert response_event.payload["attribution"]["provider"] == "mock"
    assert response_event.payload["attribution"]["input_tokens"] == 21
    assert any(edge.edge_type is GraphEdgeType.ATTACKS for edge in graph.edges)
    assert any(edge.edge_type is GraphEdgeType.SUPERSEDES for edge in graph.edges)


@req("FR-503")
async def test_revise_appends_same_kind_target_and_exact_coordinator_lineage() -> None:
    values = response_artifacts()
    committer, artifacts, graph, _ledger, _responses = service(values)

    result = await committer.commit(command(CritiqueResponseDisposition.REVISE, values))

    assert result.target_revision_id is not None
    revision = artifacts.values[result.target_revision_id]
    assert revision.kind is values[0].kind
    assert revision.logical_id == values[0].logical_id
    assert revision.owner_actor_id == values[0].owner_actor_id
    assert revision.version == values[0].version + 1
    assert revision.supersedes_id == values[0].id
    assert revision.parent_relationships == (
        ParentRelationship(edge_type=GraphEdgeType.RESPONDS_TO, target_artifact_id=values[1].id),
    )
    assert [edge.edge_type for edge in graph.edges].count(GraphEdgeType.SUPERSEDES) == 2
    assert [edge.edge_type for edge in graph.edges].count(GraphEdgeType.RESPONDS_TO) == 1
    responds = next(edge for edge in graph.edges if edge.edge_type is GraphEdgeType.RESPONDS_TO)
    assert responds.from_node == graph.nodes[revision.id].id
    assert responds.to_node == graph.nodes[values[1].id].id


@req("FR-503")
async def test_revising_attacked_critique_derives_attack_and_response_relationships() -> None:
    attacked_artifact = artifact(ArtifactKind.CLAIM, artifact_id=U[14], owner_id=U[4])
    target_values = artifact_data(ArtifactKind.CRITIQUE)
    target_values.update(
        {
            "id": U[10],
            "workspace_id": U[0],
            "session_id": U[1],
            "logical_id": U[60],
            "owner_actor_class": ActorClass.AGENT,
            "owner_actor_id": U[2],
            "round": 1,
            "payload": CritiquePayload(
                target_id=attacked_artifact.id,
                critique_type=CritiqueType.LOGICAL_FALLACY,
                severity=Severity.MEDIUM,
                argument="The inference is invalid.",
                resolution=Resolution.OPEN,
            ),
            "parent_relationships": (
                ParentRelationship(
                    edge_type=GraphEdgeType.ATTACKS,
                    target_artifact_id=attacked_artifact.id,
                ),
            ),
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    target_values["content_hash"] = artifact_content_hash(target_values)
    target = validate_artifact(target_values)
    response_values = artifact_data(ArtifactKind.CRITIQUE)
    response_values.update(
        {
            "id": U[11],
            "workspace_id": U[0],
            "session_id": U[1],
            "logical_id": U[61],
            "owner_actor_class": ActorClass.AGENT,
            "owner_actor_id": U[3],
            "round": 1,
            "payload": CritiquePayload(
                target_id=target.id,
                critique_type=CritiqueType.ALTERNATIVE_OMITTED,
                severity=Severity.HIGH,
                argument="The Critique omitted a valid interpretation.",
                resolution=Resolution.OPEN,
            ),
            "parent_relationships": (
                ParentRelationship(edge_type=GraphEdgeType.ATTACKS, target_artifact_id=target.id),
            ),
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    response_values["content_hash"] = artifact_content_hash(response_values)
    response_critique = validate_artifact(response_values)
    values = (target, response_critique, attacked_artifact)
    revision = ArtifactRevisionProposal(
        op="propose",
        kind=ArtifactKind.CRITIQUE,
        payload={
            "target_id": attacked_artifact.id,
            "critique_type": "LOGICAL_FALLACY",
            "severity": "MEDIUM",
            "argument": "The inference needs a narrower qualification.",
            "resolution": "UNRESOLVED",
        },
    )
    committer, artifacts, graph, _ledger, _responses = service(values)

    result = await committer.commit(
        command(
            CritiqueResponseDisposition.REVISE,
            values,
            proposed_revision=revision,
        )
    )

    assert result.target_revision_id is not None
    revised = artifacts.values[result.target_revision_id]
    assert revised.kind is ArtifactKind.CRITIQUE
    assert revised.parent_relationships == (
        ParentRelationship(
            edge_type=GraphEdgeType.ATTACKS,
            target_artifact_id=attacked_artifact.id,
        ),
        ParentRelationship(
            edge_type=GraphEdgeType.RESPONDS_TO,
            target_artifact_id=response_critique.id,
        ),
    )
    assert [edge.edge_type for edge in graph.edges].count(GraphEdgeType.ATTACKS) == 2
    assert [edge.edge_type for edge in graph.edges].count(GraphEdgeType.RESPONDS_TO) == 1


@req("FR-503")
async def test_exact_retry_returns_prior_result_without_duplicate_effects() -> None:
    values = response_artifacts()
    committer, artifacts, graph, ledger, responses = service(values)
    operation = command(CritiqueResponseDisposition.REVISE, values)

    first = await committer.commit(operation)
    counts = (len(artifacts.added), len(graph.edges), len(ledger.events))
    second = await committer.commit(operation)

    assert second == first
    assert (len(artifacts.added), len(graph.edges), len(ledger.events)) == counts
    assert responses.locked == [U[13], U[13]]


@req("FR-503")
async def test_exact_retry_survives_later_supersession_of_its_recorded_heads() -> None:
    values = response_artifacts()
    committer, artifacts, graph, ledger, _responses = service(values)
    operation = command(CritiqueResponseDisposition.REVISE, values)
    first = await committer.commit(operation)
    assert first.target_revision_id is not None
    for artifact_id in (first.critique_revision_id, first.target_revision_id):
        current = artifacts.values[artifact_id]
        artifacts.values[artifact_id] = current.model_copy(
            update={"status": LifecycleStatus.SUPERSEDED}
        )
    counts = (len(artifacts.added), len(graph.edges), len(ledger.events))

    replay = await committer.commit(operation)

    assert replay == first
    assert (len(artifacts.added), len(graph.edges), len(ledger.events)) == counts


@req("FR-503")
async def test_response_identity_reuse_with_different_content_fails_closed() -> None:
    values = response_artifacts()
    committer, artifacts, graph, ledger, _responses = service(values)
    await committer.commit(command(CritiqueResponseDisposition.ACCEPT, values))
    counts = (len(artifacts.added), len(graph.edges), len(ledger.events))

    with pytest.raises(ArtifactCommitError, match="conflicting prior commit"):
        await committer.commit(
            command(CritiqueResponseDisposition.ACCEPT, values, rationale="Different rationale")
        )

    assert (len(artifacts.added), len(graph.edges), len(ledger.events)) == counts


@req("FR-503")
@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"critique_version": 2}, "Critique head is stale"),
        ({"target_artifact_version": 2}, "target head is stale"),
        ({"responding_definition_id": U[4]}, "does not match its authorized reasoning context"),
    ],
)
async def test_stale_or_unauthorized_response_leaves_no_write(
    change: dict[str, object], message: str
) -> None:
    values = response_artifacts()
    committer, artifacts, graph, ledger, responses = service(values)

    with pytest.raises((ArtifactCommitError, ValueError), match=message):
        await committer.commit(command(CritiqueResponseDisposition.ACCEPT, values, **change))

    assert artifacts.added == []
    assert graph.edges == []
    assert ledger.events == []
    assert responses.requests == {}
    assert responses.results == {}


@req("FR-503")
async def test_human_owned_target_cannot_be_answered_automatically() -> None:
    target, critique, warrant = response_artifacts()
    values_data = target.model_dump(mode="python")
    values_data.update({"owner_actor_class": ActorClass.HUMAN, "owner_actor_id": U[4]})
    values_data["content_hash"] = artifact_content_hash(values_data)
    target = validate_artifact(values_data)
    critique_data = critique.model_dump(mode="python")
    critique_data["payload"] = critique.payload.model_copy(update={"target_id": target.id})
    critique_data["content_hash"] = artifact_content_hash(critique_data)
    critique = validate_artifact(critique_data)
    values = (target, critique, warrant)
    committer, artifacts, graph, ledger, responses = service(values)

    with pytest.raises(ArtifactCommitError, match="AGENT-owned"):
        await committer.commit(command(CritiqueResponseDisposition.ACCEPT, values))

    assert artifacts.added == []
    assert graph.edges == []
    assert ledger.events == []
    assert responses.requests == {}


@req("FR-503")
async def test_resolved_critique_cannot_receive_a_new_response_identity() -> None:
    target, critique, warrant = response_artifacts()
    critique_data = critique.model_dump(mode="python")
    critique_data["payload"] = critique.payload.model_copy(
        update={"resolution": Resolution.RESOLVED}
    )
    critique_data["content_hash"] = artifact_content_hash(critique_data)
    resolved = validate_artifact(critique_data)
    values = (target, resolved, warrant)
    committer, artifacts, graph, ledger, responses = service(values)

    with pytest.raises(ArtifactCommitError, match="resolved Critique"):
        await committer.commit(command(CritiqueResponseDisposition.ACCEPT, values))

    assert artifacts.added == []
    assert graph.edges == []
    assert ledger.events == []
    assert responses.requests == {}


@req("FR-503")
async def test_revise_rejects_kind_change_before_any_write() -> None:
    values = response_artifacts()
    invalid_revision = ArtifactRevisionProposal(
        op="propose",
        kind=ArtifactKind.ASSUMPTION,
        payload={
            "statement": "Changed kind",
            "basis": "Not permitted",
            "materiality": "HIGH",
            "challengeable": True,
        },
    )
    committer, artifacts, graph, ledger, responses = service(values)

    with pytest.raises(ArtifactCommitError, match="preserve artifact kind"):
        await committer.commit(
            command(
                CritiqueResponseDisposition.REVISE,
                values,
                proposed_revision=invalid_revision,
            )
        )

    assert artifacts.added == []
    assert graph.edges == []
    assert ledger.events == []
    assert responses.requests == {}


@req("FR-503")
async def test_sqlalchemy_response_store_maps_rows_and_never_commits() -> None:
    values = response_artifacts()
    operation = command(CritiqueResponseDisposition.ACCEPT, values)
    committer, _artifacts, _graph, _ledger, responses = service(values)
    result = await committer.commit(operation)
    request = responses.requests[result.response_id]
    session = MagicMock(spec=AsyncSession)
    store = SqlAlchemyCritiqueResponseStore(session)

    await store.add_request(request)
    request_row = session.add.call_args_list[0].args[0]
    await store.add_result(result)
    result_row = session.add.call_args_list[1].args[0]

    assert isinstance(request_row, CritiqueResponseRequestRow)
    assert request_row.request_hash == request.request_hash
    assert request_row.execution_metadata == dict(request.execution_metadata)
    assert isinstance(result_row, CritiqueResponseResultRow)
    assert result_row.status == "RESOLVED"
    assert session.flush.await_count == 2
    session.commit.assert_not_called()


@req("FR-503")
def test_response_models_are_registered_in_declarative_metadata() -> None:
    assert cast(Any, CritiqueResponseRequestRow.__table__).name == "critique_response_requests"
    assert cast(Any, CritiqueResponseResultRow.__table__).name == "critique_response_results"
    assert response_commit_id(U[13], "response-event") == response_commit_id(
        U[13], "response-event"
    )


@req("FR-503")
def test_revision_contract_does_not_relax_fact_or_evidence_creation_policy() -> None:
    for kind in (ArtifactKind.FACT, ArtifactKind.EVIDENCE):
        revision = ArtifactRevisionProposal.model_validate(
            {
                "op": "propose",
                "kind": kind,
                "payload": cast(Any, artifact_data(kind)["payload"]).model_dump(mode="json"),
            }
        )
        assert revision.kind is kind
        with pytest.raises(ValueError, match="may not propose"):
            ArtifactProposal.model_validate(revision.model_dump())


@req("FR-503")
async def test_evidence_revision_preserves_source_backed_provenance() -> None:
    claim = artifact(ArtifactKind.CLAIM, artifact_id=U[14], owner_id=U[4])
    target_values = artifact_data(ArtifactKind.EVIDENCE)
    target_values.update(
        {
            "id": U[10],
            "workspace_id": U[0],
            "session_id": U[1],
            "logical_id": U[60],
            "owner_actor_class": ActorClass.AGENT,
            "owner_actor_id": U[2],
            "round": 1,
            "payload": cast(Any, target_values["payload"]).model_copy(
                update={"claim_id": claim.id}
            ),
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    target_values["content_hash"] = artifact_content_hash(target_values)
    target = validate_artifact(target_values)
    critique_values = artifact_data(ArtifactKind.CRITIQUE)
    critique_values.update(
        {
            "id": U[11],
            "workspace_id": U[0],
            "session_id": U[1],
            "logical_id": U[61],
            "owner_actor_class": ActorClass.AGENT,
            "owner_actor_id": U[3],
            "round": 1,
            "payload": CritiquePayload(
                target_id=target.id,
                critique_type=CritiqueType.MEASUREMENT_ERROR,
                severity=Severity.HIGH,
                argument="The measurement needs qualification.",
                resolution=Resolution.OPEN,
            ),
            "parent_relationships": (
                ParentRelationship(edge_type=GraphEdgeType.ATTACKS, target_artifact_id=target.id),
            ),
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    critique_values["content_hash"] = artifact_content_hash(critique_values)
    critique = validate_artifact(critique_values)
    revision = ArtifactRevisionProposal.model_validate(
        {
            "op": "propose",
            "kind": ArtifactKind.EVIDENCE,
            "payload": {
                **target.payload.model_dump(mode="json"),
                "quote": "Qualified source quotation.",
            },
        }
    )
    values = (target, critique, claim)
    committer, artifacts, _graph, _ledger, _responses = service(values)

    result = await committer.commit(
        command(CritiqueResponseDisposition.REVISE, values, proposed_revision=revision)
    )

    assert result.target_revision_id is not None
    replacement = artifacts.values[result.target_revision_id]
    assert replacement.kind is ArtifactKind.EVIDENCE
    assert replacement.provenance == target.provenance
    assert replacement.source_references == target.source_references


@req("FR-503")
def test_response_migration_is_linear_append_only_tenant_safe_and_widens_only_response_edges() -> (
    None
):
    migration = (
        Path(__file__).parents[2] / "alembic" / "versions" / "20260907_0019_critique_responses.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision: str | None = "20260907_0018"' in migration
    assert '"critique_response_requests"' in migration
    assert '"critique_response_results"' in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "append-only" in migration
    assert "WHEN 'RESPONDS_TO' THEN {response_sources} AND to_kind = 'CRITIQUE'" in migration
    assert "'FACT', 'ASSUMPTION', 'INFERENCE', 'PROPOSITION'" in migration
    assert "else \"from_kind IN ('POSITION', 'CLAIM')\"" in migration
