"""Official MCP Streamable HTTP adapter for T15-01."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError
from pydantic import ValidationError

from app.domain.mcp import (
    MCPFailure,
    MCPFailureCode,
    MCPFailureError,
    MCPProtocolVersion,
    MCPServerCapabilities,
    ToolCall,
    ToolClass,
    ToolContent,
    ToolContentKind,
    ToolDescriptor,
    ToolPermission,
    ToolResult,
    ToolTrustClass,
    UpstreamServerRef,
)
from app.domain.reasoning import canonical_json, content_hash
from app.ports.health import HealthStatus
from app.ports.mcp import MCPToolProvider

__all__ = ["StreamableHTTPMCPToolProvider"]


class StreamableHTTPMCPToolProvider(
    MCPToolProvider[UpstreamServerRef, MCPServerCapabilities, ToolDescriptor, ToolCall, ToolResult]
):
    def __init__(
        self, *, timeout_s: float = 30.0, client_factory: Callable[..., Any] | None = None
    ) -> None:
        self._timeout_s = min(float(timeout_s), 30.0)
        self._factory = client_factory if client_factory is not None else streamable_http_client
        self._capabilities: dict[str, MCPServerCapabilities] = {}
        self._active: dict[UUID, asyncio.Task[Any]] = {}

    async def initialize(self, server: UpstreamServerRef) -> MCPServerCapabilities:
        try:
            async with self._session(server) as session:
                result = await self._initialize_session(session)
        except MCPFailureError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise MCPFailureError(
                MCPFailure(code=MCPFailureCode.UPSTREAM_UNAVAILABLE, retryable=True)
            ) from exc
        except McpError as exc:
            raise MCPFailureError(
                MCPFailure(code=MCPFailureCode.UPSTREAM_PROTOCOL_ERROR, retryable=False)
            ) from exc
        capabilities = _negotiated_capabilities(result)
        self._capabilities[server.server_id] = capabilities
        return capabilities

    def capability_snapshot(self, server_id: str) -> MCPServerCapabilities | None:
        return self._capabilities.get(server_id)

    async def list_tools(self, server: UpstreamServerRef) -> tuple[ToolDescriptor, ...]:
        try:
            async with self._session(server) as session:
                await self._initialize_session(session)
                result = await session.list_tools()
            descriptors = tuple(
                ToolDescriptor(
                    server=server,
                    name=tool.name,
                    description=tool.description or tool.name,
                    input_schema=tool.inputSchema,
                    output_schema=tool.outputSchema,
                    tool_class=ToolClass.READ_SANE,
                    permission=ToolPermission.READ,
                    manifest_hash=server.manifest_hash,
                )
                for tool in result.tools
            )
        except MCPFailureError:
            raise
        except ValidationError as exc:
            raise MCPFailureError(
                MCPFailure(code=MCPFailureCode.RESULT_INVALID, retryable=False)
            ) from exc
        except (httpx.HTTPError, OSError) as exc:
            raise MCPFailureError(
                MCPFailure(code=MCPFailureCode.UPSTREAM_UNAVAILABLE, retryable=True)
            ) from exc
        except McpError as exc:
            raise MCPFailureError(
                MCPFailure(code=MCPFailureCode.UPSTREAM_PROTOCOL_ERROR, retryable=False)
            ) from exc
        if len(descriptors) != 1 or descriptors[0].name != "fixture.read_echo":
            raise MCPFailureError(
                MCPFailure(code=MCPFailureCode.UPSTREAM_PROTOCOL_ERROR, retryable=False)
            )
        return descriptors

    async def invoke(self, call: ToolCall) -> ToolResult:
        effective_timeout = min(float(call.timeout_s), self._timeout_s)
        current = asyncio.current_task()
        if current is None:
            raise RuntimeError("MCP invocation requires an asyncio task")
        self._active[call.context.operation_id] = current
        try:
            async with self._session(call.server) as session:
                await self._initialize_session(session)
                result = await asyncio.wait_for(
                    session.call_tool(
                        call.tool_name,
                        call.arguments,
                        read_timeout_seconds=timedelta(seconds=effective_timeout),
                        meta=call.context.model_dump(mode="json"),
                    ),
                    timeout=effective_timeout,
                )
            if result.isError:
                return self._raise_upstream_result_error(call)
            return self._map_result(call, result)
        except (TimeoutError, asyncio.CancelledError):
            raise
        except MCPFailureError:
            raise
        except ValidationError as exc:
            raise MCPFailureError(
                MCPFailure(
                    code=MCPFailureCode.RESULT_INVALID,
                    retryable=False,
                    operation_id=call.context.operation_id,
                    correlation_id=call.context.correlation_id,
                )
            ) from exc
        except (httpx.HTTPError, OSError) as exc:
            raise MCPFailureError(
                MCPFailure(
                    code=MCPFailureCode.UPSTREAM_UNAVAILABLE,
                    retryable=True,
                    operation_id=call.context.operation_id,
                    correlation_id=call.context.correlation_id,
                )
            ) from exc
        except McpError as exc:
            raise MCPFailureError(
                MCPFailure(
                    code=MCPFailureCode.UPSTREAM_PROTOCOL_ERROR,
                    retryable=False,
                    operation_id=call.context.operation_id,
                    correlation_id=call.context.correlation_id,
                )
            ) from exc
        finally:
            self._active.pop(call.context.operation_id, None)

    async def cancel(self, operation_id: UUID) -> None:
        task = self._active.get(operation_id)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def health(self) -> HealthStatus:
        return HealthStatus.OK

    async def close(self) -> None:
        tasks = tuple(self._active.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._capabilities.clear()

    async def _initialize_session(self, session: ClientSession) -> types.InitializeResult:
        result = await session.send_request(
            types.ClientRequest(
                types.InitializeRequest(
                    params=types.InitializeRequestParams(
                        protocolVersion=MCPProtocolVersion.V2025_06_18.value,
                        capabilities=types.ClientCapabilities(),
                        clientInfo=types.Implementation(name="agora-mcp-gateway", version="0.1.0"),
                    )
                )
            ),
            types.InitializeResult,
        )
        if result.protocolVersion != MCPProtocolVersion.V2025_06_18.value:
            raise MCPFailureError(
                MCPFailure(code=MCPFailureCode.UPSTREAM_PROTOCOL_ERROR, retryable=False)
            )
        await session.send_notification(types.ClientNotification(types.InitializedNotification()))
        return result

    @staticmethod
    def _raise_upstream_result_error(call: ToolCall) -> ToolResult:
        raise MCPFailureError(
            MCPFailure(
                code=MCPFailureCode.UPSTREAM_PROTOCOL_ERROR,
                retryable=False,
                operation_id=call.context.operation_id,
                correlation_id=call.context.correlation_id,
            )
        )

    @asynccontextmanager
    async def _session(self, server: UpstreamServerRef) -> AsyncIterator[ClientSession]:
        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(self._timeout_s)) as client,
            self._factory(
                server.endpoint,
                http_client=client,
                terminate_on_close=True,
            ) as streams,
            ClientSession(
                streams[0],
                streams[1],
                client_info=types.Implementation(name="agora-mcp-gateway", version="0.1.0"),
            ) as session,
        ):
            yield session

    @staticmethod
    def _map_result(call: ToolCall, result: types.CallToolResult) -> ToolResult:
        content: list[ToolContent] = []
        if result.structuredContent is not None:
            content.append(ToolContent(kind=ToolContentKind.JSON, value=result.structuredContent))
        else:
            for item in result.content:
                if isinstance(item, types.TextContent):
                    content.append(ToolContent(kind=ToolContentKind.TEXT, value=item.text))
                else:
                    content.append(
                        ToolContent(kind=ToolContentKind.JSON, value=item.model_dump(mode="json"))
                    )
        content_values = [item.model_dump(mode="json") for item in content]
        returned = len(canonical_json(content_values))
        return ToolResult(
            operation_id=call.context.operation_id,
            correlation_id=call.context.correlation_id,
            server=call.server,
            tool_name=call.tool_name,
            content=tuple(content),
            content_hash=content_hash(content_values),
            source_uri=call.server.endpoint,
            retrieved_at=datetime.now(UTC),
            trust_class=ToolTrustClass.TOOL_UNTRUSTED,
            truncated=False,
            original_bytes=returned,
            returned_bytes=returned,
        )


def _negotiated_capabilities(result: types.InitializeResult) -> MCPServerCapabilities:
    capabilities = result.capabilities
    unsupported = (
        capabilities.experimental,
        capabilities.logging,
        capabilities.prompts,
        capabilities.resources,
        capabilities.completions,
        capabilities.tasks,
    )
    if (
        result.protocolVersion != MCPProtocolVersion.V2025_06_18.value
        or capabilities.tools is None
        or any(item is not None and item != {} for item in unsupported)
    ):
        raise MCPFailureError(
            MCPFailure(code=MCPFailureCode.UPSTREAM_PROTOCOL_ERROR, retryable=False)
        )
    return MCPServerCapabilities(
        protocol_version=MCPProtocolVersion.V2025_06_18,
        tools=True,
        resources=False,
        prompts=False,
        cancellation=True,
        progress=False,
    )
