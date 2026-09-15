"""Infrastructure-neutral MCP gateway provider and workload identity ports."""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "InvalidWorkloadTokenError",
    "MCPToolProvider",
    "WorkloadPrincipal",
    "WorkloadTokenVerifier",
]


class InvalidWorkloadTokenError(ValueError):
    pass


ServerT = TypeVar("ServerT", contravariant=True)
CapabilitiesT = TypeVar("CapabilitiesT", covariant=True)
DescriptorT = TypeVar("DescriptorT", covariant=True)
CallT = TypeVar("CallT", contravariant=True)
ResultT = TypeVar("ResultT", covariant=True)


class WorkloadPrincipal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    subject: str
    audience: str
    service_role: str
    expires_at: int = Field(gt=0)

    @field_validator("subject", "audience", "service_role")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("workload principal fields must not be blank")
        return value


@runtime_checkable
class WorkloadTokenVerifier(Protocol):
    async def verify(self, token: str) -> WorkloadPrincipal: ...


@runtime_checkable
# trace: FR-1001, NFR-012, NFR-015, NFR-016, NFR-020
class MCPToolProvider(Protocol[ServerT, CapabilitiesT, DescriptorT, CallT, ResultT]):
    async def initialize(self, server: ServerT) -> CapabilitiesT: ...

    async def list_tools(self, server: ServerT) -> tuple[DescriptorT, ...]: ...

    async def invoke(self, call: CallT) -> ResultT: ...

    async def cancel(self, operation_id: UUID) -> None: ...
