"""Authenticated Prometheus exposition endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.ports.auth import WorkspaceRole
from app.security import require_roles

__all__ = ["router"]

router = APIRouter(tags=["operations"])


@router.get("/metrics", summary="Prometheus metrics", response_class=Response)
@require_roles(WorkspaceRole.ADMIN, WorkspaceRole.OPERATOR)
async def metrics(request: Request) -> Response:
    """Expose this replica's metrics only to operational roles."""
    body, content_type = request.app.state.metrics.render()
    return Response(content=body, headers={"Content-Type": content_type})
