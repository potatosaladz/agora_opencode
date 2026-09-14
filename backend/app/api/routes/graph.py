"""Authenticated read-only boundary for the existing reasoning graph store."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from app.api.errors import not_found
from app.api.graph_contracts import GraphSubgraphRequest
from app.common.errors import ValidationFailed
from app.common.ids import parse_id, public_id
from app.domain.reasoning import GraphEdgeType
from app.domain.reasoning_graph import TraversalResult
from app.ports.auth import WorkspaceRole
from app.security import current_principal, require_roles

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])
_READ = tuple(WorkspaceRole)


def _parse_public_id(resource: str, value: str, field: str) -> UUID:
    try:
        return parse_id(resource, value)
    except ValueError as exc:
        raise ValidationFailed(f"{field} contains a malformed public identifier") from exc


def _public_node(node: Any) -> dict[str, Any]:
    return {
        "id": public_id("graph_node", node.id),
        "workspace_id": public_id("workspace", node.workspace_id),
        "session_id": public_id("session", node.session_id),
        "kind": node.kind.value,
        "ref_id": public_id("artifact", node.ref_id),
        "label": node.label,
        "attrs": dict(node.attrs),
    }


def _public_edge(edge: Any) -> dict[str, Any]:
    actor_resource = {
        "HUMAN": "user",
        "AGENT": "agent",
        "SERVICE": "service",
        "POLICY": "policy",
    }[edge.actor_class.value]
    return {
        "id": public_id("graph_edge", edge.id),
        "workspace_id": public_id("workspace", edge.workspace_id),
        "session_id": public_id("session", edge.session_id),
        "from_node": public_id("graph_node", edge.from_node),
        "to_node": public_id("graph_node", edge.to_node),
        "edge_type": edge.edge_type.value,
        "weight": edge.weight,
        "qualifier": dict(edge.qualifier),
        "actor_class": edge.actor_class.value,
        "actor_id": public_id(actor_resource, edge.actor_id),
    }


def _response(result: TraversalResult, request: Request) -> JSONResponse:
    principal = current_principal(request)
    return JSONResponse(
        {
            "data": {
                "nodes": [_public_node(node) for node in result.nodes],
                "edges": [_public_edge(edge) for edge in result.edges],
                "truncated": result.truncated,
                "next_cursor": result.next_cursor,
            },
            "meta": {
                "request_id": str(request.state.correlation_id),
                "workspace_id": public_id("workspace", principal.workspace_id),
            },
        }
    )


@router.post("/subgraph")
@require_roles(*_READ)
# trace: FR-805, NFR-004, NFR-010, NFR-019
async def get_graph_subgraph(request: Request, body: GraphSubgraphRequest) -> JSONResponse:
    """Expose the existing bounded traversal without adding graph authority."""
    principal = current_principal(request)
    session_id = _parse_public_id("session", body.session_id, "session_id")
    root_ids = tuple(_parse_public_id("graph_node", value, "root_ids") for value in body.root_ids)
    edge_types = (
        frozenset(GraphEdgeType(value) for value in body.edge_types)
        if body.edge_types is not None
        else None
    )

    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:
        # Radius zero uses the same tenant/session-scoped traversal to prove every root
        # is visible before the caller's requested traversal is evaluated.
        visible = await tx.graph.subgraph(
            principal.workspace_id,
            session_id,
            root_ids,
            max_depth=0,
            page_size=len(root_ids),
        )
        if {node.id for node in visible.nodes} != set(root_ids):
            raise not_found("graph root")
        try:
            result = await tx.graph.subgraph(
                principal.workspace_id,
                session_id,
                root_ids,
                max_depth=body.max_depth,
                edge_types=edge_types,
                page_size=body.page_size,
                cursor=body.cursor,
            )
        except ValueError as exc:
            raise ValidationFailed(str(exc)) from exc
    return _response(result, request)
