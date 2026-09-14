"""Add resolvable evidence citations and additive source retractions.

Revision ID: 20260906_0015
Revises: 20260906_0014
Migration type: expand
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260906_0015"
down_revision: str | None = "20260906_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE sources SET retraction_reason = 'legacy retraction; reason unavailable' "
        "WHERE status = 'RETRACTED' AND "
        "(retraction_reason IS NULL OR length(btrim(retraction_reason)) = 0)"
    )
    op.create_check_constraint(
        op.f("ck_sources_retraction_reason_required"),
        "sources",
        "status <> 'RETRACTED' OR length(btrim(retraction_reason)) > 0",
    )
    op.create_table(
        "evidence_citations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("namespace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("citation", sa.Text(), nullable=False),
        sa.Column("locator", postgresql.JSONB(), nullable=False),
        sa.Column("source_content_hash", sa.Text(), nullable=False),
        sa.Column("chunk_content_hash", sa.Text(), nullable=False),
        sa.Column("chunker_version", sa.Text(), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trust_level", sa.Text(), nullable=False),
        sa.Column("source_status", sa.Text(), nullable=False),
        sa.Column(
            "attached_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(btrim(citation)) > 0", name=op.f("ck_evidence_citations_citation")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(locator) = 'object' "
            "AND jsonb_typeof(locator -> 'char_start') = 'number' "
            "AND jsonb_typeof(locator -> 'char_end') = 'number' "
            "AND (locator ->> 'char_start')::bigint >= 0 "
            "AND (locator ->> 'char_end')::bigint > "
            "(locator ->> 'char_start')::bigint",
            name=op.f("ck_evidence_citations_locator"),
        ),
        sa.CheckConstraint(
            "source_content_hash ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_evidence_citations_source_hash"),
        ),
        sa.CheckConstraint(
            "chunk_content_hash ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_evidence_citations_chunk_hash"),
        ),
        sa.CheckConstraint(
            "source_status IN ('PROCESSING','READY','FAILED','RETRACTED')",
            name=op.f("ck_evidence_citations_source_status"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "evidence_artifact_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name=op.f("fk_evidence_citations_evidence"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "claim_artifact_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name=op.f("fk_evidence_citations_claim"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name=op.f("fk_evidence_citations_actor"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id", "namespace_id"],
            ["sources.workspace_id", "sources.id", "sources.namespace_id"],
            name=op.f("fk_evidence_citations_source"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id", "source_id"],
            ["documents.workspace_id", "documents.id", "documents.source_id"],
            name=op.f("fk_evidence_citations_document"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "chunk_id", "document_id"],
            ["chunks.workspace_id", "chunks.id", "chunks.document_id"],
            name=op.f("fk_evidence_citations_chunk"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_citations")),
        sa.UniqueConstraint(
            "workspace_id",
            "evidence_artifact_id",
            "chunk_id",
            name=op.f("uq_evidence_citations_evidence_chunk"),
        ),
    )
    op.create_index(
        "ix_evidence_citations_source", "evidence_citations", ["workspace_id", "source_id"]
    )
    op.create_index(
        "ix_evidence_citations_claim", "evidence_citations", ["workspace_id", "claim_artifact_id"]
    )

    op.create_table(
        "source_retractions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(btrim(reason)) > 0", name=op.f("ck_source_retractions_reason")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name=op.f("fk_source_retractions_source"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name=op.f("fk_source_retractions_actor"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_retractions")),
        sa.UniqueConstraint("workspace_id", "source_id", name=op.f("uq_source_retractions_source")),
    )
    op.create_index(
        "ix_source_retractions_workspace_time",
        "source_retractions",
        ["workspace_id", "retracted_at"],
    )

    op.execute(
        """
        CREATE FUNCTION reject_citation_fact_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'citation and retraction facts are append-only' USING ERRCODE = '27000';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("evidence_citations", "source_retractions"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_citation_fact_mutation()"
        )
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM PUBLIC")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_workspace_isolation ON {table} "
            "USING (workspace_id = "
            "NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
            "WITH CHECK (workspace_id = "
            "NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
        )

    op.execute(
        """
        CREATE FUNCTION enforce_source_retraction_once() RETURNS trigger AS $$
        BEGIN
          IF OLD.status = 'RETRACTED' AND (NEW.status, NEW.retracted_at, NEW.retraction_reason)
             IS DISTINCT FROM (OLD.status, OLD.retracted_at, OLD.retraction_reason) THEN
            RAISE EXCEPTION 'source retraction is irreversible' USING ERRCODE = '27000';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_sources_retraction_once BEFORE UPDATE ON sources "
        "FOR EACH ROW EXECUTE FUNCTION enforce_source_retraction_once()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_sources_retraction_once ON sources")
    op.execute("DROP FUNCTION enforce_source_retraction_once()")
    op.drop_table("source_retractions")
    op.drop_table("evidence_citations")
    op.execute("DROP FUNCTION reject_citation_fact_mutation()")
    op.drop_constraint(op.f("ck_sources_retraction_reason_required"), "sources", type_="check")
