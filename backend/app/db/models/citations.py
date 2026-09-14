"""Tenant-safe citation dependency and source-retraction rows."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["EvidenceCitationRow", "SourceRetractionRow"]


class EvidenceCitationRow(Base):
    __tablename__ = "evidence_citations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "evidence_artifact_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_evidence_citations_evidence",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "claim_artifact_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_evidence_citations_claim",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_id", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name="fk_evidence_citations_actor",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "source_id", "namespace_id"],
            ["sources.workspace_id", "sources.id", "sources.namespace_id"],
            name="fk_evidence_citations_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "document_id", "source_id"],
            ["documents.workspace_id", "documents.id", "documents.source_id"],
            name="fk_evidence_citations_document",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "chunk_id", "document_id"],
            ["chunks.workspace_id", "chunks.id", "chunks.document_id"],
            name="fk_evidence_citations_chunk",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(btrim(citation)) > 0", name="citation"),
        CheckConstraint(
            "jsonb_typeof(locator) = 'object' "
            "AND jsonb_typeof(locator -> 'char_start') = 'number' "
            "AND jsonb_typeof(locator -> 'char_end') = 'number' "
            "AND (locator ->> 'char_start')::bigint >= 0 "
            "AND (locator ->> 'char_end')::bigint > "
            "(locator ->> 'char_start')::bigint",
            name="locator",
        ),
        CheckConstraint("source_content_hash ~ '^sha256:[0-9a-f]{64}$'", name="source_hash"),
        CheckConstraint("chunk_content_hash ~ '^sha256:[0-9a-f]{64}$'", name="chunk_hash"),
        CheckConstraint(
            "source_status IN ('PROCESSING','READY','FAILED','RETRACTED')",
            name="source_status",
        ),
        UniqueConstraint(
            "workspace_id",
            "evidence_artifact_id",
            "chunk_id",
            name="uq_evidence_citations_evidence_chunk",
        ),
        Index("ix_evidence_citations_source", "workspace_id", "source_id"),
        Index("ix_evidence_citations_claim", "workspace_id", "claim_artifact_id"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    evidence_artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    claim_artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    namespace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    chunk_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    citation: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    chunker_version: Mapped[str] = mapped_column(Text, nullable=False)
    source_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    document_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trust_level: Mapped[str] = mapped_column(Text, nullable=False)
    source_status: Mapped[str] = mapped_column(Text, nullable=False)
    attached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SourceRetractionRow(Base):
    __tablename__ = "source_retractions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_source_retractions_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_id", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name="fk_source_retractions_actor",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(btrim(reason)) > 0", name="reason"),
        UniqueConstraint("workspace_id", "source_id", name="uq_source_retractions_source"),
        UniqueConstraint("workspace_id", "id", name="uq_source_retractions_workspace_id"),
        Index("ix_source_retractions_workspace_time", "workspace_id", "retracted_at"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    retracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
