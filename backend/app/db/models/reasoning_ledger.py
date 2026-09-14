"""Tenant-safe rows for the Phase 3 append-only reasoning ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.reasoning_ledger import GENESIS_HASH

__all__ = ["ReasoningEventRow", "SessionLedgerHeadRow"]


class SessionLedgerHeadRow(Base):
    """Lockable allocator and committed chain head for one session."""

    __tablename__ = "session_ledger_heads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_session_ledger_heads_session_workspace",
        ),
        CheckConstraint("next_seq > 0", name="next_seq_positive"),
        CheckConstraint("head_hash ~ '^sha256:[0-9a-f]{64}$'", name="head_hash_format"),
    )

    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    next_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1")
    head_hash: Mapped[str] = mapped_column(
        Text, nullable=False, default=GENESIS_HASH, server_default=text(f"'{GENESIS_HASH}'")
    )


class ReasoningEventRow(Base):
    """One immutable event in a session-local hash chain."""

    __tablename__ = "reasoning_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_reasoning_events_session_workspace",
        ),
        CheckConstraint("ledger_seq > 0", name="ledger_seq_positive"),
        CheckConstraint("payload_schema_version > 0", name="payload_schema_version_positive"),
        CheckConstraint(
            "actor_class IN ('HUMAN', 'AGENT', 'SERVICE', 'POLICY')", name="actor_class"
        ),
        CheckConstraint("round >= 0", name="round_nonnegative"),
        CheckConstraint("payload_hash ~ '^sha256:[0-9a-f]{64}$'", name="payload_hash_format"),
        CheckConstraint("prev_hash ~ '^sha256:[0-9a-f]{64}$'", name="prev_hash_format"),
        CheckConstraint("event_hash ~ '^sha256:[0-9a-f]{64}$'", name="event_hash_format"),
        UniqueConstraint("session_id", "ledger_seq", name="uq_reasoning_events_session_seq"),
        UniqueConstraint(
            "workspace_id", "session_id", "id", name="uq_reasoning_events_workspace_session_id"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    ledger_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor_class: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prev_hash: Mapped[str] = mapped_column(Text, nullable=False)
    event_hash: Mapped[str] = mapped_column(Text, nullable=False)
