"""SQLAlchemy implementation of the Phase 3 / Phase 10 reasoning-graph boundary."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause

from app.db.models.reasoning_graph import GraphEdgeRow, GraphNodeRow
from app.domain.reasoning import ActorClass, ArtifactKind, GraphEdgeType
from app.domain.reasoning_graph import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_PAGE_SIZE,
    DEFAULT_SUBGRAPH_DEPTH,
    MAX_ALLOWED_DEPTH,
    MAX_PAGE_SIZE,
    MAX_SUBGRAPH_DEPTH,
    GraphEdge,
    GraphNode,
    ReasoningGraphStore,
    TraversalResult,
)

__all__ = ["SqlAlchemyReasoningGraphStore"]


def _node_from_row(row: GraphNodeRow) -> GraphNode:
    return GraphNode(
        id=row.id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        kind=ArtifactKind(row.kind),
        ref_id=row.ref_id,
        label=row.label,
        attrs=row.attrs,
    )


def _edge_from_row(row: GraphEdgeRow) -> GraphEdge:
    return GraphEdge(
        id=row.id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        from_node=row.from_node,
        to_node=row.to_node,
        edge_type=GraphEdgeType(row.edge_type),
        weight=float(row.weight) if row.weight is not None else None,
        qualifier=row.qualifier,
        actor_class=ActorClass(row.actor_class),
        actor_id=row.actor_id,
    )


def _walk_sql(next_node_expr: str, join_cond: str) -> str:
    """Build a bounded, cycle-safe recursive-CTE walk over ``graph_edges``.

    ``path`` accumulates visited node ids so a node already on the current
    walk is never revisited (cycle safety); the walk still explores up to
    ``max_depth + 1`` hops so truncation can be detected precisely by the
    caller instead of guessed at.
    """
    return f"""
        WITH RECURSIVE walk(node_id, depth, path, edge_id) AS (
            SELECT r, 0, ARRAY[r]::uuid[], NULL::uuid
            FROM unnest(CAST(:root_ids AS uuid[])) AS r
            UNION ALL
            SELECT
                {next_node_expr} AS node_id,
                w.depth + 1,
                w.path || {next_node_expr},
                e.id
            FROM walk w
            JOIN graph_edges e
                ON {join_cond}
               AND e.workspace_id = :workspace_id
               AND e.session_id = :session_id
               AND (
                   CAST(:edge_types AS text[]) IS NULL
                   OR e.edge_type = ANY(CAST(:edge_types AS text[]))
               )
            WHERE w.depth < :max_depth + 1
              AND NOT ({next_node_expr} = ANY(w.path))
        )
        SELECT node_id, depth, edge_id FROM walk
    """


_BACKWARD_SQL = text(_walk_sql("e.from_node", "e.to_node = w.node_id"))
_FORWARD_SQL = text(_walk_sql("e.to_node", "e.from_node = w.node_id"))
_BOTH_SQL = text(
    _walk_sql(
        "(CASE WHEN e.to_node = w.node_id THEN e.from_node ELSE e.to_node END)",
        "(e.from_node = w.node_id OR e.to_node = w.node_id)",
    )
)


def _query_fingerprint(
    direction: Literal["backward", "forward", "both"],
    workspace_id: UUID,
    session_id: UUID,
    root_ids: tuple[UUID, ...],
    max_depth: int,
    edge_types: frozenset[GraphEdgeType] | None,
) -> str:
    query = {
        "direction": direction,
        "edge_types": (
            None if edge_types is None else sorted(edge_type.value for edge_type in edge_types)
        ),
        "max_depth": max_depth,
        "root_ids": sorted(str(root_id) for root_id in root_ids),
        "session_id": str(session_id),
        "workspace_id": str(workspace_id),
    }
    encoded = json.dumps(query, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _encode_cursor(offset: int, fingerprint: str) -> str:
    payload = json.dumps({"offset": offset, "query": fingerprint}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _parse_cursor(cursor: str) -> object:
    padded = cursor + "=" * (-len(cursor) % 4)
    return json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))


def _decode_cursor(cursor: str | None, fingerprint: str) -> int:
    if cursor is None:
        return 0
    try:
        payload = _parse_cursor(cursor)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError("invalid traversal cursor") from None
    if not isinstance(payload, dict) or set(payload) != {"offset", "query"}:
        raise ValueError("invalid traversal cursor")
    offset = payload["offset"]
    if payload["query"] != fingerprint:
        raise ValueError("invalid traversal cursor")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("invalid traversal cursor")
    return offset


class SqlAlchemyReasoningGraphStore:
    """Read and write graph projections within a caller-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_node(self, node: GraphNode) -> None:
        self._session.add(
            GraphNodeRow(
                id=node.id,
                workspace_id=node.workspace_id,
                session_id=node.session_id,
                kind=node.kind.value,
                ref_id=node.ref_id,
                label=node.label,
                attrs=dict(node.attrs),
            )
        )
        await self._session.flush()

    async def add_edge(self, edge: GraphEdge) -> None:
        self._session.add(
            GraphEdgeRow(
                id=edge.id,
                workspace_id=edge.workspace_id,
                session_id=edge.session_id,
                from_node=edge.from_node,
                to_node=edge.to_node,
                edge_type=edge.edge_type.value,
                weight=Decimal(str(edge.weight)) if edge.weight is not None else None,
                qualifier=dict(edge.qualifier),
                actor_class=edge.actor_class.value,
                actor_id=edge.actor_id,
            )
        )
        await self._session.flush()

    async def node_for_artifact(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> GraphNode | None:
        row = await self._session.scalar(
            select(GraphNodeRow).where(
                GraphNodeRow.workspace_id == workspace_id,
                GraphNodeRow.session_id == session_id,
                GraphNodeRow.ref_id == artifact_id,
            )
        )
        if row is None:
            return None
        return GraphNode(
            id=row.id,
            workspace_id=row.workspace_id,
            session_id=row.session_id,
            kind=ArtifactKind(row.kind),
            ref_id=row.ref_id,
            label=row.label,
            attrs=row.attrs,
        )

    async def _walk(
        self,
        sql: TextClause,
        direction: Literal["backward", "forward", "both"],
        workspace_id: UUID,
        session_id: UUID,
        root_ids: tuple[UUID, ...],
        max_depth: int,
        edge_types: frozenset[GraphEdgeType] | None,
        depth_cap: int,
        page_size: int,
        cursor: str | None,
    ) -> TraversalResult:
        if max_depth < 0:
            raise ValueError("max_depth must not be negative")
        if max_depth > depth_cap:
            raise ValueError(f"max_depth must not exceed {depth_cap}")
        if page_size < 1 or page_size > MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")

        fingerprint = _query_fingerprint(
            direction, workspace_id, session_id, root_ids, max_depth, edge_types
        )
        offset = _decode_cursor(cursor, fingerprint)
        rows = (
            await self._session.execute(
                sql,
                {
                    "root_ids": list(root_ids),
                    "workspace_id": workspace_id,
                    "session_id": session_id,
                    "max_depth": max_depth,
                    "edge_types": (
                        [edge_type.value for edge_type in edge_types]
                        if edge_types is not None
                        else None
                    ),
                },
            )
        ).all()

        within_bound = [row for row in rows if row.depth <= max_depth]
        truncated = len(within_bound) < len(rows)
        node_ids = sorted({row.node_id for row in within_bound})
        edge_ids = sorted({row.edge_id for row in within_bound if row.edge_id is not None})
        member_count = len(node_ids) + len(edge_ids)
        if offset > member_count or (offset == member_count and cursor is not None):
            raise ValueError("invalid traversal cursor")

        page_end = min(offset + page_size, member_count)
        node_start = min(offset, len(node_ids))
        node_end = min(page_end, len(node_ids))
        edge_start = max(0, offset - len(node_ids))
        edge_end = max(0, page_end - len(node_ids))
        page_node_ids = node_ids[node_start:node_end]
        page_edge_ids = edge_ids[edge_start:edge_end]

        nodes: tuple[GraphNode, ...] = ()
        if page_node_ids:
            node_rows = (
                await self._session.execute(
                    select(GraphNodeRow)
                    .where(
                        GraphNodeRow.workspace_id == workspace_id,
                        GraphNodeRow.session_id == session_id,
                        GraphNodeRow.id.in_(page_node_ids),
                    )
                    .order_by(GraphNodeRow.id)
                )
            ).scalars()
            nodes = tuple(_node_from_row(row) for row in node_rows)

        edges: tuple[GraphEdge, ...] = ()
        if page_edge_ids:
            edge_rows = (
                await self._session.execute(
                    select(GraphEdgeRow)
                    .where(
                        GraphEdgeRow.workspace_id == workspace_id,
                        GraphEdgeRow.session_id == session_id,
                        GraphEdgeRow.id.in_(page_edge_ids),
                    )
                    .order_by(GraphEdgeRow.id)
                )
            ).scalars()
            edges = tuple(_edge_from_row(row) for row in edge_rows)

        next_cursor = _encode_cursor(page_end, fingerprint) if page_end < member_count else None
        return TraversalResult(
            nodes=nodes,
            edges=edges,
            truncated=truncated,
            next_cursor=next_cursor,
        )

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
        return await self._walk(
            _BACKWARD_SQL,
            "backward",
            workspace_id,
            session_id,
            (node_id,),
            max_depth,
            edge_types,
            MAX_ALLOWED_DEPTH,
            page_size,
            cursor,
        )

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
        return await self._walk(
            _FORWARD_SQL,
            "forward",
            workspace_id,
            session_id,
            (node_id,),
            max_depth,
            edge_types,
            MAX_ALLOWED_DEPTH,
            page_size,
            cursor,
        )

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
        if not root_ids:
            raise ValueError("subgraph requires at least one root id")
        return await self._walk(
            _BOTH_SQL,
            "both",
            workspace_id,
            session_id,
            root_ids,
            max_depth,
            edge_types,
            MAX_SUBGRAPH_DEPTH,
            page_size,
            cursor,
        )


_GRAPH_STORE_PORT: type[ReasoningGraphStore] = SqlAlchemyReasoningGraphStore
