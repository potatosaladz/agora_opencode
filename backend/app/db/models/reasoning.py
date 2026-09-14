"""Tenant-safe rows for the frozen Phase 3 session and artifact schema."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = [
    "ReasoningArtifactRow",
    "SessionAgentInterventionRow",
    "SessionAgentRow",
    "SessionConstraintRow",
    "SessionObjectiveRow",
    "SessionRow",
]


class SessionRow(Base):
    """A fully bound Phase 3 draft session; workflow state arrives in Phase 4."""

    __tablename__ = "sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "created_by"],
            ["workspace_members.workspace_id", "workspace_members.user_id"],
            name="fk_sessions_creator_workspace",
        ),
        CheckConstraint("status = 'DRAFT'", name="status_draft"),
        CheckConstraint("length(btrim(problem_statement)) > 0", name="problem_not_blank"),
        CheckConstraint("max_rounds BETWEEN 1 AND 50", name="max_rounds_range"),
        CheckConstraint("budget_tokens > 0", name="budget_tokens_positive"),
        CheckConstraint("budget_usd > 0", name="budget_usd_positive"),
        CheckConstraint("round >= 0", name="round_nonnegative"),
        UniqueConstraint("workspace_id", "id", name="uq_sessions_workspace_id"),
        Index("ix_sessions_workspace_status", "workspace_id", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="DRAFT", server_default=text("'DRAFT'")
    )
    problem_statement: Mapped[str] = mapped_column(Text, nullable=False)
    max_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    budget_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SessionAgentRow(Base):
    """A session pin to one immutable agent-definition version row."""

    __tablename__ = "session_agents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_session_agents_session_workspace",
        ),
        ForeignKeyConstraint(
            ["agent_def_id", "workspace_id"],
            ["agent_definitions.id", "agent_definitions.workspace_id"],
            name="fk_session_agents_agent_workspace",
        ),
        PrimaryKeyConstraint("session_id", "agent_def_id", name="pk_session_agents"),
        Index("ix_session_agents_workspace_agent", "workspace_id", "agent_def_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    agent_def_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    bound_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SessionAgentInterventionRow(Base):
    """One immutable coordinator-approved membership delta effective from a round."""

    __tablename__ = "session_agent_interventions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_session_agent_interventions_session_workspace",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "event_id"],
            ["reasoning_events.workspace_id", "reasoning_events.session_id", "reasoning_events.id"],
            name="fk_session_agent_interventions_event_workspace_session",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agent_def_id", "workspace_id"],
            ["agent_definitions.id", "agent_definitions.workspace_id"],
            name="fk_session_agent_interventions_agent_workspace",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replaced_agent_def_id", "workspace_id"],
            ["agent_definitions.id", "agent_definitions.workspace_id"],
            name="fk_session_agent_interventions_replaced_agent_workspace",
            ondelete="RESTRICT",
        ),
        CheckConstraint("kind IN ('REPLACE','INJECT')", name="kind"),
        CheckConstraint("effective_round >= 1", name="effective_round_positive"),
        CheckConstraint(
            "(kind = 'REPLACE' AND replaced_agent_def_id IS NOT NULL) OR "
            "(kind = 'INJECT' AND replaced_agent_def_id IS NULL)",
            name="replacement_shape",
        ),
        CheckConstraint(
            "replaced_agent_def_id IS NULL OR replaced_agent_def_id <> agent_def_id",
            name="replacement_differs",
        ),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        UniqueConstraint(
            "workspace_id", "session_id", "event_id", name="uq_session_agent_interventions_scope"
        ),
        Index(
            "ix_session_agent_interventions_effective",
            "workspace_id",
            "session_id",
            "effective_round",
            "recorded_at",
            "event_id",
        ),
    )

    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    replaced_agent_def_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    agent_def_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    effective_round: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReasoningArtifactRow(Base):
    """One immutable typed artifact revision in the unified Phase 3 store."""

    __tablename__ = "reasoning_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_reasoning_artifacts_session_workspace",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "supersedes_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_reasoning_artifacts_supersedes_workspace_session",
        ),
        CheckConstraint(
            "kind IN ('CLAIM', 'FACT', 'ASSUMPTION', 'INFERENCE', 'PROPOSITION', "
            "'EVIDENCE', 'UNCERTAINTY', 'RISK', 'IMPACT', 'OBJECTIVE', 'CONSTRAINT', "
            "'ALTERNATIVE', 'POSITION', 'CRITIQUE')",
            name="kind",
        ),
        CheckConstraint("schema_version > 0", name="schema_version_positive"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("status IN ('ACTIVE', 'SUPERSEDED', 'WITHDRAWN')", name="status"),
        CheckConstraint(
            "owner_actor_class IN ('HUMAN', 'AGENT', 'SERVICE', 'POLICY')",
            name="owner_actor_class",
        ),
        CheckConstraint("round >= 0", name="round_nonnegative"),
        CheckConstraint("content_hash ~ '^sha256:[0-9a-f]{64}$'", name="content_hash_format"),
        CheckConstraint(
            "((version = 1 AND supersedes_id IS NULL) OR "
            "(version > 1 AND supersedes_id IS NOT NULL))",
            name="revision_shape",
        ),
        CheckConstraint("validate_reasoning_artifact_payload(kind, payload)", name="payload"),
        CheckConstraint(
            "validate_reasoning_artifact_envelope(kind, version, owner_actor_class, payload, "
            "provenance, source_references, parent_relationships, confidence, metadata)",
            name="envelope",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_reasoning_artifacts_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "session_id",
            "id",
            name="uq_reasoning_artifacts_workspace_session_id",
        ),
        UniqueConstraint(
            "workspace_id",
            "session_id",
            "logical_id",
            "version",
            name="uq_reasoning_artifacts_logical_version",
        ),
        Index(
            "ix_reasoning_artifacts_session_kind",
            "workspace_id",
            "session_id",
            "kind",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    logical_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="ACTIVE", server_default=text("'ACTIVE'")
    )
    supersedes_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    owner_actor_class: Mapped[str] = mapped_column(Text, nullable=False)
    owner_actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_references: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    parent_relationships: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    confidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SessionObjectiveRow(Base):
    """A typed objective artifact committed as part of a session binding."""

    __tablename__ = "session_objectives"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_session_objectives_session_workspace",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "artifact_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_session_objectives_artifact_workspace_session",
        ),
        PrimaryKeyConstraint("session_id", "artifact_id", name="pk_session_objectives"),
        Index("ix_session_objectives_workspace_artifact", "workspace_id", "artifact_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)


class SessionConstraintRow(Base):
    """A typed constraint artifact committed as part of a session binding."""

    __tablename__ = "session_constraints"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_session_constraints_session_workspace",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "artifact_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_session_constraints_artifact_workspace_session",
        ),
        PrimaryKeyConstraint("session_id", "artifact_id", name="pk_session_constraints"),
        Index("ix_session_constraints_workspace_artifact", "workspace_id", "artifact_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
