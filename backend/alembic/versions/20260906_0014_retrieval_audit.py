"""Add append-only retrieval attempt audits.

Revision ID: 20260906_0014
Revises: 20260906_0013
Migration type: expand
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260906_0014"
down_revision: str | None = "20260906_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "retrieval_attempts",
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_class", sa.Text(), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("query_hash", sa.Text(), nullable=False),
        sa.Column("requested_namespace_ids", postgresql.ARRAY(postgresql.UUID()), nullable=False),
        sa.Column(
            "searched_namespace_ids",
            postgresql.ARRAY(postgresql.UUID()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column(
            "result_chunk_ids",
            postgresql.ARRAY(postgresql.UUID()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column(
            "result_content_hashes",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("index_version", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("embedding_version", sa.Text(), nullable=False),
        sa.Column("reranker_version", sa.Text(), nullable=True),
        sa.Column("lexical_count", sa.Integer(), nullable=False),
        sa.Column("vector_count", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("degradation", sa.Text(), nullable=True),
        sa.Column(
            "warnings",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "principal_class IN ('HUMAN','AGENT')",
            name=op.f("ck_retrieval_attempts_principal_class"),
        ),
        sa.CheckConstraint(
            "query_hash ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_retrieval_attempts_query_hash"),
        ),
        sa.CheckConstraint(
            "cardinality(requested_namespace_ids) > 0",
            name=op.f("ck_retrieval_attempts_requested_scope_nonempty"),
        ),
        sa.CheckConstraint(
            "lexical_count >= 0", name=op.f("ck_retrieval_attempts_lexical_count_nonnegative")
        ),
        sa.CheckConstraint(
            "vector_count >= 0", name=op.f("ck_retrieval_attempts_vector_count_nonnegative")
        ),
        sa.CheckConstraint(
            "result_count >= 0", name=op.f("ck_retrieval_attempts_result_count_nonnegative")
        ),
        sa.CheckConstraint(
            "result_count = cardinality(result_chunk_ids)",
            name=op.f("ck_retrieval_attempts_result_census"),
        ),
        sa.CheckConstraint(
            "result_count = cardinality(result_content_hashes)",
            name=op.f("ck_retrieval_attempts_result_hash_census"),
        ),
        sa.CheckConstraint(
            "cardinality(result_content_hashes) = 0 OR "
            "array_to_string(result_content_hashes, ',') ~ "
            "'^sha256:[0-9a-f]{64}(,sha256:[0-9a-f]{64})*$'",
            name=op.f("ck_retrieval_attempts_result_hashes"),
        ),
        sa.CheckConstraint(
            "outcome IN ('ALLOWED','DENIED')", name=op.f("ck_retrieval_attempts_outcome")
        ),
        sa.CheckConstraint(
            "degradation IS NULL OR degradation IN "
            "('NONE','LEXICAL_ONLY','INDEX_MISMATCH','RERANKER_FAILED')",
            name=op.f("ck_retrieval_attempts_degradation"),
        ),
        sa.CheckConstraint(
            "(outcome = 'ALLOWED' AND degradation IS NOT NULL) OR "
            "(outcome = 'DENIED' AND degradation IS NULL "
            "AND cardinality(searched_namespace_ids) = 0 "
            "AND lexical_count = 0 AND vector_count = 0 AND result_count = 0)",
            name=op.f("ck_retrieval_attempts_outcome_census"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_retrieval_attempts_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("attempt_id", name=op.f("pk_retrieval_attempts")),
    )
    op.create_index(
        "ix_retrieval_attempts_workspace_requested",
        "retrieval_attempts",
        ["workspace_id", "requested_at"],
    )
    op.create_index(
        "ix_retrieval_attempts_workspace_principal",
        "retrieval_attempts",
        ["workspace_id", "principal_id"],
    )
    op.create_index("ix_retrieval_attempts_trace_id", "retrieval_attempts", ["trace_id"])
    op.execute(
        """
        CREATE FUNCTION reject_retrieval_attempt_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'retrieval attempts are append-only' USING ERRCODE = '27000';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_retrieval_attempts_append_only "
        "BEFORE UPDATE OR DELETE ON retrieval_attempts "
        "FOR EACH ROW EXECUTE FUNCTION reject_retrieval_attempt_mutation()"
    )
    op.execute("REVOKE UPDATE, DELETE ON retrieval_attempts FROM PUBLIC")
    op.execute("ALTER TABLE retrieval_attempts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE retrieval_attempts FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY retrieval_attempts_workspace_isolation ON retrieval_attempts "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.drop_table("retrieval_attempts")
    op.execute("DROP FUNCTION IF EXISTS reject_retrieval_attempt_mutation()")
