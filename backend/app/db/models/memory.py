"""Append-only semantic promotion and memory lifecycle rows."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = [
    "MemoryLifecycleEventRow",
    "MemoryPromotionEvidenceRow",
    "MemoryPromotionRow",
    "SemanticMemoryEntryRow",
]


class SemanticMemoryEntryRow(Base):
    __tablename__ = "semantic_memory_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "namespace_id"],
            ["knowledge_namespaces.workspace_id", "knowledge_namespaces.id"],
            name="fk_semantic_memory_entries_namespace",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "source_session_id", "source_artifact_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_semantic_memory_entries_artifact",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "supersedes_entry_id"],
            ["semantic_memory_entries.workspace_id", "semantic_memory_entries.id"],
            name="fk_semantic_memory_entries_supersedes",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("source_content_hash ~ '^sha256:[0-9a-f]{64}$'", name="source_hash"),
        CheckConstraint(
            "(version = 1 AND supersedes_entry_id IS NULL) OR (version > 1 AND supersedes_entry_id IS NOT NULL)",  # noqa: E501
            name="version_shape",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_semantic_memory_entries_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "source_artifact_id",
            "version",
            name="uq_semantic_memory_entries_artifact_version",
        ),
        UniqueConstraint(
            "workspace_id", "supersedes_entry_id", name="uq_semantic_memory_entries_supersedes"
        ),
        Index(
            "ix_semantic_memory_entries_namespace", "workspace_id", "namespace_id", "promoted_at"
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    namespace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_artifact_kind: Mapped[str] = mapped_column(Text, nullable=False)
    source_content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_entry_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    promoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryPromotionRow(Base):
    __tablename__ = "memory_promotions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "entry_id"],
            ["semantic_memory_entries.workspace_id", "semantic_memory_entries.id"],
            name="fk_memory_promotions_entry",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["validator_id", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name="fk_memory_promotions_validator",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["second_validator_id", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name="fk_memory_promotions_second_validator",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(btrim(justification)) > 0", name="justification"),
        CheckConstraint("cardinality(caveats) > 0", name="caveats_nonempty"),
        CheckConstraint(
            "second_validator_id IS NULL OR second_validator_id <> validator_id",
            name="independent_validator",
        ),
        CheckConstraint(
            "review_by IS NULL OR review_by > promoted_at", name="review_after_promotion"
        ),
        UniqueConstraint("workspace_id", "entry_id", name="uq_memory_promotions_entry"),
        UniqueConstraint("workspace_id", "id", name="uq_memory_promotions_workspace_id"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    entry_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    validator_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    second_validator_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    caveats: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemoryPromotionEvidenceRow(Base):
    __tablename__ = "memory_promotion_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "promotion_id"],
            ["memory_promotions.workspace_id", "memory_promotions.id"],
            name="fk_memory_promotion_evidence_promotion",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "evidence_artifact_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_memory_promotion_evidence_artifact",
            ondelete="RESTRICT",
        ),
        PrimaryKeyConstraint(
            "workspace_id",
            "promotion_id",
            "evidence_artifact_id",
            name="pk_memory_promotion_evidence",
        ),
    )
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    promotion_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    evidence_artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)


class MemoryLifecycleEventRow(Base):
    __tablename__ = "memory_lifecycle_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "entry_id"],
            ["semantic_memory_entries.workspace_id", "semantic_memory_entries.id"],
            name="fk_memory_lifecycle_events_entry",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_id", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name="fk_memory_lifecycle_events_actor",
            ondelete="RESTRICT",
        ),
        CheckConstraint("state IN ('STALE','ARCHIVED')", name="state"),
        CheckConstraint("length(btrim(reason)) > 0", name="reason"),
        UniqueConstraint(
            "workspace_id", "entry_id", "state", name="uq_memory_lifecycle_events_state"
        ),
        Index("ix_memory_lifecycle_events_entry_time", "workspace_id", "entry_id", "recorded_at"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    entry_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
