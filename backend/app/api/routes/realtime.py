"""Authenticated ledger-backed realtime session stream."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query, Request
from starlette.responses import StreamingResponse

from app.api.errors import not_found
from app.common.ids import parse_id
from app.ports.auth import WorkspaceRole
from app.security import current_principal, require_roles

router = APIRouter(prefix="/api/v1", tags=["reasoning"])
_READ = (
    WorkspaceRole.ADMIN,
    WorkspaceRole.RESEARCHER,
    WorkspaceRole.OPERATOR,
    WorkspaceRole.VIEWER,
)


@router.get("/sessions/{session_id}/events/stream")
@require_roles(*_READ)
async def stream_session_events(
    request: Request,
    session_id: str,
    since: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[int | None, Header(alias="Last-Event-ID", ge=0)] = None,
) -> StreamingResponse:
    principal = current_principal(request)
    try:
        internal_id = parse_id("session", session_id)
        after = last_event_id if last_event_id is not None else since
    except ValueError as exc:
        raise not_found("session") from exc

    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:
        if await tx.sessions.get(principal.workspace_id, internal_id) is None:
            raise not_found("session")

    return StreamingResponse(
        request.app.state.container.realtime_gateway.stream(
            principal.workspace_id, internal_id, after=after
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
