"""Application provenance contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from app.application.provenance import ProvenanceService
from app.domain.citations import (
    CitationResolution,
    CitationSnapshot,
    EvidenceCitation,
    ManualEvidenceCitation,
    SourceRetraction,
    SourceRetractionCommand,
)
from app.domain.knowledge import SourceStatus
from app.domain.phase3_api import Phase3ArtifactStore
from app.domain.reasoning import (
    ActorClass,
    ArtifactKind,
    Bearing,
    ClaimPayload,
    ClaimType,
    EvidencePayload,
    EvidenceProvenance,
    EvidenceRelation,
    GraphEdgeType,
    LifecycleStatus,
    Provenance,
    ProvenanceOrigin,
    ReasoningArtifact,
    ReviewStatus,
    SourceReference,
    Strength,
    TrustLevel,
    Verification,
    artifact_content_hash,
    validate_artifact,
)
from app.domain.reasoning_graph import GraphEdge, GraphNode, ReasoningGraphStore, TraversalResult
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 30))
NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)


def _artifact(
    kind: ArtifactKind, artifact_id: UUID, *, workspace_id: UUID = U[0]
) -> ReasoningArtifact:
    payload = (
        EvidencePayload(
            claim_id=U[3],
            relation=EvidenceRelation.SUPPORTS,
            quote="exact source statement",
            verification=Verification.UNVERIFIED,
            trust_level=TrustLevel.PRIMARY,
            weight="0.8",
            provenance_kind=EvidenceProvenance.HUMAN,
        )
        if kind is ArtifactKind.EVIDENCE
        else ClaimPayload(
            statement="result",
            claim_type=ClaimType.FACTUAL,
            direction=Bearing.SUPPORTS,
            strength=Strength.MODERATE,
            supporting_evidence_ids=(),
            opposing_evidence_ids=(),
            review_status=ReviewStatus.PROPOSED,
        )
    )
    values = {
        "id": artifact_id,
        "workspace_id": workspace_id,
        "session_id": U[1],
        "logical_id": artifact_id,
        "kind": kind,
        "schema_version": 1,
        "version": 1,
        "status": LifecycleStatus.ACTIVE,
        "supersedes_id": None,
        "owner_actor_class": ActorClass.HUMAN,
        "owner_actor_id": U[2],
        "round": 0,
        "payload": payload,
        "provenance": Provenance(origin=ProvenanceOrigin.HUMAN, reference="fixture"),
        "source_references": (
            (
                SourceReference(
                    reference="Primary source",
                    locator={"char_start": 0, "char_end": 10},
                    content_hash="sha256:" + "b" * 64,
                    retrieved_at=NOW,
                    source_timestamp=NOW,
                ),
            )
            if kind is ArtifactKind.EVIDENCE
            else ()
        ),
        "parent_relationships": (),
        "confidence": None,
        "metadata": {},
        "created_at": NOW,
        "updated_at": NOW,
    }
    values["content_hash"] = artifact_content_hash(values)
    return validate_artifact(values)


def _node(node_id: UUID, artifact_id: UUID, kind: ArtifactKind) -> GraphNode:
    return GraphNode(
        id=node_id,
        workspace_id=U[0],
        session_id=U[1],
        kind=kind,
        ref_id=artifact_id,
        label=kind.value.title(),
    )


def _edge(edge_id: UUID, source: GraphNode, target: GraphNode, kind: GraphEdgeType) -> GraphEdge:
    return GraphEdge(
        id=edge_id,
        workspace_id=U[0],
        session_id=U[1],
        from_node=source.id,
        to_node=target.id,
        edge_type=kind,
        actor_class=ActorClass.HUMAN,
        actor_id=U[2],
    )


def _resolution(evidence_id: UUID, status: SourceStatus = SourceStatus.READY) -> CitationResolution:
    citation = EvidenceCitation(
        citation_id=U[10],
        workspace_id=U[0],
        session_id=U[1],
        evidence_artifact_id=evidence_id,
        claim_artifact_id=U[3],
        actor_id=U[2],
        attached_at=NOW,
        snapshot=CitationSnapshot(
            namespace_id=U[11],
            source_id=U[12],
            document_id=U[13],
            chunk_id=U[14],
            citation="Primary source",
            locator={"char_start": 0, "char_end": 10},
            source_content_hash="sha256:" + "a" * 64,
            chunk_content_hash="sha256:" + "b" * 64,
            chunker_version="v1",
            source_timestamp=NOW,
            document_timestamp=NOW,
            retrieved_at=NOW,
            trust_level="PRIMARY",
            source_status=SourceStatus.READY,
        ),
    )
    return CitationResolution(
        citation=citation,
        current_source_status=status,
        retracted_at=NOW if status is SourceStatus.RETRACTED else None,
        retraction_reason="withdrawn study" if status is SourceStatus.RETRACTED else None,
    )


class Artifacts:
    def __init__(self, *values: ReasoningArtifact) -> None:
        self.values = {value.id: value for value in values}

    async def get(
        self, workspace_id: UUID, artifact_id: UUID, *, session_id: UUID | None = None
    ) -> ReasoningArtifact | None:
        value = self.values.get(artifact_id)
        if value is None or value.workspace_id != workspace_id:
            return None
        if session_id is not None and value.session_id != session_id:
            return None
        return value

    async def add(self, artifact: ReasoningArtifact) -> None:
        self.values[artifact.id] = artifact

    async def get_for_update(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> ReasoningArtifact | None:
        return await self.get(workspace_id, artifact_id, session_id=session_id)


class Graph:
    def __init__(self, root: GraphNode | None, traversal: TraversalResult) -> None:
        self.root = root
        self.traversal = traversal
        self.calls: list[tuple[int, int, str | None]] = []

    async def node_for_artifact(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> GraphNode | None:
        if (
            self.root is not None
            and self.root.workspace_id == workspace_id
            and self.root.session_id == session_id
            and self.root.ref_id == artifact_id
        ):
            return self.root
        return None

    async def trace_backward(
        self,
        workspace_id: UUID,
        session_id: UUID,
        node_id: UUID,
        **kwargs: int | str | None,
    ) -> TraversalResult:
        del workspace_id, session_id, node_id
        self.calls.append(
            (
                cast(int, kwargs["max_depth"]),
                cast(int, kwargs["page_size"]),
                cast(str | None, kwargs["cursor"]),
            )
        )
        return self.traversal


class Citations:
    def __init__(self, *values: CitationResolution) -> None:
        self.values = values

    async def citations_for_evidence(
        self, workspace_id: UUID, evidence_artifact_id: UUID
    ) -> tuple[CitationResolution, ...]:
        return tuple(
            value
            for value in self.values
            if value.citation.workspace_id == workspace_id
            and value.citation.evidence_artifact_id == evidence_artifact_id
        )

    async def attach_manual(self, command: ManualEvidenceCitation) -> EvidenceCitation:
        raise NotImplementedError

    async def resolve(self, workspace_id: UUID, citation_id: UUID) -> CitationResolution | None:
        return next(
            (
                value
                for value in self.values
                if value.citation.workspace_id == workspace_id
                and value.citation.citation_id == citation_id
            ),
            None,
        )

    async def retract_source(self, command: SourceRetractionCommand) -> SourceRetraction:
        raise NotImplementedError

    async def dependencies(
        self, workspace_id: UUID, source_id: UUID
    ) -> tuple[EvidenceCitation, ...]:
        return ()


@req("NFR-004")
async def test_provenance_enriches_evidence_and_preserves_adversarial_edge() -> None:
    root_artifact = _artifact(ArtifactKind.CLAIM, U[3])
    evidence_artifact = _artifact(ArtifactKind.EVIDENCE, U[4])
    root = _node(U[5], root_artifact.id, ArtifactKind.CLAIM)
    evidence = _node(U[6], evidence_artifact.id, ArtifactKind.EVIDENCE)
    attack = _edge(U[7], evidence, root, GraphEdgeType.ATTACKS)
    graph = Graph(
        root,
        TraversalResult(
            nodes=(root, evidence), edges=(attack,), truncated=True, next_cursor="next"
        ),
    )

    result = await ProvenanceService(
        cast(Phase3ArtifactStore, Artifacts(root_artifact, evidence_artifact)),
        cast(ReasoningGraphStore, graph),
        Citations(_resolution(evidence_artifact.id, SourceStatus.RETRACTED)),
    ).provenance_of(U[0], root_artifact.id, max_depth=4, page_size=20, cursor="cursor")

    assert result is not None
    assert result.root_artifact_id == root_artifact.id
    assert result.nodes == (
        result.nodes[0],
        result.nodes[1],
    )
    enriched = result.nodes[1]
    assert enriched.verification is Verification.UNVERIFIED
    assert enriched.citations[0].citation.snapshot.document_id == U[13]
    assert enriched.citations[0].citation.snapshot.chunk_id == U[14]
    assert enriched.citations[0].current_source_status is SourceStatus.RETRACTED
    assert result.edges[0].edge_type is GraphEdgeType.ATTACKS
    assert result.truncated is True
    assert result.next_cursor == "next"
    assert graph.calls == [(4, 20, "cursor")]


@req("NFR-004")
async def test_provenance_supports_branching_deduplicated_deterministic_traversal() -> None:
    root_artifact = _artifact(ArtifactKind.CLAIM, U[3])
    first_artifact = _artifact(ArtifactKind.EVIDENCE, U[4])
    second_artifact = _artifact(ArtifactKind.CLAIM, U[8])
    root = _node(U[5], root_artifact.id, ArtifactKind.CLAIM)
    first = _node(U[6], first_artifact.id, ArtifactKind.EVIDENCE)
    second = _node(U[9], second_artifact.id, ArtifactKind.CLAIM)
    edges = (
        _edge(U[15], first, root, GraphEdgeType.SUPPORTS),
        _edge(U[16], second, root, GraphEdgeType.CONTRADICTS),
    )
    traversal = TraversalResult(nodes=(root, first, second), edges=edges)

    result = await ProvenanceService(
        cast(Phase3ArtifactStore, Artifacts(root_artifact, first_artifact, second_artifact)),
        cast(ReasoningGraphStore, Graph(root, traversal)),
        Citations(),
    ).provenance_of(U[0], root_artifact.id)

    assert result is not None
    assert [node.graph_node.id for node in result.nodes] == [U[5], U[6], U[9]]
    assert len({node.graph_node.id for node in result.nodes}) == 3
    assert [edge.edge_type for edge in result.edges] == [
        GraphEdgeType.SUPPORTS,
        GraphEdgeType.CONTRADICTS,
    ]
    assert result.nodes[1].citations == ()


@req("NFR-004")
async def test_provenance_returns_root_only_when_no_upstream_nodes_exist() -> None:
    artifact = _artifact(ArtifactKind.CLAIM, U[3])
    root = _node(U[5], artifact.id, ArtifactKind.CLAIM)
    result = await ProvenanceService(
        cast(Phase3ArtifactStore, Artifacts(artifact)),
        cast(ReasoningGraphStore, Graph(root, TraversalResult(nodes=(root,), edges=()))),
        Citations(),
    ).provenance_of(U[0], artifact.id)
    assert result is not None
    assert result.nodes[0].graph_node == root
    assert result.edges == ()


@req("NFR-004")
async def test_provenance_hides_missing_cross_workspace_and_missing_projection() -> None:
    artifact = _artifact(ArtifactKind.CLAIM, U[3])
    root = _node(U[5], artifact.id, ArtifactKind.CLAIM)
    empty = TraversalResult()
    service = ProvenanceService(
        cast(Phase3ArtifactStore, Artifacts(artifact)),
        cast(ReasoningGraphStore, Graph(root, empty)),
        Citations(),
    )

    assert await service.provenance_of(U[20], artifact.id) is None
    assert await service.provenance_of(U[0], U[21]) is None
    assert (
        await ProvenanceService(
            cast(Phase3ArtifactStore, Artifacts(artifact)),
            cast(ReasoningGraphStore, Graph(None, empty)),
            Citations(),
        ).provenance_of(U[0], artifact.id)
        is None
    )
