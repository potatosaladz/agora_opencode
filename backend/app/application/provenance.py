"""Application orchestration for artifact reasoning and citation provenance."""

from __future__ import annotations

from uuid import UUID

from app.domain.citations import CitationRepository, CitationResolution
from app.domain.phase3_api import Phase3ArtifactStore
from app.domain.provenance import ProvenanceNode, ProvenanceResult
from app.domain.reasoning import ArtifactKind, EvidencePayload
from app.domain.reasoning_graph import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_PAGE_SIZE,
    ReasoningGraphStore,
)

__all__ = ["ProvenanceService"]


class ProvenanceService:
    """Join bounded graph ancestry to PostgreSQL-authoritative evidence citations."""

    def __init__(
        self,
        artifacts: Phase3ArtifactStore,
        graph: ReasoningGraphStore,
        citations: CitationRepository,
    ) -> None:
        self._artifacts = artifacts
        self._graph = graph
        self._citations = citations

    async def provenance_of(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
        *,
        max_depth: int = DEFAULT_MAX_DEPTH,
        page_size: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ProvenanceResult | None:
        """Return exact-version ancestry, or ``None`` for absent/tenant-hidden roots."""
        root_artifact = await self._artifacts.get(workspace_id, artifact_id)
        if root_artifact is None:
            return None
        root_node = await self._graph.node_for_artifact(
            workspace_id, root_artifact.session_id, artifact_id
        )
        if root_node is None:
            return None

        traversal = await self._graph.trace_backward(
            workspace_id,
            root_artifact.session_id,
            root_node.id,
            max_depth=max_depth,
            page_size=page_size,
            cursor=cursor,
        )
        enriched: list[ProvenanceNode] = []
        for node in traversal.nodes:
            artifact = (
                root_artifact
                if node.ref_id == root_artifact.id
                else await self._artifacts.get(
                    workspace_id, node.ref_id, session_id=root_artifact.session_id
                )
            )
            if artifact is None or artifact.kind is not node.kind:
                # A graph projection must never replace canonical artifact authority.
                return None
            verification = None
            citation_values: tuple[CitationResolution, ...] = ()
            if node.kind is ArtifactKind.EVIDENCE:
                if not isinstance(artifact.payload, EvidencePayload):
                    return None
                verification = artifact.payload.verification
                citation_values = await self._citations.citations_for_evidence(
                    workspace_id, artifact.id
                )
            enriched.append(
                ProvenanceNode(
                    graph_node=node,
                    artifact_version=artifact.version,
                    verification=verification,
                    citations=citation_values,
                )
            )

        return ProvenanceResult(
            root_artifact_id=root_artifact.id,
            root_artifact_version=root_artifact.version,
            root_node=root_node,
            nodes=tuple(enriched),
            edges=traversal.edges,
            truncated=traversal.truncated,
            max_depth=max_depth,
            next_cursor=traversal.next_cursor,
        )
