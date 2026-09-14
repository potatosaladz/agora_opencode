"""Tenant-safe, application-append-only audit rows (Phase 13, T13-02)."""

from __future__ import annotations

from datetime import date, datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["AccessLogRow", "AuditAnchorRow"]


# trace: FR-807, NFR-006
class AccessLogRow(Base):
    """One audited read. Rows are append-only and never mutate (FR-807/NFR-006)."""

    __tablename__ = "access_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_access_log_session",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "principal_class IN ('HUMAN','AGENT','SERVICE','POLICY')",
            name="principal_class",
        ),
        CheckConstraint("action = 'READ'", name="action"),
        CheckConstraint("result IN ('ALLOWED','DENIED','FAILED')", name="result"),
        CheckConstraint("length(btrim(resource_kind)) > 0", name="resource_kind"),
        CheckConstraint("length(btrim(trace_id)) > 0", name="trace_id"),
        CheckConstraint("jsonb_typeof(scope_ids) = 'array'", name="scope_ids_array"),
        UniqueConstraint("workspace_id", "id", name="uq_access_log_workspace_id"),
        Index(
            "ix_access_log_resource",
            "workspace_id",
            "resource_kind",
            "resource_id",
            "recorded_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    principal_class: Mapped[str] = mapped_column(Text, nullable=False)
    principal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    resource_kind: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    scope_ids: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    source_ip: Mapped[IPv4Address | IPv6Address | None] = mapped_column(INET)
    trace_id: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditAnchorRow(Base):
    """A session-day head anchor over the reasoning ledger. Append-only (Q8)."""

    __tablename__ = "audit_anchors"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_audit_anchors_session",
            ondelete="RESTRICT",
        ),
        CheckConstraint("head_seq > 0", name="head_seq"),
        CheckConstraint("head_hash ~ '^sha256:[0-9a-f]{64}$'", name="head_hash"),
        CheckConstraint("prev_head_hash ~ '^sha256:[0-9a-f]{64}$'", name="prev_head_hash"),
        CheckConstraint("anchor_hash ~ '^sha256:[0-9a-f]{64}$'", name="anchor_hash"),
        UniqueConstraint("workspace_id", "id", name="uq_audit_anchors_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "session_id",
            "anchor_day",
            name="uq_audit_anchors_session_day",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    anchor_day: Mapped[date] = mapped_column(Date, nullable=False)
    head_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    head_hash: Mapped[str] = mapped_column(Text, nullable=False)
    prev_head_hash: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_hash: Mapped[str] = mapped_column(Text, nullable=False)
    anchored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
