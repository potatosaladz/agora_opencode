"""Application tests for atomic artifact lifecycle orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.application.artifact_commit import ArtifactCommitService, ArtifactEventContext
from app.domain import (
    ActorClass,
    ArtifactCommitError,
    ArtifactKind,
    Bearing,
    ClaimPayload,
    ClaimType,
    GraphEdge,
    GraphEdgeType,
    GraphNode,
    LedgerAppend,
    LedgerEvent,
    LedgerVerification,
    LifecycleStatus,
    ParentRelationship,
    Provenance,
    ProvenanceOrigin,
    ReasoningArtifact,
    ReviewStatus,
    Strength,
    artifact_content_hash,
    ledger_event_hash,
    ledger_payload_hash,
    validate_artifact,
)
from tests.traceability import req

U1 = UUID("018f0000-0000-7000-8000-000000000001")
U2 = UUID("018f0000-0000-7000-8000-000000000002")
U3 = UUID("018f0000-0000-7000-8000-000000000003")
U4 = UUID("018f0000-0000-7000-8000-000000000004")
U5 = UUID("018f0000-0000-7000-8000-000000000005")
U6 = UUID("018f0000-0000-7000-8000-000000000006")
U7 = UUID("018f0000-0000-7000-8000-000000000007")
U8 = UUID("018f0000-0000-7000-8000-000000000008")
NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)


def _artifact(
    *,
    artifact_id: UUID = U1,
    version: int = 1,
    supersedes_id: UUID | None = None,
    status: LifecycleStatus = LifecycleStatus.ACTIVE,
    statement: str = "Initial claim",
    parent_relationships: tuple[ParentRelationship, ...] = (),
) -> ReasoningArtifact:
    data: dict[str, object] = {
        "id": artifact_id,
        "workspace_id": U2,
        "session_id": U3,
        "logical_id": U4,
        "kind": ArtifactKind.CLAIM,
        "schema_version": 1,
        "version": version,
        "status": status,
        "supersedes_id": supersedes_id,
        "owner_actor_class": ActorClass.HUMAN,
        "owner_actor_id": U5,
        "round": 0,
        "payload": ClaimPayload(
            statement=statement,
            claim_type=ClaimType.FACTUAL,
            direction=Bearing.SUPPORTS,
            strength=Strength.MODERATE,
            supporting_evidence_ids=(),
            opposing_evidence_ids=(),
            review_status=ReviewStatus.PROPOSED,
        ),
        "provenance": Provenance(origin=ProvenanceOrigin.HUMAN, reference="unit-test"),
        "source_references": (),
        "parent_relationships": parent_relationships,
        "confidence": None,
        "metadata": {},
        "created_at": NOW,
        "updated_at": NOW,
    }
    data["content_hash"] = artifact_content_hash(data)
    return validate_artifact(data)


def _context(event_id: UUID = U6) -> ArtifactEventContext:
    return ArtifactEventContext(
        event_id=event_id,
        correlation_id=U7,
        actor_class=ActorClass.HUMAN,
        actor_id=U5,
        recorded_at=NOW,
    )


class _Artifacts:
    def __init__(self, *values: ReasoningArtifact) -> None:
        self.values = {value.id: value for value in values}
        self.lifecycle: list[tuple[UUID, LifecycleStatus]] = []

    async def add(self, artifact: ReasoningArtifact) -> None:
        self.values[artifact.id] = artifact

    async def get_for_update(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> ReasoningArtifact | None:
        candidate = self.values.get(artifact_id)
        if candidate is None:
            return None
        if (candidate.workspace_id, candidate.session_id) != (workspace_id, session_id):
            return None
        return candidate

    async def set_lifecycle(
        self,
        workspace_id: UUID,
        session_id: UUID,
        artifact_id: UUID,
        status: LifecycleStatus,
        *,
        updated_at: datetime,
    ) -> None:
        current = self.values[artifact_id]
        assert (current.workspace_id, current.session_id) == (workspace_id, session_id)
        self.values[artifact_id] = current.model_copy(
            update={"status": status, "updated_at": updated_at}
        )
        self.lifecycle.append((artifact_id, status))


class _Graph:
    def __init__(self, *nodes: GraphNode) -> None:
        self.nodes = {node.ref_id: node for node in nodes}
        self.edges: list[GraphEdge] = []

    async def add_node(self, node: GraphNode) -> None:
        self.nodes[node.ref_id] = node

    async def add_edge(self, edge: GraphEdge) -> None:
        self.edges.append(edge)

    async def node_for_artifact(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> GraphNode | None:
        node = self.nodes.get(artifact_id)
        if node is None or (node.workspace_id, node.session_id) != (workspace_id, session_id):
            return None
        return node


class _Ledger:
    def __init__(self) -> None:
        self.events: list[LedgerEvent] = []

    async def append(self, event: LedgerAppend) -> LedgerEvent:
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

    async def read(
        self, workspace_id: UUID, session_id: UUID, *, from_seq: int = 1, limit: int = 1000
    ) -> tuple[LedgerEvent, ...]:
        return tuple(self.events[from_seq - 1 :][:limit])

    async def verify(self, workspace_id: UUID, session_id: UUID) -> LedgerVerification:
        head = self.events[-1].event_hash if self.events else "sha256:" + "0" * 64
        return LedgerVerification(valid=True, event_count=len(self.events), head_hash=head)


@req("FR-302", "FR-303")
async def test_commit_writes_typed_row_node_and_id_only_event() -> None:
    artifacts, graph, ledger = _Artifacts(), _Graph(), _Ledger()
    artifact = _artifact()

    result = await ArtifactCommitService(artifacts, graph, ledger).commit(
        artifact, node_id=U8, label="Initial claim", context=_context()
    )

    assert result.artifact == artifact
    assert graph.nodes[artifact.id].attrs == {"logical_id": str(U4), "version": 1}
    assert result.event.event_type == "ARTIFACT_COMMITTED"
    assert result.event.payload == {
        "artifact_id": str(U1),
        "kind": "CLAIM",
        "logical_id": str(U4),
        "version": 1,
    }


@req("FR-302", "FR-303")
async def test_commit_projects_declared_parent_relationships() -> None:
    target = GraphNode(
        id=U8,
        workspace_id=U2,
        session_id=U3,
        kind=ArtifactKind.CLAIM,
        ref_id=U6,
        label="Parent claim",
    )
    graph = _Graph(target)
    artifact = _artifact(
        parent_relationships=(
            ParentRelationship(edge_type=GraphEdgeType.DERIVED_FROM, target_artifact_id=U6),
        )
    )

    await ArtifactCommitService(_Artifacts(), graph, _Ledger()).commit(
        artifact,
        node_id=U7,
        relationship_edge_ids=(U5,),
        label="Derived claim",
        context=_context(),
    )

    assert graph.edges[0].edge_type is GraphEdgeType.DERIVED_FROM
    assert (graph.edges[0].from_node, graph.edges[0].to_node) == (U7, U8)

    with pytest.raises(ArtifactCommitError, match="each parent relationship"):
        await ArtifactCommitService(_Artifacts(), graph, _Ledger()).commit(
            artifact, node_id=U1, label="Missing edge ID", context=_context()
        )


@req("FR-302")
async def test_revision_supersedes_previous_and_projects_forward_to_predecessor() -> None:
    previous = _artifact()
    previous_node = GraphNode(
        id=U8,
        workspace_id=U2,
        session_id=U3,
        kind=ArtifactKind.CLAIM,
        ref_id=U1,
        label="Initial claim",
    )
    artifacts, graph, ledger = _Artifacts(previous), _Graph(previous_node), _Ledger()
    revision = _artifact(artifact_id=U6, version=2, supersedes_id=U1, statement="Revised claim")

    result = await ArtifactCommitService(artifacts, graph, ledger).revise(
        revision,
        node_id=U7,
        edge_id=U5,
        label="Revised claim",
        reason="Evidence changed",
        context=_context(U2),
    )

    assert artifacts.lifecycle == [(U1, LifecycleStatus.SUPERSEDED)]
    assert graph.edges == [
        GraphEdge(
            id=U5,
            workspace_id=U2,
            session_id=U3,
            from_node=U7,
            to_node=U8,
            edge_type=GraphEdgeType.SUPERSEDES,
            qualifier={"reason": "Evidence changed"},
            actor_class=ActorClass.HUMAN,
            actor_id=U5,
        )
    ]
    assert result.event.event_type == "ARTIFACT_REVISED"


@req("FR-303")
async def test_withdraw_changes_only_lifecycle_and_appends_reason() -> None:
    artifact = _artifact()
    warrant = GraphNode(
        id=U7,
        workspace_id=U2,
        session_id=U3,
        kind=ArtifactKind.CLAIM,
        ref_id=U8,
        label="Withdrawal warrant",
    )
    artifacts, graph, ledger = _Artifacts(artifact), _Graph(warrant), _Ledger()

    result = await ArtifactCommitService(artifacts, graph, ledger).withdraw(
        U2,
        U3,
        U1,
        reason="Author retracted claim",
        warrant_artifact_ids=(U8,),
        context=_context(),
    )

    assert artifacts.lifecycle == [(U1, LifecycleStatus.WITHDRAWN)]
    assert result.artifact.status is LifecycleStatus.WITHDRAWN
    assert result.artifact.content_hash == artifact.content_hash
    assert graph.nodes == {U8: warrant}
    assert graph.edges == []
    assert result.event.payload["reason"] == "Author retracted claim"
    assert result.event.payload["warrant_artifact_ids"] == (str(U8),)

    with pytest.raises(ArtifactCommitError, match="warrant artifact"):
        await ArtifactCommitService(_Artifacts(artifact), graph, _Ledger()).withdraw(
            U2,
            U3,
            U1,
            reason="Missing warrant",
            warrant_artifact_ids=(),
            context=_context(),
        )
    with pytest.raises(ArtifactCommitError, match="has no graph projection"):
        await ArtifactCommitService(_Artifacts(artifact), graph, _Ledger()).withdraw(
            U2,
            U3,
            U1,
            reason="Fabricated warrant",
            warrant_artifact_ids=(U6,),
            context=_context(),
        )


@req("FR-302", "FR-303")
@pytest.mark.parametrize("operation", ["missing", "inactive", "wrong-version", "missing-node"])
async def test_revision_rejects_conflicting_preconditions(operation: str) -> None:
    previous = _artifact(
        status=LifecycleStatus.WITHDRAWN if operation == "inactive" else LifecycleStatus.ACTIVE
    )
    artifacts = _Artifacts() if operation == "missing" else _Artifacts(previous)
    graph = _Graph()
    if operation != "missing-node":
        graph.nodes[U1] = GraphNode(
            id=U8,
            workspace_id=U2,
            session_id=U3,
            kind=ArtifactKind.CLAIM,
            ref_id=U1,
            label="Initial claim",
        )
    revision = _artifact(
        artifact_id=U6,
        version=3 if operation == "wrong-version" else 2,
        supersedes_id=U1,
        statement="Revised claim",
    )

    with pytest.raises(ArtifactCommitError):
        await ArtifactCommitService(artifacts, graph, _Ledger()).revise(
            revision,
            node_id=U7,
            edge_id=U5,
            label="Revised claim",
            reason="Correction",
            context=_context(U2),
        )
