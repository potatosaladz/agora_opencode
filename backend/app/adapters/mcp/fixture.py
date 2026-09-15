"""Deterministic external MCP fixture used only by T15-01 acceptance tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

__all__ = ["create_fixture_app"]


def create_fixture_app() -> Starlette:
    server = Server("agora-fixture", "0.1.0")

    list_tools_handler = cast(
        Callable[
            [Callable[[], Awaitable[list[types.Tool]]]], Callable[[], Awaitable[list[types.Tool]]]
        ],
        server.list_tools(),
    )

    @list_tools_handler
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="fixture.read_echo",
                description="Return the deterministic fixture payload.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "value": {"type": "string", "maxLength": 128},
                        "delay_ms": {"type": "integer", "minimum": 0, "maximum": 30000},
                        "fail": {"type": "boolean"},
                    },
                    "required": ["value"],
                    "additionalProperties": False,
                },
                outputSchema={
                    "type": "object",
                    "properties": {"value": {"type": "string"}, "fixture": {"const": True}},
                    "required": ["value", "fixture"],
                    "additionalProperties": False,
                },
            )
        ]

    call_tool_handler = cast(
        Callable[
            [Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]],
            Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
        ],
        server.call_tool(),
    )

    @call_tool_handler
    async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name != "fixture.read_echo":
            raise ValueError("unknown fixture tool")
        if arguments.get("fail") is True:
            raise RuntimeError("fixture upstream failure")
        delay_ms = arguments.get("delay_ms", 0)
        if not isinstance(delay_ms, int) or delay_ms < 0 or delay_ms > 30000:
            raise ValueError("invalid fixture delay")
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)
        return {"value": arguments["value"], "fixture": True}

    manager = StreamableHTTPSessionManager(
        app=server,
        stateless=True,
        session_idle_timeout=None,
        max_request_body_size=64 * 1024,
    )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        del app
        async with manager.run():
            yield

    async def mcp(scope: Scope, receive: Receive, send: Send) -> None:
        await manager.handle_request(scope, receive, send)

    async def health(request: Any) -> Any:
        from starlette.responses import JSONResponse

        return JSONResponse({"status": "ok", "service": "mcp-fixture"})

    return Starlette(
        routes=[
            Mount("/mcp", app=mcp),
            Route("/health", health, methods=["GET"]),
        ],
        lifespan=lifespan,
    )
