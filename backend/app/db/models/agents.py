"""Tenant-owned LLM configuration, agent registry, and call-accounting rows."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = [
    "AgentDefinitionRow",
    "LLMCallRecordRow",
    "LLMConfigurationRow",
    "LLMCredentialEnvelopeRow",
]


class LLMConfigurationRow(Base):
    """Provider-neutral endpoint metadata; plaintext credentials never enter this row."""

    __tablename__ = "llm_configurations"
    __table_args__ = (
        CheckConstraint(
            "provider_kind IN ('openai_compatible', 'mock')",
            name="provider_kind",
        ),
        UniqueConstraint("id", "workspace_id", name="uq_llm_configurations_id_workspace"),
        UniqueConstraint("workspace_id", "name", name="uq_llm_configurations_workspace_name"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    provider_kind: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_model: Mapped[str | None] = mapped_column(Text)
    api_version: Mapped[str | None] = mapped_column(Text)
    secret_provider: Mapped[str] = mapped_column(Text, nullable=False)
    secret_name: Mapped[str] = mapped_column(Text, nullable=False)
    secret_version: Mapped[int | None] = mapped_column(Integer)
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    rate_limit: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LLMCredentialEnvelopeRow(Base):
    """Envelope-encrypted provider credential associated one-to-one with a configuration."""

    __tablename__ = "llm_credential_envelopes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["llm_config_id", "workspace_id"],
            ["llm_configurations.id", "llm_configurations.workspace_id"],
            name="fk_llm_credential_envelopes_config_workspace",
            ondelete="CASCADE",
        ),
        CheckConstraint("algorithm = 'AES-256-GCM'", name="algorithm"),
    )

    llm_config_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    credential_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    wrapped_data_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    wrapping_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    algorithm: Mapped[str] = mapped_column(
        String(32), nullable=False, default="AES-256-GCM", server_default="AES-256-GCM"
    )
    master_key_provider: Mapped[str] = mapped_column(Text, nullable=False)
    master_key_name: Mapped[str] = mapped_column(Text, nullable=False)
    master_key_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentDefinitionRow(Base):
    """One immutable-on-use version of an agent definition."""

    __tablename__ = "agent_definitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["llm_config_id", "workspace_id"],
            ["llm_configurations.id", "llm_configurations.workspace_id"],
            name="fk_agent_definitions_llm_config_workspace",
        ),
        ForeignKeyConstraint(
            ["superseded_by", "workspace_id"],
            ["agent_definitions.id", "agent_definitions.workspace_id"],
            name="fk_agent_definitions_superseded_workspace",
        ),
        CheckConstraint(
            "role_kind IN ('domain_expert', 'critic', 'orchestrator', 'retriever', 'evaluator')",
            name="role_kind",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'DEPRECATED', 'WITHDRAWN')",
            name="status",
        ),
        CheckConstraint("version > 0", name="version_positive"),
        UniqueConstraint("id", "workspace_id", name="uq_agent_definitions_id_workspace"),
        UniqueConstraint("logical_id", "version", name="uq_agent_definitions_logical_version"),
        UniqueConstraint(
            "workspace_id", "name", "version", name="uq_agent_definitions_workspace_name_version"
        ),
        Index("ix_agentdef_lookup", "workspace_id", "domain", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    logical_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    role_kind: Mapped[str] = mapped_column(Text, nullable=False)
    objectives: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    constraints: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    knowledge_ns: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)),
        nullable=False,
        default=list,
        server_default=text("'{}'::uuid[]"),
    )
    strategy_ref: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_ver: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_ref: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(Text, nullable=False)
    llm_config_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    tool_perms: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    budget: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="DRAFT", server_default="DRAFT"
    )
    superseded_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    referenced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LLMCallRecordRow(Base):
    """Durable per-call token, cost, latency, retry, and raw-artifact accounting."""

    __tablename__ = "llm_call_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_def_id", "workspace_id"],
            ["agent_definitions.id", "agent_definitions.workspace_id"],
            name="fk_llm_call_records_agent_workspace",
        ),
        ForeignKeyConstraint(
            ["llm_config_id", "workspace_id"],
            ["llm_configurations.id", "llm_configurations.workspace_id"],
            name="fk_llm_call_records_config_workspace",
        ),
        CheckConstraint("input_tokens >= 0", name="input_tokens_nonnegative"),
        CheckConstraint("output_tokens >= 0", name="output_tokens_nonnegative"),
        CheckConstraint("cost_usd >= 0", name="cost_nonnegative"),
        CheckConstraint("latency_ms >= 0", name="latency_nonnegative"),
        CheckConstraint("retry_attempts >= 0", name="retries_nonnegative"),
        Index("ix_llm_calls_workspace_created", "workspace_id", "created_at"),
        Index("ix_llm_calls_session", "session_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    agent_def_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    llm_config_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    finish_reason: Mapped[str] = mapped_column(Text, nullable=False)
    retry_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_artifact_ref: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
