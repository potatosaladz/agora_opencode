"""Add tenant-safe Phase 5 knowledge provenance tables.

Revision ID: 20260906_0010
Revises: 20260905_0009
Migration type: expand
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260906_0010"
down_revision: str | None = "20260905_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "knowledge_namespaces",
    "knowledge_namespace_grants",
    "sources",
    "documents",
    "chunks",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "knowledge_namespaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_def_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "retention", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "tier IN ('GLOBAL','WORKSPACE','DOMAIN','AGENT','SESSION','HISTORICAL')",
            name=op.f("ck_knowledge_namespaces_tier"),
        ),
        sa.CheckConstraint(
            "(tier = 'SESSION') = (session_id IS NOT NULL)",
            name=op.f("ck_knowledge_namespaces_session_scope"),
        ),
        sa.CheckConstraint(
            "(tier = 'AGENT') = (agent_def_id IS NOT NULL)",
            name=op.f("ck_knowledge_namespaces_agent_scope"),
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0", name=op.f("ck_knowledge_namespaces_name_not_blank")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(retention) = 'object'",
            name=op.f("ck_knowledge_namespaces_retention_object"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_knowledge_namespaces_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_knowledge_namespaces_session_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["agent_def_id", "workspace_id"],
            ["agent_definitions.id", "agent_definitions.workspace_id"],
            name="fk_knowledge_namespaces_agent_workspace",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_namespaces")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_knowledge_namespaces_workspace_id"),
        sa.UniqueConstraint(
            "workspace_id", "tier", "name", name="uq_knowledge_namespaces_workspace_tier_name"
        ),
    )
    op.create_table(
        "knowledge_namespace_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("namespace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_kind", sa.Text(), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "subject_kind IN ('WORKSPACE','USER','AGENT_DEFINITION','SESSION')",
            name=op.f("ck_knowledge_namespace_grants_subject_kind"),
        ),
        sa.CheckConstraint(
            "capability IN ('READ','WRITE')", name=op.f("ck_knowledge_namespace_grants_capability")
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name=op.f("ck_knowledge_namespace_grants_valid_interval"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "namespace_id"],
            ["knowledge_namespaces.workspace_id", "knowledge_namespaces.id"],
            name="fk_namespace_grants_namespace_workspace",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_namespace_grants")),
        sa.UniqueConstraint(
            "workspace_id",
            "namespace_id",
            "subject_kind",
            "subject_id",
            "capability",
            "valid_from",
            name="uq_namespace_grants_identity",
        ),
    )
    op.create_index(
        "ix_namespace_grants_resolution",
        "knowledge_namespace_grants",
        ["workspace_id", "subject_kind", "subject_id", "capability", "valid_until"],
    )
    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("namespace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("citation", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("object_ref", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("trust_level", sa.Text(), server_default="UNKNOWN", nullable=False),
        sa.Column("license", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="READY", nullable=False),
        sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retraction_reason", sa.Text(), nullable=True),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PROCESSING','READY','FAILED','RETRACTED')", name=op.f("ck_sources_status")
        ),
        sa.CheckConstraint(
            "content_hash ~ '^sha256:[0-9a-f]{64}$'", name=op.f("ck_sources_content_hash")
        ),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_sources_size_nonnegative")),
        sa.CheckConstraint(
            "(status = 'RETRACTED') = (retracted_at IS NOT NULL)",
            name=op.f("ck_sources_retraction"),
        ),
        sa.CheckConstraint(
            "retraction_reason IS NULL OR status = 'RETRACTED'",
            name=op.f("ck_sources_retraction_reason"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "namespace_id"],
            ["knowledge_namespaces.workspace_id", "knowledge_namespaces.id"],
            name="fk_sources_namespace_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name="fk_sources_uploader_workspace",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_sources_workspace_id"),
    )
    op.create_index(
        "ix_sources_workspace_namespace_status",
        "sources",
        ["workspace_id", "namespace_id", "status"],
    )
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), server_default="und", nullable=False),
        sa.Column(
            "structure", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=True),
        sa.Column("parser", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','PARSING','CHUNKED','EMBEDDED','READY','FAILED')",
            name=op.f("ck_documents_status"),
        ),
        sa.CheckConstraint(
            "page_count IS NULL OR page_count >= 0",
            name=op.f("ck_documents_page_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "char_count IS NULL OR char_count >= 0",
            name=op.f("ck_documents_char_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(structure) = 'object'", name=op.f("ck_documents_structure_object")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_documents_source_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "parent_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_documents_parent_workspace",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_documents_workspace_id"),
    )
    op.create_index(
        "ix_documents_workspace_source_status", "documents", ["workspace_id", "source_id", "status"]
    )
    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("locator", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("chunker_version", sa.Text(), nullable=False),
        sa.Column(
            "acl",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("ordinal >= 0", name=op.f("ck_chunks_ordinal_nonnegative")),
        sa.CheckConstraint("token_count > 0", name=op.f("ck_chunks_token_count_positive")),
        sa.CheckConstraint(
            "content_hash ~ '^sha256:[0-9a-f]{64}$'", name=op.f("ck_chunks_content_hash")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(locator) = 'object'", name=op.f("ck_chunks_locator_object")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_chunks_document_workspace",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_chunks_workspace_id"),
        sa.UniqueConstraint(
            "workspace_id", "document_id", "ordinal", name="uq_chunks_document_ordinal"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "document_id",
            "content_hash",
            "chunker_version",
            name="uq_chunks_content_identity",
        ),
    )
    op.create_index(
        "ix_chunks_workspace_document", "chunks", ["workspace_id", "document_id", "ordinal"]
    )
    op.create_index("ix_chunks_acl_gin", "chunks", ["acl"], postgresql_using="gin")
    op.create_index(
        "ix_chunks_text_trgm",
        "chunks",
        ["text"],
        postgresql_using="gin",
        postgresql_ops={"text": "gin_trgm_ops"},
    )

    _create_subject_guard()
    _create_immutability_guards()
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_workspace_isolation ON {table} "
            "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
            "WITH CHECK (workspace_id = "
            "NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
        )


def _create_subject_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_namespace_grant_subject() RETURNS trigger AS $$
        BEGIN
          IF NEW.subject_kind = 'WORKSPACE' AND NEW.subject_id <> NEW.workspace_id THEN
            RAISE EXCEPTION 'workspace grant subject must equal workspace' USING ERRCODE = '23503';
          ELSIF NEW.subject_kind = 'USER' AND NOT EXISTS (
            SELECT 1 FROM workspace_members m
            WHERE m.workspace_id = NEW.workspace_id AND m.user_id = NEW.subject_id
          ) THEN
            RAISE EXCEPTION 'grant user is not a workspace member' USING ERRCODE = '23503';
          ELSIF NEW.subject_kind = 'AGENT_DEFINITION' AND NOT EXISTS (
            SELECT 1 FROM agent_definitions a
            WHERE a.workspace_id = NEW.workspace_id AND a.id = NEW.subject_id
          ) THEN
            RAISE EXCEPTION 'grant agent is not in workspace' USING ERRCODE = '23503';
          ELSIF NEW.subject_kind = 'SESSION' AND NOT EXISTS (
            SELECT 1 FROM sessions s
            WHERE s.workspace_id = NEW.workspace_id AND s.id = NEW.subject_id
          ) THEN
            RAISE EXCEPTION 'grant session is not in workspace' USING ERRCODE = '23503';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_namespace_grant_subject "
        "AFTER INSERT OR UPDATE ON knowledge_namespace_grants DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION enforce_namespace_grant_subject()"
    )


def _create_immutability_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_knowledge_identity_immutability() RETURNS trigger AS $$
        BEGIN
          IF (TG_TABLE_NAME = 'knowledge_namespaces' AND
              (to_jsonb(NEW) - 'retention') IS DISTINCT FROM (to_jsonb(OLD) - 'retention'))
            OR (TG_TABLE_NAME = 'knowledge_namespace_grants' AND
              (to_jsonb(NEW) - 'valid_until') IS DISTINCT FROM (to_jsonb(OLD) - 'valid_until'))
            OR (TG_TABLE_NAME = 'sources' AND
              (to_jsonb(NEW) - ARRAY['status','retracted_at','retraction_reason']) IS DISTINCT FROM
              (to_jsonb(OLD) - ARRAY['status','retracted_at','retraction_reason']))
            OR (TG_TABLE_NAME = 'documents' AND
              (to_jsonb(NEW) -
                ARRAY['structure','page_count','char_count','status','error','updated_at'])
                IS DISTINCT FROM
              (to_jsonb(OLD) -
                ARRAY['structure','page_count','char_count','status','error','updated_at']))
            OR (TG_TABLE_NAME = 'chunks' AND
              (to_jsonb(NEW) - 'acl') IS DISTINCT FROM (to_jsonb(OLD) - 'acl')) THEN
            RAISE EXCEPTION 'knowledge provenance identity is immutable' USING ERRCODE = '27000';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION enforce_knowledge_identity_immutability()"
        )
    op.execute(
        """
        CREATE FUNCTION reject_knowledge_provenance_delete() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'knowledge provenance rows cannot be deleted' USING ERRCODE = '27000';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_no_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_knowledge_provenance_delete()"
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION IF EXISTS reject_knowledge_provenance_delete()")
    op.execute("DROP FUNCTION IF EXISTS enforce_knowledge_identity_immutability()")
    op.execute("DROP FUNCTION IF EXISTS enforce_namespace_grant_subject()")
