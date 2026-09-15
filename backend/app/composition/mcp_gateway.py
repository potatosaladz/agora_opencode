"""Composition root for the stateless mcp-gateway deployment role."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import uvicorn
from starlette.applications import Starlette

from app.adapters.auth_workload import JWTWorkloadTokenVerifier
from app.adapters.mcp.gateway_server import create_gateway_app
from app.adapters.mcp.streamable_http import StreamableHTTPMCPToolProvider
from app.application.mcp_context import SessionMCPContextAuthority
from app.application.mcp_gateway import MCPGateway
from app.config.settings import Settings, get_settings
from app.db import Database, create_database
from app.db.coordinator_policy import SqlAlchemyCoordinatorPolicyStore
from app.domain.coordinator_policy import EffectiveMembershipStore
from app.domain.mcp import MCPCallContext, UpstreamServerRef
from app.observability.logging import configure_logging, register_secret_literal

__all__ = ["GatewayRuntime", "build_gateway", "run_gateway"]


@dataclass(slots=True)
class GatewayRuntime:
    app: Starlette
    database: Database
    provider: StreamableHTTPMCPToolProvider

    async def close(self) -> None:
        try:
            await self.provider.close()
        finally:
            await self.database.close()


def build_gateway(settings: Settings) -> GatewayRuntime:
    if not settings.mcp_workload_secret.get_secret_value():
        raise ValueError("mcp_workload_secret is required by the gateway role")
    register_secret_literal(settings.mcp_workload_secret.get_secret_value())
    database = create_database(settings)
    provider = StreamableHTTPMCPToolProvider(timeout_s=settings.mcp_timeout_s)
    server = UpstreamServerRef(
        server_id=settings.mcp_fixture_server_id,
        version=1,
        endpoint=settings.mcp_fixture_endpoint,
        manifest_hash=settings.mcp_fixture_manifest_hash,
    )

    @asynccontextmanager
    async def stores(context: MCPCallContext) -> AsyncIterator[EffectiveMembershipStore]:
        async with database.session(context.workspace_id) as session:
            yield SqlAlchemyCoordinatorPolicyStore(session)

    gateway = MCPGateway(
        provider,
        JWTWorkloadTokenVerifier(
            secret=settings.mcp_workload_secret.get_secret_value(),
            issuer=settings.mcp_workload_issuer,
            audience=settings.mcp_workload_audience,
            allowed_subject=settings.mcp_workload_subject,
        ),
        SessionMCPContextAuthority(stores),
        server,
        allowed_subject=settings.mcp_workload_subject,
    )
    return GatewayRuntime(create_gateway_app(gateway, server), database, provider)


async def run_gateway(settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    configure_logging(level=resolved.log_level, fmt=resolved.log_format)
    runtime = build_gateway(resolved)
    config = uvicorn.Config(
        runtime.app,
        host=resolved.host,
        port=resolved.mcp_gateway_port,
        log_config=None,
        access_log=False,
    )
    try:
        await uvicorn.Server(config).serve()
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(run_gateway())
