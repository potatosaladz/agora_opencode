"""Authoritative immutable T11-01 formalization rows."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["FormalizationDecisionRow", "FormalizationRow", "FormalizationValidationRow"]


class FormalizationRow(Base):
    __tablename__ = "formalizations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_formalizations_session",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "source_artifact_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_formalizations_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "supersedes_id"],
            ["formalizations.workspace_id", "formalizations.session_id", "formalizations.id"],
            name="fk_formalizations_supersedes",
            ondelete="RESTRICT",
        ),
        CheckConstraint("revision >= 1", name="revision"),
        CheckConstraint("source_artifact_version >= 1", name="source_version"),
        CheckConstraint("ast_hash ~ '^sha256:[0-9a-f]{64}$'", name="ast_hash"),
        CheckConstraint("jsonb_typeof(ast) = 'object'", name="ast_object"),
        CheckConstraint("ast = CAST(ast_canonical AS jsonb)", name="ast_canonical_content"),
        CheckConstraint(
            "ast_hash = 'sha256:' || encode(digest(convert_to(ast_canonical, 'UTF8'), "
            "'sha256'), 'hex')",
            name="ast_hash_consistent",
        ),
        CheckConstraint("jsonb_typeof(symbols) = 'array'", name="symbols_array"),
        CheckConstraint("length(btrim(canonical_rendering)) > 0", name="rendering"),
        CheckConstraint("length(btrim(fidelity_notes)) > 0", name="fidelity"),
        CheckConstraint("cardinality(limitations) > 0", name="limitations"),
        CheckConstraint("(revision = 1) = (supersedes_id IS NULL)", name="revision_shape"),
        CheckConstraint("actor_class IN ('HUMAN','AGENT','SERVICE','POLICY')", name="actor_class"),
        UniqueConstraint("workspace_id", "id", name="uq_formalizations_workspace_id"),
        UniqueConstraint(
            "workspace_id", "session_id", "id", name="uq_formalizations_workspace_session_id"
        ),
        UniqueConstraint(
            "workspace_id", "logical_id", "revision", name="uq_formalizations_logical_revision"
        ),
        UniqueConstraint("workspace_id", "supersedes_id", name="uq_formalizations_successor"),
        Index("ix_formalizations_head", "workspace_id", "logical_id", "revision"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    logical_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source_artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_artifact_logical_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_artifact_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ast: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ast_canonical: Mapped[str] = mapped_column(Text, nullable=False)
    ast_hash: Mapped[str] = mapped_column(Text, nullable=False)
    symbols: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    canonical_rendering: Mapped[str] = mapped_column(Text, nullable=False)
    premise_artifact_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False
    )
    limitations: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    fidelity_notes: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_class: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)


class FormalizationValidationRow(Base):
    __tablename__ = "formalization_validations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "formalization_revision_id"],
            ["formalizations.workspace_id", "formalizations.id"],
            name="fk_formalization_validations_revision",
            ondelete="RESTRICT",
        ),
        CheckConstraint("ast_hash ~ '^sha256:[0-9a-f]{64}$'", name="ast_hash"),
        CheckConstraint("jsonb_typeof(issues) = 'array'", name="issues_array"),
        CheckConstraint("success = (jsonb_array_length(issues) = 0)", name="result"),
        UniqueConstraint(
            "workspace_id",
            "formalization_revision_id",
            name="uq_formalization_validations_revision",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    formalization_revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    ast_hash: Mapped[str] = mapped_column(Text, nullable=False)
    validator_ruleset: Mapped[str] = mapped_column(Text, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    issues: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_class: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)


class FormalizationDecisionRow(Base):
    __tablename__ = "formalization_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "formalization_revision_id"],
            ["formalizations.workspace_id", "formalizations.id"],
            name="fk_formalization_decisions_revision",
            ondelete="RESTRICT",
        ),
        CheckConstraint("kind IN ('CONFIRMED','REJECTED')", name="kind"),
        CheckConstraint("length(btrim(reason)) > 0", name="reason"),
        CheckConstraint("ast_hash ~ '^sha256:[0-9a-f]{64}$'", name="ast_hash"),
        UniqueConstraint(
            "workspace_id", "formalization_revision_id", name="uq_formalization_decisions_revision"
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    formalization_revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    ast_hash: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
