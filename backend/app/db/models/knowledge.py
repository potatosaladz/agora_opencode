"""Tenant-safe SQLAlchemy rows for Phase 5 knowledge provenance."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = [
    "DocumentRow",
    "IngestionOperationRow",
    "KnowledgeChunkRow",
    "KnowledgeNamespaceRow",
    "NamespaceGrantRow",
    "SourceRow",
]


class KnowledgeNamespaceRow(Base):
    __tablename__ = "knowledge_namespaces"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_knowledge_namespaces_session_workspace",
        ),
        ForeignKeyConstraint(
            ["agent_def_id", "workspace_id"],
            ["agent_definitions.id", "agent_definitions.workspace_id"],
            name="fk_knowledge_namespaces_agent_workspace",
        ),
        CheckConstraint(
            "tier IN ('GLOBAL','WORKSPACE','DOMAIN','AGENT','SESSION','HISTORICAL')", name="tier"
        ),
        CheckConstraint("(tier = 'SESSION') = (session_id IS NOT NULL)", name="session_scope"),
        CheckConstraint("(tier = 'AGENT') = (agent_def_id IS NOT NULL)", name="agent_scope"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("jsonb_typeof(retention) = 'object'", name="retention_object"),
        UniqueConstraint("workspace_id", "id", name="uq_knowledge_namespaces_workspace_id"),
        UniqueConstraint(
            "workspace_id", "tier", "name", name="uq_knowledge_namespaces_workspace_tier_name"
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    agent_def_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    retention: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NamespaceGrantRow(Base):
    __tablename__ = "knowledge_namespace_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "namespace_id"],
            ["knowledge_namespaces.workspace_id", "knowledge_namespaces.id"],
            name="fk_namespace_grants_namespace_workspace",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "subject_kind IN ('WORKSPACE','USER','AGENT_DEFINITION','SESSION')", name="subject_kind"
        ),
        CheckConstraint("capability IN ('READ','WRITE')", name="capability"),
        CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="valid_interval"),
        UniqueConstraint(
            "workspace_id",
            "namespace_id",
            "subject_kind",
            "subject_id",
            "capability",
            "valid_from",
            name="uq_namespace_grants_identity",
        ),
        Index(
            "ix_namespace_grants_resolution",
            "workspace_id",
            "subject_kind",
            "subject_id",
            "capability",
            "valid_until",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    namespace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    subject_kind: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    capability: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SourceRow(Base):
    __tablename__ = "sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "namespace_id"],
            ["knowledge_namespaces.workspace_id", "knowledge_namespaces.id"],
            name="fk_sources_namespace_workspace",
        ),
        ForeignKeyConstraint(
            ["uploaded_by", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name="fk_sources_uploader_workspace",
        ),
        CheckConstraint("status IN ('PROCESSING','READY','FAILED','RETRACTED')", name="status"),
        CheckConstraint("content_hash ~ '^sha256:[0-9a-f]{64}$'", name="content_hash"),
        CheckConstraint("size_bytes >= 0", name="size_nonnegative"),
        CheckConstraint("(status = 'RETRACTED') = (retracted_at IS NOT NULL)", name="retraction"),
        CheckConstraint(
            "retraction_reason IS NULL OR status = 'RETRACTED'", name="retraction_reason"
        ),
        CheckConstraint(
            "status <> 'RETRACTED' OR length(btrim(retraction_reason)) > 0",
            name="retraction_reason_required",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_sources_workspace_id"),
        UniqueConstraint(
            "workspace_id", "id", "namespace_id", name="uq_sources_workspace_id_namespace"
        ),
        Index("ix_sources_workspace_namespace_status", "workspace_id", "namespace_id", "status"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    namespace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    citation: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    object_ref: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    trust_level: Mapped[str] = mapped_column(Text, nullable=False, server_default="UNKNOWN")
    license: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="READY")
    retracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retraction_reason: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class DocumentRow(Base):
    __tablename__ = "documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_documents_source_workspace",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "parent_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_documents_parent_workspace",
        ),
        CheckConstraint(
            "status IN ('PENDING','PARSING','CHUNKED','EMBEDDED','READY','FAILED')", name="status"
        ),
        CheckConstraint("page_count IS NULL OR page_count >= 0", name="page_count_nonnegative"),
        CheckConstraint("char_count IS NULL OR char_count >= 0", name="char_count_nonnegative"),
        CheckConstraint("jsonb_typeof(structure) = 'object'", name="structure_object"),
        UniqueConstraint("workspace_id", "id", name="uq_documents_workspace_id"),
        UniqueConstraint(
            "workspace_id", "id", "source_id", name="uq_documents_workspace_id_source"
        ),
        Index("ix_documents_workspace_source_status", "workspace_id", "source_id", "status"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    title: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default="und")
    structure: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    page_count: Mapped[int | None] = mapped_column(Integer)
    char_count: Mapped[int | None] = mapped_column(Integer)
    parser: Mapped[str] = mapped_column(Text, nullable=False)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class KnowledgeChunkRow(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_chunks_document_workspace",
            ondelete="RESTRICT",
        ),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint("token_count > 0", name="token_count_positive"),
        CheckConstraint("content_hash ~ '^sha256:[0-9a-f]{64}$'", name="content_hash"),
        CheckConstraint("jsonb_typeof(locator) = 'object'", name="locator_object"),
        UniqueConstraint("workspace_id", "id", name="uq_chunks_workspace_id"),
        UniqueConstraint(
            "workspace_id", "id", "document_id", name="uq_chunks_workspace_id_document"
        ),
        UniqueConstraint(
            "workspace_id", "document_id", "ordinal", name="uq_chunks_document_ordinal"
        ),
        UniqueConstraint(
            "workspace_id",
            "document_id",
            "content_hash",
            "chunker_version",
            name="uq_chunks_content_identity",
        ),
        Index("ix_chunks_workspace_document", "workspace_id", "document_id", "ordinal"),
        Index("ix_chunks_acl_gin", "acl", postgresql_using="gin"),
        Index("ix_chunks_search_vector_gin", "search_vector", postgresql_using="gin"),
        Index(
            "ix_chunks_text_trgm",
            "text",
            postgresql_using="gin",
            postgresql_ops={"text": "gin_trgm_ops"},
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    chunker_version: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "pg_catalog.to_tsvector('pg_catalog.simple'::pg_catalog.regconfig, text)",
            persisted=True,
        ),
        nullable=False,
    )
    acl: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)),
        nullable=False,
        default=list,
        server_default=sql_text("'{}'::uuid[]"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IngestionOperationRow(Base):
    __tablename__ = "knowledge_ingestion_operations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "namespace_id"],
            ["knowledge_namespaces.workspace_id", "knowledge_namespaces.id"],
            name="fk_ingestion_operations_namespace_workspace",
            ondelete="RESTRICT",
        ),
        CheckConstraint("request_hash ~ '^sha256:[0-9a-f]{64}$'", name="request_hash"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint(
            "acquire_state IN ('PENDING','RUNNING','SUCCEEDED','FAILED')", name="acquire_state"
        ),
        CheckConstraint(
            "parse_state IN ('PENDING','RUNNING','SUCCEEDED','FAILED')", name="parse_state"
        ),
        CheckConstraint(
            "embed_state IN ('PENDING','RUNNING','SUCCEEDED','FAILED')", name="embed_state"
        ),
        CheckConstraint(
            "index_state IN ('PENDING','RUNNING','SUCCEEDED','FAILED')", name="index_state"
        ),
        CheckConstraint(
            "failure_kind IS NULL OR failure_kind IN ('PERMANENT','TRANSIENT')",
            name="failure_kind",
        ),
        CheckConstraint(
            "failure_stage IS NULL OR failure_stage IN ('ACQUIRE','PARSE','EMBED','INDEX')",
            name="failure_stage",
        ),
        CheckConstraint(
            "(failure_code IS NULL) = (failure_stage IS NULL) AND "
            "(failure_code IS NULL) = (failure_kind IS NULL) AND "
            "(failure_code IS NULL) = (failure_detail IS NULL)",
            name="failure_complete",
        ),
        CheckConstraint(
            "failure_stage IS NULL OR "
            "(failure_stage = 'ACQUIRE' AND acquire_state = 'FAILED' AND parse_state <> 'FAILED' "
            "AND embed_state <> 'FAILED' AND index_state <> 'FAILED') OR "
            "(failure_stage = 'PARSE' AND acquire_state <> 'FAILED' AND parse_state = 'FAILED' "
            "AND embed_state <> 'FAILED' AND index_state <> 'FAILED') OR "
            "(failure_stage = 'EMBED' AND acquire_state <> 'FAILED' AND parse_state <> 'FAILED' "
            "AND embed_state = 'FAILED' AND index_state <> 'FAILED') OR "
            "(failure_stage = 'INDEX' AND acquire_state <> 'FAILED' AND parse_state <> 'FAILED' "
            "AND embed_state <> 'FAILED' AND index_state = 'FAILED')",
            name="failure_matches_state",
        ),
        CheckConstraint(
            "(failure_stage IS NULL) = (acquire_state <> 'FAILED' AND parse_state <> 'FAILED' "
            "AND embed_state <> 'FAILED' AND index_state <> 'FAILED')",
            name="failed_has_failure",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_ingestion_operations_workspace_id"),
        UniqueConstraint("workspace_id", "source_id", name="uq_ingestion_operations_source_id"),
        UniqueConstraint("workspace_id", "document_id", name="uq_ingestion_operations_document_id"),
        Index("ix_ingestion_operations_workspace_state", "workspace_id", "parse_state"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    namespace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    acquire_state: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    parse_state: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    embed_state: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    index_state: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    object_ref: Mapped[str | None] = mapped_column(Text)
    parse_warnings: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=sql_text("'{}'::text[]")
    )
    failure_stage: Mapped[str | None] = mapped_column(Text)
    failure_code: Mapped[str | None] = mapped_column(Text)
    failure_kind: Mapped[str | None] = mapped_column(Text)
    failure_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
