"""Append-only Phase 12 MARL trajectory rows."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["MarlEpisodeRow", "MarlRecordRow"]


class MarlEpisodeRow(Base):
    __tablename__ = "marl_episodes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_marl_episodes_session",
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('OPEN','COMPLETE','INCOMPLETE')", name="status"),
        CheckConstraint("schema_version = 1", name="schema_version"),
        CheckConstraint("code_identity ~ '^sha256:[0-9a-f]{64}$'", name="code_identity"),
        UniqueConstraint("workspace_id", "id", name="uq_marl_episodes_workspace_id"),
        UniqueConstraint(
            "workspace_id", "session_id", "id", name="uq_marl_episodes_workspace_session_id"
        ),
        Index("ix_marl_episodes_workspace_status", "workspace_id", "status", "id"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    environment_version: Mapped[str] = mapped_column(Text, nullable=False)
    code_identity: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    incomplete_marker: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    incomplete_hash: Mapped[str | None] = mapped_column(Text)


class MarlRecordRow(Base):
    __tablename__ = "marl_trajectory_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "episode_id"],
            ["marl_episodes.workspace_id", "marl_episodes.session_id", "marl_episodes.id"],
            name="fk_marl_records_episode",
            ondelete="RESTRICT",
        ),
        CheckConstraint("decision_index >= 0", name="decision_index"),
        CheckConstraint("record_kind IN ('DECISION_BOUNDARY','TRANSITION')", name="record_kind"),
        CheckConstraint("record_hash ~ '^sha256:[0-9a-f]{64}$'", name="record_hash"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        UniqueConstraint(
            "workspace_id",
            "episode_id",
            "decision_index",
            "record_kind",
            name="uq_marl_records_decision_kind",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_marl_records_workspace_id"),
        Index(
            "ix_marl_records_order",
            "workspace_id",
            "episode_id",
            "decision_index",
            "record_kind",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    episode_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    decision_index: Mapped[int] = mapped_column(Integer, nullable=False)
    record_kind: Mapped[str] = mapped_column(Text, nullable=False)
    record_hash: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
