"""Focused T15-01 contracts, authentication, gateway, and no-write tests."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx
import jwt
import pytest
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError
from pydantic import ValidationError

from app.adapters.auth_workload import JWTWorkloadTokenIssuer, JWTWorkloadTokenVerifier
from app.adapters.mcp.fixture import create_fixture_app
from app.adapters.mcp.gateway_client import (
    MCPGatewayCallError,
    _authorization_headers,
    _raise_failure,
)
from app.adapters.mcp.gateway_server import (
    _failure_result,
    _internal_error,
    _map_tool_failure,
    create_gateway_app,
)
from app.application.mcp_gateway import (
    MCPContextAuthorizationError,
    MCPGateway,
    MCPGatewayError,
)
from app.domain.mcp import (
    MCPCallContext,
    MCPFailure,
    MCPFailureCode,
    MCPProtocolVersion,
    MCPServerCapabilities,
    ToolCall,
    ToolClass,
    ToolContent,
    ToolContentKind,
    ToolDescriptor,
    ToolFailure,
    ToolFailureCode,
    ToolPermission,
    ToolResult,
    ToolTrustClass,
    UpstreamServerRef,
    content_hash,
    tool_args_hash,
)
from app.ports.mcp import InvalidWorkloadTokenError, WorkloadPrincipal
from tests.traceability import req

_SERVER = UpstreamServerRef(
    server_id="fixture",
    version=1,
    endpoint="http://fixture/mcp",
    manifest_hash="sha256:" + "0" * 64,
)
_CONTEXT = MCPCallContext(
    workload_subject="reasoning-worker",
    workspace_id=UUID("018f0000-0000-7000-8000-000000000001"),
    session_id=UUID("018f0000-0000-7000-8000-000000000002"),
    agent_definition_id=UUID("018f0000-0000-7000-8000-000000000003"),
    agent_definition_version=1,
    operation_id=UUID("018f0000-0000-7000-8000-000000000004"),
    correlation_id=UUID("018f0000-0000-7000-8000-000000000005"),
    round=1,
    deadline_at=datetime.now(UTC) + timedelta(seconds=30),
)
_PRINCIPAL = WorkloadPrincipal(
    subject="reasoning-worker",
    audience="mcp-gateway",
    service_role="reasoning-worker",
    expires_at=int(datetime.now(UTC).timestamp()) + 60,
)


def _descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        server=_SERVER,
        name="fixture.read_echo",
        description="Return deterministic fixture data.",
        input_schema={
            "type": "object",
            "properties": {
                "value": {"type": "string", "maxLength": 128},
                "delay_ms": {"type": "integer", "minimum": 0, "maximum": 30000},
                "fail": {"type": "boolean"},
            },
            "required": ["value"],
            "additionalProperties": False,
        },
        tool_class=ToolClass.READ_SANE,
        permission=ToolPermission.READ,
        manifest_hash=_SERVER.manifest_hash,
    )


def _call(*, value: str = "hello", operation_id: UUID = _CONTEXT.operation_id) -> ToolCall:
    context = _CONTEXT.model_copy(update={"operation_id": operation_id})
    arguments = {"value": value}
    return ToolCall(
        context=context,
        server=_SERVER,
        tool_name="fixture.read_echo",
        arguments=arguments,
        args_hash=tool_args_hash(arguments),
        timeout_s=Decimal("1"),
    )


def _result(call: ToolCall) -> ToolResult:
    content = (ToolContent(kind=ToolContentKind.JSON, value={"value": "hello", "fixture": True}),)
    content_hash_value = content_hash([item.model_dump(mode="json") for item in content])
    return ToolResult(
        operation_id=call.context.operation_id,
        correlation_id=call.context.correlation_id,
        server=call.server,
        tool_name=call.tool_name,
        content=content,
        content_hash=content_hash_value,
        source_uri=call.server.endpoint,
        retrieved_at=datetime.now(UTC),
        trust_class=ToolTrustClass.TOOL_UNTRUSTED,
        original_bytes=1,
        returned_bytes=1,
    )


class FakeProvider:
    def __init__(self, result: ToolResult | None = None, *, delay_s: float = 0) -> None:
        self.result = result
        self.delay_s = delay_s
        self.calls: list[ToolCall] = []
        self.cancelled: list[UUID] = []

    async def initialize(self, server: UpstreamServerRef) -> MCPServerCapabilities:
        return MCPServerCapabilities(protocol_version=MCPProtocolVersion.V2025_06_18)

    async def list_tools(self, server: UpstreamServerRef) -> tuple[ToolDescriptor, ...]:
        return (_descriptor(),)

    async def invoke(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        return self.result or _result(call)

    async def cancel(self, operation_id: UUID) -> None:
        self.cancelled.append(operation_id)


class FakeVerifier:
    async def verify(self, token: str) -> WorkloadPrincipal:
        if token != "valid":
            raise InvalidWorkloadTokenError("invalid")
        return _PRINCIPAL


class FakeAuthority:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.contexts: list[MCPCallContext] = []

    async def validate(self, context: MCPCallContext, principal: WorkloadPrincipal) -> None:
        self.contexts.append(context)
        if self.fail:
            raise MCPContextAuthorizationError("denied")


class BrokenAuthority:
    async def validate(self, context: MCPCallContext, principal: WorkloadPrincipal) -> None:
        raise RuntimeError("membership store unavailable")


def _gateway(provider: FakeProvider, authority: FakeAuthority | None = None) -> MCPGateway:
    return MCPGateway(provider, FakeVerifier(), authority or FakeAuthority(), _SERVER)


@req("NFR-015")
def test_mcp_contracts_require_canonical_hashes_and_closed_arguments() -> None:
    call = _call()
    assert call.args_hash == tool_args_hash(call.arguments)
    with pytest.raises(ValidationError):
        ToolCall.model_validate({**call.model_dump(), "arguments": {"workspace_id": "bad"}})
    invalid_descriptor = _descriptor().model_dump()
    invalid_descriptor["permission"] = ToolPermission.APPROVAL_REQUIRED
    with pytest.raises(ValidationError):
        ToolDescriptor.model_validate(invalid_descriptor)


@req("NFR-015")
def test_tool_result_is_untrusted_and_hash_validated() -> None:
    call = _call()
    content = (ToolContent(kind=ToolContentKind.TEXT, value="untrusted"),)

    result = ToolResult(
        operation_id=call.context.operation_id,
        correlation_id=call.context.correlation_id,
        server=_SERVER,
        tool_name=call.tool_name,
        content=content,
        content_hash=content_hash([item.model_dump(mode="json") for item in content]),
        retrieved_at=datetime.now(UTC),
        trust_class=ToolTrustClass.TOOL_UNTRUSTED,
        original_bytes=10,
        returned_bytes=10,
    )
    assert result.content[0].untrusted is True
    invalid = result.model_dump()
    invalid["content_hash"] = "sha256:" + "f" * 64
    with pytest.raises(ValidationError):
        ToolResult.model_validate(invalid)


@req("NFR-015")
@pytest.mark.asyncio
async def test_gateway_initializes_and_delegates_typed_fixture_call() -> None:
    provider = FakeProvider()
    gateway = _gateway(provider)
    capabilities = await gateway.initialize()
    assert isinstance(capabilities, MCPServerCapabilities)
    assert capabilities.protocol_version is MCPProtocolVersion.V2025_06_18
    assert (await gateway.list_tools("valid", _CONTEXT))[0].name == "fixture.read_echo"
    result = await gateway.invoke("valid", _call())
    assert result.trust_class is ToolTrustClass.TOOL_UNTRUSTED
    assert provider.calls[0].context.correlation_id == _CONTEXT.correlation_id


@req("NFR-015")
@pytest.mark.asyncio
async def test_gateway_rejects_auth_context_and_operation_conflicts() -> None:
    gateway = _gateway(FakeProvider())
    with pytest.raises(MCPGatewayError) as missing:
        await gateway.invoke("", _call())
    assert missing.value.failure.code is ToolFailureCode.AUTH_REQUIRED
    await gateway.invoke("valid", _call(value="one"))
    with pytest.raises(MCPGatewayError) as conflict:
        await gateway.invoke("valid", _call(value="two"))
    assert conflict.value.failure.code is ToolFailureCode.OPERATION_CONFLICT


@req("NFR-015")
@pytest.mark.asyncio
async def test_gateway_preserves_unexpected_context_defects() -> None:
    gateway = MCPGateway(FakeProvider(), FakeVerifier(), BrokenAuthority(), _SERVER)
    with pytest.raises(RuntimeError, match="membership store unavailable"):
        await gateway.invoke("valid", _call())


@req("NFR-015")
@pytest.mark.asyncio
async def test_gateway_maps_expected_context_denial() -> None:
    gateway = _gateway(FakeProvider(), FakeAuthority(fail=True))
    with pytest.raises(MCPGatewayError) as error:
        await gateway.invoke("valid", _call())
    assert error.value.failure.code is MCPFailureCode.INVALID_CONTEXT


@req("NFR-015")
def test_malformed_failure_metadata_is_rejected_without_raw_detail() -> None:
    with pytest.raises(MCPGatewayCallError) as error:
        _raise_failure({"failure": {"code": "NOT_A_REAL_CODE"}})
    assert error.value.failure.code is MCPFailureCode.RESULT_INVALID
    assert "NOT_A_REAL_CODE" not in str(error.value)


@req("NFR-015")
@pytest.mark.asyncio
async def test_gateway_preserves_unexpected_verifier_defects() -> None:
    class BrokenVerifier:
        async def verify(self, token: str) -> WorkloadPrincipal:
            raise RuntimeError("identity service unavailable")

    gateway = MCPGateway(FakeProvider(), BrokenVerifier(), FakeAuthority(), _SERVER)
    with pytest.raises(RuntimeError, match="identity service unavailable"):
        await gateway.invoke("valid", _call())


@req("NFR-015")
def test_gateway_rejects_round_zero_context() -> None:
    values = _CONTEXT.model_dump()
    values["round"] = 0
    with pytest.raises(ValidationError):
        MCPCallContext.model_validate(values)


@req("NFR-016")
@pytest.mark.asyncio
async def test_gateway_timeout_cancels_upstream() -> None:
    provider = FakeProvider(delay_s=0.2)
    gateway = _gateway(provider)
    call = _call()
    with pytest.raises(MCPGatewayError) as error:
        await gateway.invoke("valid", call.model_copy(update={"timeout_s": Decimal("0.01")}))
    assert error.value.failure.code is ToolFailureCode.TOOL_TIMEOUT
    assert provider.cancelled == [call.context.operation_id]


@req("NFR-016")
@pytest.mark.asyncio
async def test_gateway_cancellation_is_typed_and_cleanup_failure_is_not_success() -> None:
    class CleanupFailureProvider(FakeProvider):
        async def cancel(self, operation_id: UUID) -> None:
            raise RuntimeError("cleanup defect")

    provider = CleanupFailureProvider(delay_s=1)
    gateway = _gateway(provider)
    task = asyncio.create_task(gateway.invoke("valid", _call()))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(MCPGatewayError) as error:
        await task
    assert error.value.failure.code is ToolFailureCode.TOOL_CANCELLED
    assert provider.cancelled == []


@req("NFR-016")
@pytest.mark.asyncio
async def test_gateway_timeout_remains_distinct_from_cancellation_when_cleanup_fails() -> None:
    class CleanupFailureProvider(FakeProvider):
        async def cancel(self, operation_id: UUID) -> None:
            raise RuntimeError("cleanup defect")

    provider = CleanupFailureProvider(delay_s=1)
    gateway = _gateway(provider)
    with pytest.raises(MCPGatewayError) as error:
        await gateway.invoke("valid", _call().model_copy(update={"timeout_s": Decimal("0.01")}))
    assert error.value.failure.code is ToolFailureCode.TOOL_TIMEOUT
    assert provider.cancelled == []


@req("NFR-015")
def test_workload_jwt_requires_issuer_audience_subject_and_expiry() -> None:
    secret = "t15-01-deterministic-test-key-32-bytes"
    issuer = JWTWorkloadTokenIssuer(secret=secret, issuer="https://identity.test")
    verifier = JWTWorkloadTokenVerifier(secret=secret, issuer="https://identity.test")
    token = issuer.issue()
    assert asyncio.run(verifier.verify(token)).subject == "reasoning-worker"
    wrong_audience = jwt.encode(
        {
            "iss": "https://identity.test",
            "aud": "other",
            "sub": "reasoning-worker",
            "exp": 9_999_999_999,
        },
        secret,
        algorithm="HS256",
    )
    with pytest.raises(InvalidWorkloadTokenError, match="invalid workload token"):
        asyncio.run(verifier.verify(wrong_audience))


@req("NFR-016")
@pytest.mark.asyncio
async def test_gateway_rejects_expired_trusted_deadline_before_provider() -> None:
    provider = FakeProvider()
    gateway = _gateway(provider)
    expired = _CONTEXT.model_copy(update={"deadline_at": datetime.now(UTC) - timedelta(seconds=1)})
    call = _call()
    call = call.model_copy(update={"context": expired})
    with pytest.raises(MCPGatewayError) as error:
        await gateway.invoke("valid", call)
    assert error.value.failure.code is ToolFailureCode.TOOL_TIMEOUT
    assert provider.calls == []


@req("NFR-016")
@pytest.mark.asyncio
async def test_gateway_uses_shorter_trusted_deadline() -> None:
    provider = FakeProvider(delay_s=0.1)
    gateway = _gateway(provider)
    context = _CONTEXT.model_copy(
        update={"deadline_at": datetime.now(UTC) + timedelta(seconds=0.01)}
    )
    call = _call().model_copy(update={"context": context, "timeout_s": Decimal("1")})
    with pytest.raises(MCPGatewayError) as error:
        await gateway.invoke("valid", call)
    assert error.value.failure.code is ToolFailureCode.TOOL_TIMEOUT


@req("NFR-015")
def test_gateway_client_omits_empty_bearer_header() -> None:
    assert _authorization_headers("") == {}
    assert _authorization_headers("token") == {"Authorization": "Bearer token"}


@req("NFR-015")
def test_worker_failure_envelope_is_typed_and_does_not_expose_detail() -> None:
    failure = MCPFailure(
        code=MCPFailureCode.AUTHENTICATION_FAILED,
        retryable=False,
        operation_id=_CONTEXT.operation_id,
        correlation_id=_CONTEXT.correlation_id,
    )
    with pytest.raises(MCPGatewayCallError) as error:
        _raise_failure({"failure": failure.model_dump(mode="json")})
    assert error.value.failure.code is MCPFailureCode.AUTHENTICATION_FAILED
    assert "secret" not in str(error.value).lower()


@req("NFR-012")
def test_domain_has_no_mcp_sdk_imports() -> None:
    from tests.test_layering import find_sdk_violations

    assert find_sdk_violations(Path(__file__).parents[2] / "app") == []


@req("NFR-012")
def test_mcp_gateway_has_no_artifact_or_ledger_writer_dependency() -> None:
    root = Path(__file__).parents[2] / "app"
    for relative in (
        Path("application/mcp_gateway.py"),
        Path("adapters/mcp/gateway_server.py"),
        Path("adapters/mcp/streamable_http.py"),
        Path("adapters/temporal/mcp_activity.py"),
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "app.ports.reasoning" not in text
        assert "app.domain.reasoning_ledger" not in text
        assert "ArtifactCommitService" not in text
        assert ".commit(" not in text


@req("NFR-015")
def test_closed_failure_taxonomy_maps_to_sanitized_meta() -> None:
    expected = {
        ToolFailureCode.AUTH_REQUIRED: MCPFailureCode.AUTHENTICATION_FAILED,
        ToolFailureCode.FORBIDDEN: MCPFailureCode.AUTHORIZATION_DENIED,
        ToolFailureCode.ARGUMENT_INVALID: MCPFailureCode.INVALID_ARGUMENTS,
        ToolFailureCode.TOOL_NOT_FOUND: MCPFailureCode.TOOL_NOT_FOUND,
        ToolFailureCode.PROTOCOL_ERROR: MCPFailureCode.UPSTREAM_PROTOCOL_ERROR,
        ToolFailureCode.UPSTREAM_UNAVAILABLE: MCPFailureCode.UPSTREAM_UNAVAILABLE,
        ToolFailureCode.TOOL_TIMEOUT: MCPFailureCode.TIMEOUT,
        ToolFailureCode.TOOL_CANCELLED: MCPFailureCode.CANCELLED,
        ToolFailureCode.RESULT_INVALID: MCPFailureCode.RESULT_INVALID,
    }
    for tool_code, gateway_code in expected.items():
        mapped = _map_tool_failure(
            ToolFailure(
                code=tool_code,
                detail="hostile upstream body token=secret traceback RuntimeError",
                retryable=False,
                operation_id=_CONTEXT.operation_id,
                correlation_id=_CONTEXT.correlation_id,
            )
        )
        result = _failure_result(mapped)
        serialized = json.dumps(result.model_dump(mode="json"))
        assert mapped.code is gateway_code
        assert result.isError is True
        assert result.content == []
        assert "failure" in (result.meta or {})
        assert "secret" not in serialized
        assert "traceback" not in serialized
        assert "RuntimeError" not in serialized


@req("NFR-015")
def test_unexpected_programming_defect_uses_internal_protocol_error() -> None:
    error = _internal_error()
    assert isinstance(error, McpError)
    assert error.error.code == types.INTERNAL_ERROR
    assert error.error.message == "Internal server error"


@req("NFR-015")
@pytest.mark.asyncio
async def test_gateway_rejects_invalid_and_context_override_arguments_before_upstream() -> None:
    provider = FakeProvider()
    gateway = _gateway(provider)
    for arguments in (
        {},
        {"value": "ok", "unknown": True},
        {"value": "ok", "workspace_id": str(_CONTEXT.workspace_id)},
        {"value": "ok", "delay_ms": 30_001},
    ):
        call = _call().model_copy(
            update={"arguments": arguments, "args_hash": tool_args_hash(arguments)}
        )
        with pytest.raises(MCPGatewayError) as error:
            await gateway.invoke("valid", call)
        assert error.value.failure.code is ToolFailureCode.ARGUMENT_INVALID
    assert provider.calls == []


@req("NFR-015")
@pytest.mark.asyncio
async def test_gateway_unexpected_provider_defect_is_not_an_expected_failure() -> None:
    class BrokenProvider(FakeProvider):
        async def invoke(self, call: ToolCall) -> ToolResult:
            raise RuntimeError("secret programming defect")

    with pytest.raises(RuntimeError, match="secret programming defect"):
        await _gateway(BrokenProvider()).invoke("valid", _call())


@req("NFR-015")
@pytest.mark.asyncio
async def test_official_sdk_fixture_initializes_lists_calls_and_reports_errors() -> None:
    app = create_fixture_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://fixture") as client,
            streamable_http_client("http://fixture/mcp", http_client=client) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            initialized = await session.send_request(
                types.ClientRequest(
                    types.InitializeRequest(
                        params=types.InitializeRequestParams(
                            protocolVersion=MCPProtocolVersion.V2025_06_18.value,
                            capabilities=types.ClientCapabilities(),
                            clientInfo=types.Implementation(name="test", version="1"),
                        )
                    )
                ),
                types.InitializeResult,
            )
            await session.send_notification(
                types.ClientNotification(types.InitializedNotification())
            )
            tools = await session.list_tools()
            result = await session.call_tool("fixture.read_echo", {"value": "hello"})
            failed = await session.call_tool("fixture.read_echo", {"value": "hello", "fail": True})
    assert initialized.protocolVersion == MCPProtocolVersion.V2025_06_18.value
    assert [tool.name for tool in tools.tools] == ["fixture.read_echo"]
    assert result.structuredContent == {"value": "hello", "fixture": True}
    assert failed.isError is True
    assert failed.content[0].text == "fixture upstream failure"


@req("NFR-015")
@pytest.mark.asyncio
async def test_gateway_server_returns_expected_failure_in_meta() -> None:
    gateway = _gateway(FakeProvider())
    app = create_gateway_app(gateway, _SERVER)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://gateway") as client,
            streamable_http_client("http://gateway/mcp", http_client=client) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            initialized = await session.send_request(
                types.ClientRequest(
                    types.InitializeRequest(
                        params=types.InitializeRequestParams(
                            protocolVersion=MCPProtocolVersion.V2025_06_18.value,
                            capabilities=types.ClientCapabilities(),
                            clientInfo=types.Implementation(name="test", version="1"),
                        )
                    )
                ),
                types.InitializeResult,
            )
            await session.send_notification(
                types.ClientNotification(types.InitializedNotification())
            )
            failure = await session.list_tools(
                params=types.PaginatedRequestParams(_meta=_CONTEXT.model_dump(mode="json"))
            )
    assert initialized.protocolVersion == MCPProtocolVersion.V2025_06_18.value
    assert failure.tools == []
    assert failure.meta == {
        "failure": {
            "code": MCPFailureCode.AUTHENTICATION_FAILED.value,
            "retryable": False,
            "operation_id": str(_CONTEXT.operation_id),
            "correlation_id": str(_CONTEXT.correlation_id),
        }
    }
