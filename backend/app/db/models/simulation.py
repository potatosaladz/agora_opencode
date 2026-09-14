"""SQLAlchemy rows for durable Phase 8 simulation runs and results."""

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
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["SimulationResultRow", "SimulationRunRow"]

_RUN_STATUSES = "'PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'TIMEOUT', 'REJECTED'"


class SimulationRunRow(Base):
    """One tenant-scoped durable simulation execution."""

    __tablename__ = "simulation_runs"
    __table_args__ = (
        CheckConstraint(f"status IN ({_RUN_STATUSES})", name="status"),
        Index("ix_simulation_runs_workspace_session", "workspace_id", "session_id"),
        Index("ix_simulation_runs_spec_hash", "spec_hash"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False
    )
    requested_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_definitions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    engine: Mapped[str] = mapped_column(Text, nullable=False)
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    spec_ref: Mapped[str] = mapped_column(Text, nullable=False)
    spec_hash: Mapped[str] = mapped_column(Text, nullable=False)
    sandboxed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    n_runs: Mapped[int] = mapped_column(Integer, nullable=False)
    horizon: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class SimulationResultRow(Base):
    """One named output variable produced by a simulation run."""

    __tablename__ = "simulation_results"
    __table_args__ = (
        UniqueConstraint("run_id", "variable", name="uq_simulation_results_run_variable"),
        Index("ix_simulation_results_run_id", "run_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False
    )
    variable: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    mean: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    sd: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    ci_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    ci_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    quantiles: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    distribution: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sensitivity: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    validity_domain: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    object_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
