"""Append-only, tenant-safe retrieval attempt audit rows."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["RetrievalAttemptRow"]


# trace: FR-409
class RetrievalAttemptRow(Base):
    __tablename__ = "retrieval_attempts"
    __table_args__ = (
        CheckConstraint("principal_class IN ('HUMAN','AGENT')", name="principal_class"),
        CheckConstraint("query_hash ~ '^sha256:[0-9a-f]{64}$'", name="query_hash"),
        CheckConstraint(
            "cardinality(requested_namespace_ids) > 0", name="requested_scope_nonempty"
        ),
        CheckConstraint("lexical_count >= 0", name="lexical_count_nonnegative"),
        CheckConstraint("vector_count >= 0", name="vector_count_nonnegative"),
        CheckConstraint("result_count >= 0", name="result_count_nonnegative"),
        CheckConstraint("result_count = cardinality(result_chunk_ids)", name="result_census"),
        CheckConstraint(
            "result_count = cardinality(result_content_hashes)", name="result_hash_census"
        ),
        CheckConstraint(
            "cardinality(result_content_hashes) = 0 OR "
            "array_to_string(result_content_hashes, ',') ~ "
            "'^sha256:[0-9a-f]{64}(,sha256:[0-9a-f]{64})*$'",
            name="result_hashes",
        ),
        CheckConstraint("outcome IN ('ALLOWED','DENIED','RAG_FAILED')", name="outcome"),
        CheckConstraint(
            "degradation IS NULL OR degradation IN "
            "('NONE','LEXICAL_ONLY','INDEX_MISMATCH','RERANKER_FAILED')",
            name="degradation",
        ),
        CheckConstraint(
            "(outcome = 'ALLOWED' AND degradation IS NOT NULL) OR "
            "(outcome = 'DENIED' AND degradation IS NULL "
            "AND cardinality(searched_namespace_ids) = 0 "
            "AND lexical_count = 0 AND vector_count = 0 AND result_count = 0) OR "
            "(outcome = 'RAG_FAILED' AND result_count = 0)",
            name="outcome_census",
        ),
        Index("ix_retrieval_attempts_workspace_requested", "workspace_id", "requested_at"),
        Index("ix_retrieval_attempts_workspace_principal", "workspace_id", "principal_id"),
        Index("ix_retrieval_attempts_trace_id", "trace_id"),
    )

    attempt_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    trace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    principal_class: Mapped[str] = mapped_column(Text, nullable=False)
    principal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    query_hash: Mapped[str] = mapped_column(Text, nullable=False)
    requested_namespace_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False
    )
    searched_namespace_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)),
        nullable=False,
        default=list,
        server_default=text("'{}'::uuid[]"),
    )
    result_chunk_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)),
        nullable=False,
        default=list,
        server_default=text("'{}'::uuid[]"),
    )
    result_content_hashes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    index_version: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_version: Mapped[str] = mapped_column(Text, nullable=False)
    reranker_version: Mapped[str | None] = mapped_column(Text)
    lexical_count: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_count: Mapped[int] = mapped_column(Integer, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    degradation: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
