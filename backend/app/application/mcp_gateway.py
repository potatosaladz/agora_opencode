"""T15-01 gateway orchestration without persistence or artifact authority."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.domain.mcp import (
    MCPCallContext,
    MCPFailure,
    MCPFailureCode,
    MCPFailureError,
    MCPServerCapabilities,
    ToolCall,
    ToolContentKind,
    ToolDescriptor,
    ToolFailure,
    ToolFailureCode,
    ToolResult,
    ToolTrustClass,
    UpstreamServerRef,
)
from app.ports.mcp import InvalidWorkloadTokenError, MCPToolProvider, WorkloadPrincipal

__all__ = [
    "MCPContextAuthority",
    "MCPContextAuthorizationError",
    "MCPGateway",
    "MCPGatewayError",
]

_LOG = logging.getLogger("agora.application.mcp_gateway")


class MCPContextAuthorizationError(ValueError):
    pass


class MCPContextAuthority(Protocol):
    async def validate(self, context: MCPCallContext, principal: WorkloadPrincipal) -> None: ...


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> WorkloadPrincipal: ...


class MCPGatewayError(MCPFailureError):
    pass


@dataclass(frozen=True, slots=True)
class MCPCallIdentity:
    server: UpstreamServerRef
    tool_name: str
    context: MCPCallContext
    args_hash: str


class MCPGateway:
    def __init__(
        self,
        provider: MCPToolProvider[
            UpstreamServerRef, MCPServerCapabilities, ToolDescriptor, ToolCall, ToolResult
        ],
        token_verifier: TokenVerifier,
        context_authority: MCPContextAuthority,
        fixture_server: UpstreamServerRef,
        *,
        allowed_subject: str = "reasoning-worker",
    ) -> None:
        self._provider = provider
        self._token_verifier = token_verifier
        self._context_authority = context_authority
        self._fixture_server = fixture_server
        self._allowed_subject = allowed_subject
        self._dedup: dict[UUID, tuple[MCPCallIdentity, ToolResult]] = {}
        self._inflight: dict[UUID, tuple[MCPCallIdentity, asyncio.Future[ToolResult]]] = {}
        self._tools: tuple[ToolDescriptor, ...] = ()
        self._capabilities: object | None = None
        self._lock = asyncio.Lock()
        self._max_dedup_entries = 1024

    async def initialize(self) -> object:
        capabilities = await self._provider.initialize(self._fixture_server)
        tools = await self._provider.list_tools(self._fixture_server)
        if not capabilities.tools or capabilities.resources or capabilities.prompts:
            raise MCPGatewayError(
                ToolFailure(
                    code=ToolFailureCode.PROTOCOL_ERROR,
                    detail="upstream did not negotiate the authorized tools-only capability",
                    retryable=False,
                )
            )
        if not self._fixture_manifest_valid(tools):
            raise MCPGatewayError(
                ToolFailure(
                    code=ToolFailureCode.PROTOCOL_ERROR,
                    detail="fixture tool manifest is not authorized",
                    retryable=False,
                )
            )
        self._capabilities = capabilities
        self._tools = tools
        return capabilities

    async def list_tools(self, token: str, context: MCPCallContext) -> tuple[ToolDescriptor, ...]:
        principal = await self._verify(token, context)
        await self._authorize(context, principal)
        if not self._tools:
            await self.initialize()
        return self._tools

    async def invoke(self, token: str, call: ToolCall) -> ToolResult:
        principal = await self._verify(token, call.context)
        await self._authorize(call.context, principal)
        if call.server != self._fixture_server:
            raise MCPGatewayError(
                self._failure(ToolFailureCode.FORBIDDEN, call, "fixture authorization failed")
            )
        if call.tool_name != "fixture.read_echo":
            raise MCPGatewayError(
                self._failure(ToolFailureCode.TOOL_NOT_FOUND, call, "tool not found")
            )
        forbidden_context_arguments = {
            "workload_subject",
            "workspace_id",
            "session_id",
            "agent_definition_id",
            "agent_definition_version",
            "operation_id",
            "correlation_id",
            "round",
            "deadline_at",
            "timeout_s",
        }
        if forbidden_context_arguments.intersection(call.arguments):
            raise MCPGatewayError(
                self._failure(
                    ToolFailureCode.ARGUMENT_INVALID,
                    call,
                    "trusted context fields are not tool arguments",
                )
            )
        if not self._fixture_arguments_valid(call.arguments):
            raise MCPGatewayError(
                self._failure(ToolFailureCode.ARGUMENT_INVALID, call, "tool arguments are invalid")
            )
        remaining_s = (call.context.deadline_at - datetime.now(UTC)).total_seconds()
        effective_timeout = min(float(call.timeout_s), 30.0, remaining_s)
        if effective_timeout <= 0:
            raise MCPGatewayError(
                self._failure(ToolFailureCode.TOOL_TIMEOUT, call, "trusted deadline expired")
            )
        effective_call = call.model_copy(update={"timeout_s": Decimal(str(effective_timeout))})
        identity = MCPCallIdentity(
            server=call.server,
            tool_name=call.tool_name,
            context=call.context,
            args_hash=call.args_hash,
        )
        async with self._lock:
            prior = self._dedup.get(call.context.operation_id)
            if prior is not None:
                if prior[0] != identity:
                    raise MCPGatewayError(
                        self._failure(
                            ToolFailureCode.OPERATION_CONFLICT,
                            call,
                            "operation identity was reused with different call identity",
                        )
                    )
                return prior[1]
            inflight = self._inflight.get(call.context.operation_id)
            if inflight is not None:
                if inflight[0] != identity:
                    raise MCPGatewayError(
                        self._failure(
                            ToolFailureCode.OPERATION_CONFLICT,
                            call,
                            "operation identity was reused with different call identity",
                        )
                    )
                pending = inflight[1]
            else:
                pending = asyncio.ensure_future(
                    asyncio.wait_for(
                        self._provider.invoke(effective_call), timeout=effective_timeout
                    )
                )
                self._inflight[call.context.operation_id] = (identity, pending)
        owner = inflight is None
        try:
            result: ToolResult = await asyncio.shield(pending)
        except asyncio.CancelledError:
            if owner:
                pending.cancel()
                await self._cancel(call.context.operation_id)
            raise MCPGatewayError(
                self._failure(ToolFailureCode.TOOL_CANCELLED, call, "tool call cancelled")
            ) from None
        except TimeoutError:
            await self._cancel(call.context.operation_id)
            raise MCPGatewayError(
                self._failure(ToolFailureCode.TOOL_TIMEOUT, call, "tool call timed out")
            ) from None
        except MCPGatewayError:
            raise
        except MCPFailureError as exc:
            raise MCPGatewayError(exc.failure) from exc
        finally:
            if owner:
                async with self._lock:
                    self._inflight.pop(call.context.operation_id, None)
        if (
            result.operation_id != call.context.operation_id
            or result.correlation_id != call.context.correlation_id
            or result.server != call.server
            or result.tool_name != call.tool_name
            or result.trust_class is not ToolTrustClass.TOOL_UNTRUSTED
            or result.source_uri != call.server.endpoint
            or len(result.content) != 1
            or result.content[0].kind is not ToolContentKind.JSON
            or not self._fixture_result_valid(result.content[0].value)
        ):
            raise MCPGatewayError(
                self._failure(
                    ToolFailureCode.RESULT_INVALID, call, "upstream result identity failed"
                )
            )
        async with self._lock:
            if len(self._dedup) >= self._max_dedup_entries:
                self._dedup.pop(next(iter(self._dedup)))
            self._dedup[call.context.operation_id] = (identity, result)
        return result

    async def cancel(self, token: str, context: MCPCallContext) -> None:
        principal = await self._verify(token, context)
        await self._authorize(context, principal)
        await self._cancel(context.operation_id)

    async def _authorize(self, context: MCPCallContext, principal: WorkloadPrincipal) -> None:
        try:
            await self._context_authority.validate(context, principal)
        except MCPContextAuthorizationError as exc:
            raise MCPGatewayError(
                MCPFailure(
                    code=MCPFailureCode.INVALID_CONTEXT,
                    retryable=False,
                    operation_id=context.operation_id,
                    correlation_id=context.correlation_id,
                )
            ) from exc

    async def _cancel(self, operation_id: UUID) -> None:
        try:
            await self._provider.cancel(operation_id)
        except Exception:
            _LOG.warning(
                "upstream cancel failed",
                extra={"operation_id": str(operation_id)},
                exc_info=True,
            )

    async def _verify(self, token: str, context: MCPCallContext) -> WorkloadPrincipal:
        if not token:
            raise MCPGatewayError(
                ToolFailure(
                    code=ToolFailureCode.AUTH_REQUIRED,
                    detail="workload authentication required",
                    retryable=False,
                    operation_id=context.operation_id,
                    correlation_id=context.correlation_id,
                )
            )
        try:
            principal = await self._token_verifier.verify(token)
        except InvalidWorkloadTokenError as exc:
            raise MCPGatewayError(
                ToolFailure(
                    code=ToolFailureCode.AUTH_REQUIRED,
                    detail="workload authentication failed",
                    retryable=False,
                    operation_id=context.operation_id,
                    correlation_id=context.correlation_id,
                )
            ) from exc
        if (
            principal.audience != "mcp-gateway"
            or principal.subject != context.workload_subject
            or principal.subject != self._allowed_subject
        ):
            raise MCPGatewayError(
                ToolFailure(
                    code=ToolFailureCode.FORBIDDEN,
                    detail="workload identity is not authorized",
                    retryable=False,
                    operation_id=context.operation_id,
                    correlation_id=context.correlation_id,
                )
            )
        if principal.expires_at <= int(datetime.now(UTC).timestamp()):
            raise MCPGatewayError(
                ToolFailure(
                    code=ToolFailureCode.AUTH_REQUIRED,
                    detail="workload token expired",
                    retryable=False,
                    operation_id=context.operation_id,
                    correlation_id=context.correlation_id,
                )
            )
        return principal

    @staticmethod
    def _fixture_manifest_valid(tools: tuple[ToolDescriptor, ...]) -> bool:
        if len(tools) != 1 or tools[0].name != "fixture.read_echo":
            return False
        descriptor = tools[0]
        return descriptor.input_schema == {
            "type": "object",
            "properties": {
                "value": {"type": "string", "maxLength": 128},
                "delay_ms": {"type": "integer", "minimum": 0, "maximum": 30000},
                "fail": {"type": "boolean"},
            },
            "required": ["value"],
            "additionalProperties": False,
        }

    @staticmethod
    def _fixture_result_valid(value: object) -> bool:
        return (
            isinstance(value, dict)
            and value.get("fixture") is True
            and isinstance(value.get("value"), str)
        )

    @staticmethod
    def _fixture_arguments_valid(arguments: dict[str, object]) -> bool:
        if "value" not in arguments or not set(arguments) <= {"value", "delay_ms", "fail"}:
            return False
        value = arguments["value"]
        delay_ms = arguments.get("delay_ms", 0)
        fail = arguments.get("fail", False)
        return (
            isinstance(value, str)
            and len(value) <= 128
            and type(delay_ms) is int
            and 0 <= delay_ms <= 30_000
            and isinstance(fail, bool)
        )

    @staticmethod
    def _failure(code: ToolFailureCode, call: ToolCall, detail: str) -> ToolFailure:
        return ToolFailure(
            code=code,
            detail=detail,
            retryable=code in {ToolFailureCode.TOOL_TIMEOUT, ToolFailureCode.UPSTREAM_UNAVAILABLE},
            operation_id=call.context.operation_id,
            correlation_id=call.context.correlation_id,
        )
