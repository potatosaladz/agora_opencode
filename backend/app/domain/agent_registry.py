"""Agent registry domain types — `docs/AGENT_MODEL.md`, `docs/DATA_MODEL.md` §4.

These are pure value objects. They carry no SQLAlchemy, no FastAPI, and no
infrastructure imports. The `app/db/models/agents.py` layer maps them to rows;
the `app/application/` layer orchestrates them.

`AgentDefinition` is immutable once `referenced_at` is set (FR-202). The
immutability is enforced by a database trigger, not by this Python object, but
the domain type makes the intent explicit so that application code never
attempts to mutate a frozen definition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from app.ports.storage import SecretRef

__all__ = [
    "AgentDefinition",
    "AgentRegistry",
    "AgentRoleKind",
    "AgentStatus",
    "CredentialEnvelope",
    "LLMCallRecord",
    "LLMConfiguration",
    "ProviderKind",
]


class AgentRoleKind(StrEnum):
    """The five canonical agent roles. `docs/AGENT_MODEL.md` §2."""

    DOMAIN_EXPERT = "domain_expert"
    CRITIC = "critic"
    ORCHESTRATOR = "orchestrator"
    RETRIEVER = "retriever"
    EVALUATOR = "evaluator"


class AgentStatus(StrEnum):
    """Lifecycle states for an agent definition version."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    WITHDRAWN = "WITHDRAWN"


class ProviderKind(StrEnum):
    """The two provider kinds supported in Phase 2."""

    OPENAI_COMPATIBLE = "openai_compatible"
    MOCK = "mock"


@dataclass(frozen=True, slots=True)
class CredentialEnvelope:
    """Encrypted credential material safe for durable storage."""

    ciphertext: bytes
    credential_nonce: bytes
    wrapped_data_key: bytes
    wrapping_nonce: bytes
    master_key_ref: SecretRef
    algorithm: str = "AES-256-GCM"


@dataclass(frozen=True, slots=True)
class LLMConfiguration:
    """A workspace's LLM endpoint configuration.

    `secret_ref` is the only credential handle that crosses a port boundary
    (PORTS.md §0). The plaintext API key never appears in this object.
    """

    id: UUID
    workspace_id: UUID
    name: str
    provider_kind: ProviderKind
    base_url: str
    model: str
    embedding_model: str | None = None
    api_version: str | None = None
    secret_ref: SecretRef = field(default_factory=lambda: SecretRef(provider="none", name="none"))
    capabilities: dict[str, Any] = field(default_factory=dict)
    rate_limit: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """One version of one agent. `docs/DATA_MODEL.md` §4.

    `logical_id` groups versions; `version` is the ordinal within that group.
    Once `referenced_at` is set the row is frozen (FR-202) — the database
    trigger rejects any UPDATE except to `status` and `updated_at`.
    """

    id: UUID
    workspace_id: UUID
    logical_id: UUID
    version: int
    name: str
    domain: str
    role_kind: AgentRoleKind
    objectives: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    knowledge_ns: tuple[UUID, ...] = ()
    strategy_ref: str = ""
    strategy_ver: str = ""
    prompt_ref: str = ""
    prompt_hash: str = ""
    llm_config_id: UUID | None = None
    tool_perms: tuple[str, ...] = ()
    budget: dict[str, Any] = field(default_factory=dict)
    status: AgentStatus = AgentStatus.DRAFT
    superseded_by: UUID | None = None
    referenced_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class LLMCallRecord:
    """One completed LLM call with its cost. `docs/DATA_MODEL.md` §5.

    `raw_artifact_ref` is the ObjectStore key of the exact request/response bytes
    (secret-redacted). It is mandatory: a call without a raw artifact cannot be
    re-inspected and therefore cannot satisfy the reproducibility requirement.
    """

    id: UUID
    workspace_id: UUID
    session_id: UUID | None
    agent_def_id: UUID | None
    llm_config_id: UUID | None
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    latency_ms: int
    finish_reason: str
    retry_attempts: int
    raw_artifact_ref: str
    correlation_id: str
    created_at: datetime | None = None


@runtime_checkable
class AgentRegistry(Protocol):
    """Tenant-scoped durable registry boundary for application services."""

    async def add_configuration(self, configuration: LLMConfiguration) -> None: ...

    async def get_configuration(self, configuration_id: UUID) -> LLMConfiguration | None: ...

    async def put_credential_envelope(
        self, configuration_id: UUID, workspace_id: UUID, envelope: CredentialEnvelope
    ) -> None: ...

    async def get_credential_envelope(
        self, configuration_id: UUID
    ) -> CredentialEnvelope | None: ...

    async def add_definition(self, definition: AgentDefinition) -> None: ...

    async def add_definition_version(
        self, previous_id: UUID, definition: AgentDefinition
    ) -> None: ...

    async def get_definition(self, definition_id: UUID) -> AgentDefinition | None: ...

    async def add_call_record(self, record: LLMCallRecord) -> None: ...

    async def list_call_records(self) -> tuple[LLMCallRecord, ...]: ...
