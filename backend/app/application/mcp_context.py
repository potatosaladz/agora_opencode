"""Trusted session and exact-agent affinity validation for MCP calls."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from app.application.mcp_gateway import MCPContextAuthority, MCPContextAuthorizationError
from app.domain.coordinator_policy import EffectiveMembershipStore
from app.domain.mcp import MCPCallContext
from app.ports.mcp import WorkloadPrincipal

__all__ = ["SessionMCPContextAuthority"]


StoreFactory = Callable[[MCPCallContext], AbstractAsyncContextManager[EffectiveMembershipStore]]


class SessionMCPContextAuthority(MCPContextAuthority):
    def __init__(self, stores: StoreFactory) -> None:
        self._stores = stores

    async def validate(self, context: MCPCallContext, principal: WorkloadPrincipal) -> None:
        if principal.subject != context.workload_subject:
            raise MCPContextAuthorizationError("workload subject does not match trusted context")
        if principal.service_role != "reasoning-worker":
            raise MCPContextAuthorizationError("workload service role is not authorized")
        async with self._stores(context) as store:
            membership = await store.membership(
                context.workspace_id,
                context.session_id,
                round=context.round,
            )
        if (
            membership.workspace_id != context.workspace_id
            or membership.session_id != context.session_id
            or membership.round != context.round
        ):
            raise MCPContextAuthorizationError("membership snapshot identity does not match")
        matching = tuple(
            definition
            for definition in membership.definitions
            if definition.id == context.agent_definition_id
            and definition.version == context.agent_definition_version
        )
        if len(matching) != 1:
            raise MCPContextAuthorizationError(
                "workspace, session, and exact agent affinity failed"
            )
