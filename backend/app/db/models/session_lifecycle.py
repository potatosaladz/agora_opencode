"""SQLAlchemy row for the authoritative mutable session lifecycle projection."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["SessionLifecycleRow"]


class SessionLifecycleRow(Base):
    __tablename__ = "session_lifecycles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_session_lifecycles_session_workspace",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "last_event_id"],
            [
                "reasoning_events.workspace_id",
                "reasoning_events.session_id",
                "reasoning_events.id",
            ],
            name="fk_session_lifecycles_last_event_workspace",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("workspace_id", "session_id", name="uq_session_lifecycles_workspace_id"),
        UniqueConstraint("workflow_id", name="uq_session_lifecycles_workflow_id"),
        CheckConstraint(
            "state IN ('DRAFT','INITIALIZING','RUNNING','WAITING_FOR_AGENT',"
            "'WAITING_FOR_EVIDENCE','WAITING_FOR_CRITIQUE','WAITING_FOR_SIMULATION',"
            "'WAITING_FOR_HUMAN','EVALUATING_CONSENSUS','PAUSED','FAILED_RETRYABLE',"
            "'COMPLETED','PARTIAL_CONSENSUS_STATE','NO_CONSENSUS','DEADLOCK','FAILED','CANCELLED')",
            name="state",
        ),
        CheckConstraint("round >= 0", name="round_nonnegative"),
        CheckConstraint("(workflow_id IS NULL) = (run_id IS NULL)", name="workflow_identity_pair"),
        CheckConstraint("(state = 'DRAFT') = (last_event_id IS NULL)", name="transition_event"),
        CheckConstraint(
            "state = 'DRAFT' OR initialized_at IS NOT NULL", name="initialized_timestamp"
        ),
        CheckConstraint(
            "state IN ('DRAFT','INITIALIZING') OR started_at IS NOT NULL",
            name="started_timestamp",
        ),
        CheckConstraint(
            "(state IN ('COMPLETED','PARTIAL_CONSENSUS_STATE','NO_CONSENSUS','DEADLOCK','FAILED',"
            "'CANCELLED')) = (ended_at IS NOT NULL)",
            name="terminal_timestamp",
        ),
        Index("ix_session_lifecycles_workspace_state", "workspace_id", "state", "updated_at"),
    )

    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(
        Text, nullable=False, default="DRAFT", server_default="DRAFT"
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    workflow_id: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(Text)
    last_event_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    initialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
