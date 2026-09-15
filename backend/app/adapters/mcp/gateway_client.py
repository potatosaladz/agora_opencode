"""Official MCP client boundary used by the reasoning-worker activity."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError
from pydantic import ValidationError

from app.domain.mcp import (
    MCPCallContext,
    MCPFailure,
    MCPFailureCode,
    MCPProtocolVersion,
    MCPServerCapabilities,
    ToolCall,
    ToolResult,
)

__all__ = ["GatewayMCPClient", "MCPGatewayCallError"]


class MCPGatewayCallError(ValueError):
    def __init__(self, failure: MCPFailure) -> None:
        super().__init__(failure.code.value)
        self.failure = failure


class GatewayMCPClient:
    def __init__(self, endpoint: str, token: str) -> None:
        self._endpoint = endpoint
        self._token = token
        self._capabilities: MCPServerCapabilities | None = None

    @property
    def capability_snapshot(self) -> MCPServerCapabilities | None:
        return self._capabilities

    async def discover(self, context: MCPCallContext) -> tuple[str, ...]:
        timeout = _remaining_timeout(context, 30.0)
        try:
            async with self._session(timeout) as session:
                result = await asyncio.wait_for(
                    session.list_tools(params=types.PaginatedRequestParams(_meta=_meta(context))),
                    timeout=timeout,
                )
        except MCPGatewayCallError:
            raise
        except asyncio.CancelledError as exc:
            raise MCPGatewayCallError(_failure(MCPFailureCode.CANCELLED, context)) from exc
        except TimeoutError as exc:
            raise MCPGatewayCallError(
                _failure(MCPFailureCode.TIMEOUT, context, retryable=True)
            ) from exc
        except (httpx.HTTPError, OSError) as exc:
            raise MCPGatewayCallError(
                _failure(MCPFailureCode.UPSTREAM_UNAVAILABLE, context, retryable=True)
            ) from exc
        except McpError as exc:
            raise MCPGatewayCallError(
                _failure(MCPFailureCode.UPSTREAM_PROTOCOL_ERROR, context)
            ) from exc
        _raise_failure(result.meta)
        return tuple(tool.name for tool in result.tools)

    async def invoke(self, call: ToolCall) -> ToolResult:
        timeout = _remaining_timeout(call.context, float(call.timeout_s))
        try:
            async with self._session(timeout) as session:
                discovered = await asyncio.wait_for(
                    session.list_tools(
                        params=types.PaginatedRequestParams(_meta=_meta(call.context))
                    ),
                    timeout=timeout,
                )
                failure = _parse_failure(discovered.meta)
                if failure is not None:
                    result: types.CallToolResult | None = None
                elif call.tool_name not in {tool.name for tool in discovered.tools}:
                    result = None
                    failure = _failure(MCPFailureCode.TOOL_NOT_FOUND, call.context)
                else:
                    result = await asyncio.wait_for(
                        session.call_tool(
                            call.tool_name,
                            call.arguments,
                            read_timeout_seconds=timedelta(seconds=timeout),
                            meta=_call_meta(call),
                        ),
                        timeout=timeout,
                    )
        except MCPGatewayCallError:
            raise
        except asyncio.CancelledError as exc:
            raise MCPGatewayCallError(_failure(MCPFailureCode.CANCELLED, call.context)) from exc
        except TimeoutError as exc:
            raise MCPGatewayCallError(
                _failure(MCPFailureCode.TIMEOUT, call.context, retryable=True)
            ) from exc
        except (httpx.HTTPError, OSError) as exc:
            raise MCPGatewayCallError(
                _failure(MCPFailureCode.UPSTREAM_UNAVAILABLE, call.context, retryable=True)
            ) from exc
        except McpError as exc:
            raise MCPGatewayCallError(
                _failure(MCPFailureCode.UPSTREAM_PROTOCOL_ERROR, call.context)
            ) from exc
        if failure is not None:
            raise MCPGatewayCallError(failure)
        if result is None:
            raise MCPGatewayCallError(_failure(MCPFailureCode.RESULT_INVALID, call.context))
        _raise_failure(result.meta)
        if result.isError or result.structuredContent is None:
            raise MCPGatewayCallError(_failure(MCPFailureCode.RESULT_INVALID, call.context))
        value = dict(result.structuredContent)
        value.pop("untrusted", None)
        try:
            mapped = ToolResult.model_validate_json(json.dumps(value))
        except ValidationError as exc:
            raise MCPGatewayCallError(
                _failure(MCPFailureCode.RESULT_INVALID, call.context)
            ) from exc
        if (
            mapped.operation_id != call.context.operation_id
            or mapped.correlation_id != call.context.correlation_id
            or mapped.server != call.server
            or mapped.tool_name != call.tool_name
        ):
            raise MCPGatewayCallError(_failure(MCPFailureCode.RESULT_INVALID, call.context))
        return mapped

    @asynccontextmanager
    async def _session(self, timeout_s: float) -> AsyncIterator[ClientSession]:
        headers = _authorization_headers(self._token)
        async with (
            httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(timeout_s),
            ) as client,
            streamable_http_client(self._endpoint, http_client=client) as streams,
            ClientSession(
                streams[0],
                streams[1],
                client_info=types.Implementation(name="agora-reasoning-worker", version="0.1.0"),
            ) as session,
        ):
            initialized = await session.send_request(
                types.ClientRequest(
                    types.InitializeRequest(
                        params=types.InitializeRequestParams(
                            protocolVersion=MCPProtocolVersion.V2025_06_18.value,
                            capabilities=types.ClientCapabilities(),
                            clientInfo=types.Implementation(
                                name="agora-reasoning-worker", version="0.1.0"
                            ),
                        )
                    )
                ),
                types.InitializeResult,
            )
            if initialized.protocolVersion != MCPProtocolVersion.V2025_06_18.value:
                raise MCPGatewayCallError(
                    MCPFailure(code=MCPFailureCode.UPSTREAM_PROTOCOL_ERROR, retryable=False)
                )
            unsupported = (
                initialized.capabilities.experimental,
                initialized.capabilities.logging,
                initialized.capabilities.prompts,
                initialized.capabilities.resources,
                initialized.capabilities.completions,
                initialized.capabilities.tasks,
            )
            if initialized.capabilities.tools is None or any(
                item is not None and item != {} for item in unsupported
            ):
                raise MCPGatewayCallError(
                    MCPFailure(code=MCPFailureCode.UPSTREAM_PROTOCOL_ERROR, retryable=False)
                )
            capabilities = MCPServerCapabilities(
                protocol_version=MCPProtocolVersion(initialized.protocolVersion),
                tools=True,
                resources=False,
                prompts=False,
                cancellation=True,
                progress=False,
            )
            self._capabilities = capabilities
            await session.send_notification(
                types.ClientNotification(types.InitializedNotification())
            )
            yield session


def _remaining_timeout(context: MCPCallContext, ceiling_s: float) -> float:
    remaining = (context.deadline_at - datetime.now(UTC)).total_seconds()
    timeout = min(float(ceiling_s), 30.0, remaining)
    if timeout <= 0:
        raise MCPGatewayCallError(_failure(MCPFailureCode.TIMEOUT, context, retryable=True))
    return timeout


def _failure(
    code: MCPFailureCode,
    context: MCPCallContext,
    *,
    retryable: bool = False,
) -> MCPFailure:
    return MCPFailure(
        code=code,
        retryable=retryable,
        operation_id=context.operation_id,
        correlation_id=context.correlation_id,
    )


def _parse_failure(metadata: dict[str, object] | None) -> MCPFailure | None:
    if not metadata or "failure" not in metadata:
        return None
    envelope = metadata["failure"]
    if not isinstance(envelope, dict):
        raise MCPGatewayCallError(MCPFailure(code=MCPFailureCode.RESULT_INVALID, retryable=False))
    try:
        return MCPFailure.model_validate_json(json.dumps(envelope))
    except (ValidationError, TypeError, ValueError) as exc:
        raise MCPGatewayCallError(
            MCPFailure(code=MCPFailureCode.RESULT_INVALID, retryable=False)
        ) from exc


def _raise_failure(metadata: dict[str, object] | None) -> None:
    failure = _parse_failure(metadata)
    if failure is not None:
        raise MCPGatewayCallError(failure)


def _authorization_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _call_meta(call: ToolCall) -> dict[str, object]:
    metadata: dict[str, object] = call.context.model_dump(mode="json")
    metadata["timeout_s"] = str(call.timeout_s)
    return metadata


def _meta(context: MCPCallContext) -> types.RequestParams.Meta:
    return types.RequestParams.Meta(**context.model_dump(mode="json"))
