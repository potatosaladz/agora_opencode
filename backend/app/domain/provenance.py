"""Typed artifact-provenance query results."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.domain.citations import CitationResolution
from app.domain.reasoning import FrozenModel, Verification
from app.domain.reasoning_graph import GraphEdge, GraphNode

__all__ = ["ProvenanceNode", "ProvenanceResult"]


class ProvenanceNode(FrozenModel):
    """A reasoning graph node with canonical evidence metadata when applicable."""

    graph_node: GraphNode
    artifact_version: int = Field(ge=1)
    verification: Verification | None = None
    citations: tuple[CitationResolution, ...] = Field(default_factory=tuple)


class ProvenanceResult(FrozenModel):
    """One bounded page of backward ancestry for an exact artifact version."""

    root_artifact_id: UUID
    root_artifact_version: int = Field(ge=1)
    root_node: GraphNode
    nodes: tuple[ProvenanceNode, ...] = Field(default_factory=tuple)
    edges: tuple[GraphEdge, ...] = Field(default_factory=tuple)
    truncated: bool
    max_depth: int
    next_cursor: str | None = None
