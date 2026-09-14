"""Immutable reasoning-graph domain models and read/write contracts."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.domain.reasoning import ActorClass, ArtifactKind, FrozenModel, GraphEdgeType

__all__ = [
    "GraphEdge",
    "GraphNode",
    "ReasoningGraphStore",
    "ReasoningGraphWriter",
    "TraversalResult",
]

#: Default and maximum hop count for trace_backward / trace_forward, per REASONING_GRAPH.md §5.
DEFAULT_MAX_DEPTH = 12
MAX_ALLOWED_DEPTH = 12

#: subgraph() uses a tighter radius bound (REASONING_GRAPH.md §5: "radius <= 5").
DEFAULT_SUBGRAPH_DEPTH = 2
MAX_SUBGRAPH_DEPTH = 5

#: Cursor pages follow the platform-wide maximum documented in API.md.
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 200


def _json_object(value: dict[str, Any]) -> dict[str, Any]:
    """Reject values that are not JSON serializable without changing their representation."""
    from app.domain.reasoning import canonical_json

    canonical_json(value)
    return value


class GraphNode(FrozenModel):
    """One cached projection of an existing reasoning artifact."""

    id: UUID
    workspace_id: UUID
    session_id: UUID
    kind: ArtifactKind
    ref_id: UUID
    label: str = Field(min_length=1)
    attrs: dict[str, Any] = Field(default_factory=dict)

    _attrs_json = field_validator("attrs")(_json_object)

    @field_validator("label")
    @classmethod
    def label_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("label must not be blank")
        return value


class GraphEdge(FrozenModel):
    """One typed directed relationship between two nodes in the same session."""

    id: UUID
    workspace_id: UUID
    session_id: UUID
    from_node: UUID
    to_node: UUID
    edge_type: GraphEdgeType
    weight: float | None = Field(default=None, ge=0, le=1)
    qualifier: dict[str, Any] = Field(default_factory=dict)
    actor_class: ActorClass
    actor_id: UUID

    _qualifier_json = field_validator("qualifier")(_json_object)

    @model_validator(mode="after")
    def no_self_loop(self) -> GraphEdge:
        if self.from_node == self.to_node:
            raise ValueError("graph edges cannot be self-loops")
        return self


class TraversalResult(FrozenModel):
    """A bounded, deduplicated set of nodes and edges reached by a traversal.

    ``truncated`` is ``True`` when the walk hit ``max_depth`` while unvisited
    neighbours remained. ``next_cursor`` instead signals that another page of
    the already bounded, deterministically ordered result remains.
    """

    nodes: tuple[GraphNode, ...] = Field(default_factory=tuple)
    edges: tuple[GraphEdge, ...] = Field(default_factory=tuple)
    truncated: bool = False
    next_cursor: str | None = None


@runtime_checkable
class ReasoningGraphWriter(Protocol):
    """Caller-transaction-scoped graph projection write boundary."""

    async def add_node(self, node: GraphNode) -> None: ...

    async def add_edge(self, edge: GraphEdge) -> None: ...

    async def node_for_artifact(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> GraphNode | None: ...


@runtime_checkable
class ReasoningGraphStore(ReasoningGraphWriter, Protocol):
    """Graph projection writer plus bounded, cycle-safe read traversals."""

    async def trace_backward(
        self,
        workspace_id: UUID,
        session_id: UUID,
        node_id: UUID,
        *,
        max_depth: int = DEFAULT_MAX_DEPTH,
        edge_types: frozenset[GraphEdgeType] | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> TraversalResult:
        """Walk edges ending at ``node_id`` backward to their sources, up to ``max_depth`` hops."""
        ...

    async def trace_forward(
        self,
        workspace_id: UUID,
        session_id: UUID,
        node_id: UUID,
        *,
        max_depth: int = DEFAULT_MAX_DEPTH,
        edge_types: frozenset[GraphEdgeType] | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> TraversalResult:
        """Walk edges starting at ``node_id`` forward to their targets, up to ``max_depth`` hops."""
        ...

    async def subgraph(
        self,
        workspace_id: UUID,
        session_id: UUID,
        root_ids: tuple[UUID, ...],
        *,
        max_depth: int = DEFAULT_SUBGRAPH_DEPTH,
        edge_types: frozenset[GraphEdgeType] | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> TraversalResult:
        """Walk both directions from every id in ``root_ids``, up to ``max_depth`` hops."""
        ...
