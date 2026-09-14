"""Tenant-safe append-only symbolic evaluation evidence rows."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["SymbolicEvaluationRow"]


class SymbolicEvaluationRow(Base):
    __tablename__ = "symbolic_evaluations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_symbolic_evaluations_session",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "formalization_revision_id"],
            ["formalizations.workspace_id", "formalizations.id"],
            name="fk_symbolic_evaluations_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_id", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name="fk_symbolic_evaluations_actor",
            ondelete="RESTRICT",
        ),
        CheckConstraint("ast_hash ~ '^sha256:[0-9a-f]{64}$'", name="ast_hash"),
        CheckConstraint("evidence_hash ~ '^sha256:[0-9a-f]{64}$'", name="evidence_hash"),
        CheckConstraint("status IN ('SAT','UNSAT','UNKNOWN')", name="status"),
        CheckConstraint("timeout_ms BETWEEN 1 AND 60000", name="timeout"),
        CheckConstraint("jsonb_typeof(witness) = 'array'", name="witness_array"),
        CheckConstraint("jsonb_typeof(unsat_core) = 'array'", name="core_array"),
        CheckConstraint(
            "(status='SAT' AND reason_unknown IS NULL AND jsonb_array_length(unsat_core)=0) OR "
            "(status='UNSAT' AND reason_unknown IS NULL AND jsonb_array_length(witness)=0 "
            "AND jsonb_array_length(unsat_core)>0) OR "
            "(status='UNKNOWN' AND length(btrim(reason_unknown))>0 "
            "AND jsonb_array_length(witness)=0 AND jsonb_array_length(unsat_core)=0)",
            name="evidence_shape",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_symbolic_evaluations_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "formalization_revision_id",
            "solver",
            "solver_version",
            "configuration_id",
            name="uq_symbolic_evaluations_exact_run",
        ),
        Index(
            "ix_symbolic_evaluations_revision",
            "workspace_id",
            "formalization_revision_id",
            "evaluated_at",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    formalization_revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    ast_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    witness: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    unsat_core: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)
    reason_unknown: Mapped[str | None] = mapped_column(Text)
    solver: Mapped[str] = mapped_column(Text, nullable=False)
    solver_version: Mapped[str] = mapped_column(Text, nullable=False)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration_id: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
