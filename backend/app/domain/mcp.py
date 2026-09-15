"""Frozen Phase 15 T15-01 MCP gateway value contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.domain.reasoning import ActorClass, FrozenModel, canonical_json, content_hash
from app.ports.storage import ObjectRef

__all__ = [
    "MCPCallContext",
    "MCPFailure",
    "MCPFailureCode",
    "MCPFailureError",
    "MCPProtocolVersion",
    "MCPServerCapabilities",
    "ToolCall",
    "ToolClass",
    "ToolContent",
    "ToolContentKind",
    "ToolDescriptor",
    "ToolFailure",
    "ToolFailureCode",
    "ToolPermission",
    "ToolResult",
    "ToolTrustClass",
    "UpstreamServerRef",
    "content_hash",
    "tool_args_hash",
]

_SHA256 = r"^sha256:[0-9a-f]{64}$"
_TOOL_NAME = r"^[a-z][a-z0-9_-]{0,62}\.[a-z][a-z0-9_-]{0,62}$"
_MAX_ARGUMENT_BYTES = 64 * 1024
_MAX_RESULT_BYTES = 256 * 1024
_MAX_JSON_DEPTH = 8
_MAX_JSON_MEMBERS = 256


class MCPProtocolVersion(StrEnum):
    V2025_06_18 = "2025-06-18"


class ToolClass(StrEnum):
    READ_SANE = "READ_SANE"
    READ_RISKY = "READ_RISKY"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"
    EXTERNAL_NET = "EXTERNAL_NET"


class ToolPermission(StrEnum):
    NONE = "NONE"
    READ = "READ"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


class ToolContentKind(StrEnum):
    TEXT = "TEXT"
    JSON = "JSON"
    BLOB_REF = "BLOB_REF"


class ToolTrustClass(StrEnum):
    TOOL_UNTRUSTED = "TOOL_UNTRUSTED"
    SYNTHETIC = "SYNTHETIC"


class MCPFailureCode(StrEnum):
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    INVALID_CONTEXT = "INVALID_CONTEXT"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    UPSTREAM_PROTOCOL_ERROR = "UPSTREAM_PROTOCOL_ERROR"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    RESULT_INVALID = "RESULT_INVALID"


class ToolFailureCode(StrEnum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    FORBIDDEN = "FORBIDDEN"
    SERVER_NOT_REGISTERED = "SERVER_NOT_REGISTERED"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    MANIFEST_DRIFT = "MANIFEST_DRIFT"
    ARGUMENT_INVALID = "ARGUMENT_INVALID"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_CANCELLED = "TOOL_CANCELLED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    RESULT_INVALID = "RESULT_INVALID"
    RESULT_TOO_LARGE = "RESULT_TOO_LARGE"
    INJECTION_SUSPECTED = "INJECTION_SUSPECTED"
    OPERATION_CONFLICT = "OPERATION_CONFLICT"


def _bounded_json(value: dict[str, Any], *, label: str) -> dict[str, Any]:
    encoded = canonical_json(value)
    if len(encoded) > _MAX_ARGUMENT_BYTES:
        raise ValueError(f"{label} exceeds the byte limit")

    def walk(item: Any, depth: int = 0) -> int:
        if depth > _MAX_JSON_DEPTH:
            raise ValueError(f"{label} exceeds the depth limit")
        if isinstance(item, dict):
            if len(item) > _MAX_JSON_MEMBERS:
                raise ValueError(f"{label} exceeds the member limit")
            return sum(walk(key, depth + 1) + walk(child, depth + 1) for key, child in item.items())
        if isinstance(item, list | tuple):
            return sum(walk(child, depth + 1) for child in item)
        return 1

    walk(value)
    return value


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an RFC 3339 offset")
    return value.astimezone(UTC)


class UpstreamServerRef(FrozenModel):
    server_id: str
    version: int = Field(gt=0)
    transport: Literal["STREAMABLE_HTTP"] = "STREAMABLE_HTTP"
    endpoint: str
    manifest_hash: str = Field(pattern=_SHA256)

    _server = field_validator("server_id")(_not_blank)

    @field_validator("endpoint")
    @classmethod
    def streamable_http_endpoint(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("MCP endpoint must use HTTP")
        return value


class MCPCallContext(FrozenModel):
    workload_subject: str
    workspace_id: UUID
    session_id: UUID
    agent_definition_id: UUID
    agent_definition_version: int = Field(gt=0)
    initiating_actor_class: ActorClass | None = None
    initiating_actor_id: UUID | None = None
    operation_id: UUID
    correlation_id: UUID
    round: int = Field(ge=1)
    deadline_at: datetime

    _subject = field_validator("workload_subject")(_not_blank)
    _deadline = field_validator("deadline_at")(_aware)

    @field_validator("operation_id", "correlation_id")
    @classmethod
    def uuidv7_identity(cls, value: UUID) -> UUID:
        if value.version != 7:
            raise ValueError("operation and correlation identities must be UUIDv7")
        return value

    @model_validator(mode="after")
    def actor_pair(self) -> MCPCallContext:
        if (self.initiating_actor_class is None) != (self.initiating_actor_id is None):
            raise ValueError("initiating actor class and id must be supplied together")
        return self


class MCPServerCapabilities(FrozenModel):
    protocol_version: MCPProtocolVersion
    tools: bool = True
    resources: Literal[False] = False
    prompts: Literal[False] = False
    cancellation: bool = False
    progress: bool = False


class ToolDescriptor(FrozenModel):
    server: UpstreamServerRef
    name: str = Field(pattern=_TOOL_NAME)
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    tool_class: ToolClass
    permission: ToolPermission
    manifest_hash: str = Field(pattern=_SHA256)

    _description = field_validator("description")(_not_blank)

    @field_validator("input_schema")
    @classmethod
    def bounded_input_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json(value, label="input schema")

    @field_validator("output_schema")
    @classmethod
    def bounded_output_schema(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if value is None else _bounded_json(value, label="output schema")

    @model_validator(mode="after")
    def fixture_policy_shape(self) -> ToolDescriptor:
        if self.input_schema.get("type") != "object":
            raise ValueError("tool input schema must describe an object")
        if self.input_schema.get("additionalProperties") is not False:
            raise ValueError("tool input schema must reject unknown fields")
        expected = {
            ToolClass.READ_SANE: ToolPermission.READ,
            ToolClass.READ_RISKY: ToolPermission.READ,
            ToolClass.WRITE: ToolPermission.APPROVAL_REQUIRED,
            ToolClass.EXECUTE: ToolPermission.NONE,
            ToolClass.EXTERNAL_NET: ToolPermission.NONE,
        }[self.tool_class]
        if self.permission is not expected:
            raise ValueError("tool permission does not match the frozen class mapping")
        canonical_json(self.input_schema)
        if self.output_schema is not None:
            canonical_json(self.output_schema)
        return self


def tool_args_hash(arguments: dict[str, Any]) -> str:
    return content_hash(arguments)


class ToolCall(FrozenModel):
    context: MCPCallContext
    server: UpstreamServerRef
    tool_name: str = Field(pattern=_TOOL_NAME)
    arguments: dict[str, Any]
    args_hash: str = Field(pattern=_SHA256)
    timeout_s: Decimal = Field(gt=0, le=30)
    approval_id: UUID | None = None

    @field_validator("arguments")
    @classmethod
    def bounded_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json(value, label="tool arguments")

    @model_validator(mode="after")
    def canonical_arguments(self) -> ToolCall:
        if self.args_hash != tool_args_hash(self.arguments):
            raise ValueError("args_hash does not match canonical arguments")
        return self


class ToolContent(FrozenModel):
    kind: ToolContentKind
    value: Any
    untrusted: Literal[True] = True

    @model_validator(mode="after")
    def kind_matches_value(self) -> ToolContent:
        if self.kind is ToolContentKind.TEXT and not isinstance(self.value, str):
            raise ValueError("TEXT tool content requires a string value")
        if self.kind is ToolContentKind.JSON:
            canonical_json(self.value)
        if self.kind is ToolContentKind.BLOB_REF and not isinstance(self.value, dict):
            raise ValueError("BLOB_REF tool content requires an object reference value")
        if len(canonical_json(self.value)) > _MAX_RESULT_BYTES:
            raise ValueError("tool content exceeds the byte limit")
        return self


class ToolResult(FrozenModel):
    operation_id: UUID
    correlation_id: UUID
    server: UpstreamServerRef
    tool_name: str = Field(pattern=_TOOL_NAME)
    content: tuple[ToolContent, ...]
    content_hash: str = Field(pattern=_SHA256)
    source_uri: str | None = None
    retrieved_at: datetime
    trust_class: ToolTrustClass
    raw_artifact_ref: ObjectRef | None = None
    truncated: bool = False
    original_bytes: int = Field(ge=0)
    returned_bytes: int = Field(ge=0)
    upstream_request_id: str | None = None

    _retrieved = field_validator("retrieved_at")(_aware)

    @model_validator(mode="after")
    def coherent_result(self) -> ToolResult:
        if not self.content:
            raise ValueError("tool result content must not be empty")
        if self.returned_bytes > self.original_bytes:
            raise ValueError("returned bytes cannot exceed original bytes")
        if self.truncated != (self.returned_bytes < self.original_bytes):
            raise ValueError("truncation flag must match result byte counts")
        content_value = [item.model_dump(mode="json") for item in self.content]
        if self.content_hash != content_hash(content_value):
            raise ValueError("content_hash does not match canonical tool content")
        return self


class MCPFailure(FrozenModel):
    code: MCPFailureCode
    retryable: bool
    operation_id: UUID | None = None
    correlation_id: UUID | None = None


class ToolFailure(FrozenModel):
    code: ToolFailureCode
    detail: str
    retryable: bool
    operation_id: UUID | None = None
    correlation_id: UUID | None = None

    _detail = field_validator("detail")(_not_blank)


class MCPFailureError(ValueError):
    def __init__(self, failure: MCPFailure | ToolFailure) -> None:
        super().__init__(failure.code.value)
        self.failure = failure
