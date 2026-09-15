"""Streamable HTTP MCP server boundary for the stateless gateway."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import McpError
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

from app.domain.mcp import (
    MCPCallContext,
    MCPFailure,
    MCPFailureCode,
    MCPFailureError,
    ToolCall,
    ToolDescriptor,
    ToolFailure,
    ToolFailureCode,
    ToolResult,
    UpstreamServerRef,
    tool_args_hash,
)

__all__ = ["create_gateway_app"]


class GatewayHandler(Protocol):
    async def initialize(self) -> object: ...

    async def list_tools(
        self, token: str, context: MCPCallContext
    ) -> tuple[ToolDescriptor, ...]: ...

    async def invoke(self, token: str, call: ToolCall) -> ToolResult: ...


def create_gateway_app(gateway: GatewayHandler, server: UpstreamServerRef) -> Starlette:
    mcp_server = Server("agora-mcp-gateway", "0.1.0")

    async def list_tools(request: types.ListToolsRequest) -> types.ServerResult:
        context: MCPCallContext | None = None
        try:
            context = _context(mcp_server, request.params)
            descriptors = await gateway.list_tools(_token(mcp_server), context)
        except (MCPFailureError, ValidationError) as exc:
            failure = _expected_failure(exc, context_code=MCPFailureCode.INVALID_CONTEXT)
            return types.ServerResult(
                types.ListToolsResult(tools=[], _meta={"failure": failure.model_dump(mode="json")})
            )
        except Exception as exc:
            raise _internal_error() from exc
        return types.ServerResult(
            types.ListToolsResult(
                tools=[
                    types.Tool(
                        name=item.name,
                        description=item.description,
                        inputSchema=item.input_schema,
                    )
                    for item in descriptors
                ]
            )
        )

    async def call_tool(request: types.CallToolRequest) -> types.ServerResult:
        try:
            context = _context(mcp_server, request.params)
            arguments = request.params.arguments or {}
            remaining_s = (context.deadline_at - datetime.now(UTC)).total_seconds()
            if remaining_s <= 0:
                return types.ServerResult(
                    _failure_result(
                        MCPFailure(
                            code=MCPFailureCode.TIMEOUT,
                            retryable=True,
                            operation_id=context.operation_id,
                            correlation_id=context.correlation_id,
                        )
                    )
                )
            timeout = min(_timeout(request.params), 30.0, remaining_s)
            call = ToolCall(
                context=context,
                server=server,
                tool_name=request.params.name,
                arguments=arguments,
                args_hash=tool_args_hash(arguments),
                timeout_s=Decimal(str(timeout)),
            )
            result = await gateway.invoke(_token(mcp_server), call)
        except ValidationError as exc:
            failure = _expected_failure(exc, context_code=MCPFailureCode.INVALID_ARGUMENTS)
            return types.ServerResult(_failure_result(failure))
        except MCPFailureError as exc:
            return types.ServerResult(_failure_result(_expected_failure(exc)))
        except Exception as exc:
            raise _internal_error() from exc
        structured: dict[str, Any] = result.model_dump(mode="json")
        structured["untrusted"] = True
        return types.ServerResult(
            types.CallToolResult(
                content=[
                    types.TextContent(type="text", text=json.dumps(structured, sort_keys=True))
                ],
                structuredContent=structured,
                isError=False,
            )
        )

    mcp_server.request_handlers[types.ListToolsRequest] = list_tools
    mcp_server.request_handlers[types.CallToolRequest] = call_tool

    async def health(request: Any) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "mcp-gateway"})

    async def ready(request: Any) -> JSONResponse:
        try:
            await gateway.initialize()
        except Exception:
            return JSONResponse({"status": "down", "service": "mcp-gateway"}, status_code=503)
        return JSONResponse({"status": "ok", "service": "mcp-gateway"})

    manager = StreamableHTTPSessionManager(
        app=mcp_server,
        stateless=True,
        session_idle_timeout=None,
        max_request_body_size=64 * 1024,
    )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        del app
        async with manager.run():
            await gateway.initialize()
            yield

    async def mcp(scope: Scope, receive: Receive, send: Send) -> None:
        await manager.handle_request(scope, receive, send)

    return Starlette(
        routes=[
            Mount("/mcp", app=mcp),
            Route("/health", health, methods=["GET"]),
            Route("/ready", ready, methods=["GET"]),
        ],
        lifespan=lifespan,
    )


def _token(server: Server[Any, Any]) -> str:
    request = server.request_context.request
    if request is None:
        return ""
    parts = str(request.headers.get("authorization", "")).split()
    return parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else ""


def _context(server: Server[Any, Any], params: Any) -> MCPCallContext:
    metadata = getattr(params, "meta", None)
    values = dict(metadata or {})
    values.pop("progressToken", None)
    values.pop("timeout_s", None)
    return MCPCallContext.model_validate_json(json.dumps(values))


def _timeout(params: Any) -> float:
    metadata = dict(getattr(params, "meta", None) or {})
    value = metadata.get("timeout_s")
    try:
        timeout = float(Decimal(str(value)))
    except (ArithmeticError, ValueError) as exc:
        raise MCPFailureError(
            MCPFailure(code=MCPFailureCode.INVALID_ARGUMENTS, retryable=False)
        ) from exc
    if timeout <= 0 or timeout > 30:
        raise MCPFailureError(
            MCPFailure(
                code=MCPFailureCode.INVALID_ARGUMENTS,
                retryable=False,
            )
        )
    return timeout


def _failure_result(failure: MCPFailure) -> types.CallToolResult:
    return types.CallToolResult(
        content=[],
        isError=True,
        _meta={"failure": failure.model_dump(mode="json")},
    )


def _expected_failure(
    error: MCPFailureError | ValidationError,
    *,
    context_code: MCPFailureCode = MCPFailureCode.RESULT_INVALID,
) -> MCPFailure:
    if isinstance(error, ValidationError):
        return MCPFailure(code=context_code, retryable=False)
    if isinstance(error.failure, MCPFailure):
        return error.failure
    return _map_tool_failure(error.failure)


def _map_tool_failure(failure: ToolFailure) -> MCPFailure:
    codes = {
        ToolFailureCode.AUTH_REQUIRED: MCPFailureCode.AUTHENTICATION_FAILED,
        ToolFailureCode.FORBIDDEN: MCPFailureCode.AUTHORIZATION_DENIED,
        ToolFailureCode.SERVER_NOT_REGISTERED: MCPFailureCode.AUTHORIZATION_DENIED,
        ToolFailureCode.TOOL_NOT_FOUND: MCPFailureCode.TOOL_NOT_FOUND,
        ToolFailureCode.MANIFEST_DRIFT: MCPFailureCode.UPSTREAM_PROTOCOL_ERROR,
        ToolFailureCode.ARGUMENT_INVALID: MCPFailureCode.INVALID_ARGUMENTS,
        ToolFailureCode.APPROVAL_REQUIRED: MCPFailureCode.AUTHORIZATION_DENIED,
        ToolFailureCode.RATE_LIMITED: MCPFailureCode.UPSTREAM_UNAVAILABLE,
        ToolFailureCode.BUDGET_EXCEEDED: MCPFailureCode.AUTHORIZATION_DENIED,
        ToolFailureCode.TOOL_TIMEOUT: MCPFailureCode.TIMEOUT,
        ToolFailureCode.TOOL_CANCELLED: MCPFailureCode.CANCELLED,
        ToolFailureCode.UPSTREAM_UNAVAILABLE: MCPFailureCode.UPSTREAM_UNAVAILABLE,
        ToolFailureCode.PROTOCOL_ERROR: MCPFailureCode.UPSTREAM_PROTOCOL_ERROR,
        ToolFailureCode.RESULT_INVALID: MCPFailureCode.RESULT_INVALID,
        ToolFailureCode.RESULT_TOO_LARGE: MCPFailureCode.RESULT_INVALID,
        ToolFailureCode.INJECTION_SUSPECTED: MCPFailureCode.RESULT_INVALID,
        ToolFailureCode.OPERATION_CONFLICT: MCPFailureCode.INVALID_CONTEXT,
    }
    return MCPFailure(
        code=codes[failure.code],
        retryable=failure.retryable,
        operation_id=failure.operation_id,
        correlation_id=failure.correlation_id,
    )


def _internal_error() -> McpError:
    return McpError(types.ErrorData(code=types.INTERNAL_ERROR, message="Internal server error"))
