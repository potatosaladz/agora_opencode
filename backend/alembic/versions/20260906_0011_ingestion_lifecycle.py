"""Add durable source-ingestion checkpoints.

Revision ID: 20260906_0011
Revises: 20260906_0010
Migration type: expand
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260906_0011"
down_revision: str | None = "20260906_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "knowledge_ingestion_operations"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("namespace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("acquire_state", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("parse_state", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("embed_state", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("index_state", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("object_ref", sa.Text(), nullable=True),
        sa.Column(
            "parse_warnings",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("failure_stage", sa.Text(), nullable=True),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("failure_kind", sa.Text(), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "request_hash ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_knowledge_ingestion_operations_request_hash"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_knowledge_ingestion_operations_attempt_count_nonnegative"),
        ),
        *(
            sa.CheckConstraint(
                f"{stage}_state IN ('PENDING','RUNNING','SUCCEEDED','FAILED')",
                name=op.f(f"ck_knowledge_ingestion_operations_{stage}_state"),
            )
            for stage in ("acquire", "parse", "embed", "index")
        ),
        sa.CheckConstraint(
            "failure_kind IS NULL OR failure_kind IN ('PERMANENT','TRANSIENT')",
            name=op.f("ck_knowledge_ingestion_operations_failure_kind"),
        ),
        sa.CheckConstraint(
            "failure_stage IS NULL OR failure_stage IN ('ACQUIRE','PARSE','EMBED','INDEX')",
            name=op.f("ck_knowledge_ingestion_operations_failure_stage"),
        ),
        sa.CheckConstraint(
            "(failure_code IS NULL) = (failure_stage IS NULL) AND "
            "(failure_code IS NULL) = (failure_kind IS NULL) AND "
            "(failure_code IS NULL) = (failure_detail IS NULL)",
            name=op.f("ck_knowledge_ingestion_operations_failure_complete"),
        ),
        sa.CheckConstraint(
            "failure_stage IS NULL OR "
            "(failure_stage = 'ACQUIRE' AND acquire_state = 'FAILED' AND parse_state <> 'FAILED' "
            "AND embed_state <> 'FAILED' AND index_state <> 'FAILED') OR "
            "(failure_stage = 'PARSE' AND acquire_state <> 'FAILED' AND parse_state = 'FAILED' "
            "AND embed_state <> 'FAILED' AND index_state <> 'FAILED') OR "
            "(failure_stage = 'EMBED' AND acquire_state <> 'FAILED' AND parse_state <> 'FAILED' "
            "AND embed_state = 'FAILED' AND index_state <> 'FAILED') OR "
            "(failure_stage = 'INDEX' AND acquire_state <> 'FAILED' AND parse_state <> 'FAILED' "
            "AND embed_state <> 'FAILED' AND index_state = 'FAILED')",
            name=op.f("ck_knowledge_ingestion_operations_failure_matches_state"),
        ),
        sa.CheckConstraint(
            "(failure_stage IS NULL) = (acquire_state <> 'FAILED' AND parse_state <> 'FAILED' "
            "AND embed_state <> 'FAILED' AND index_state <> 'FAILED')",
            name=op.f("ck_knowledge_ingestion_operations_failed_has_failure"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="RESTRICT",
            name=op.f("fk_knowledge_ingestion_operations_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "namespace_id"],
            ["knowledge_namespaces.workspace_id", "knowledge_namespaces.id"],
            ondelete="RESTRICT",
            name="fk_ingestion_operations_namespace_workspace",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_ingestion_operations")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_ingestion_operations_workspace_id"),
        sa.UniqueConstraint("workspace_id", "source_id", name="uq_ingestion_operations_source_id"),
        sa.UniqueConstraint(
            "workspace_id", "document_id", name="uq_ingestion_operations_document_id"
        ),
    )
    op.create_index(
        "ix_ingestion_operations_workspace_state", _TABLE, ["workspace_id", "parse_state"]
    )
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{_TABLE} ON {_TABLE} USING "
        "(workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK "
        "(workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )
    op.execute(
        """
        CREATE FUNCTION enforce_ingestion_operation_immutability() RETURNS trigger AS $$
        BEGIN
          IF (to_jsonb(NEW) - ARRAY['acquire_state','parse_state','embed_state','index_state',
              'attempt_count','object_ref','parse_warnings','failure_stage','failure_code','failure_kind',
              'failure_detail','updated_at']) IS DISTINCT FROM
             (to_jsonb(OLD) - ARRAY['acquire_state','parse_state','embed_state','index_state',
              'attempt_count','object_ref','parse_warnings','failure_stage','failure_code','failure_kind',
              'failure_detail','updated_at']) THEN
            RAISE EXCEPTION 'ingestion operation identity is immutable' USING ERRCODE = '27000';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"CREATE TRIGGER trg_{_TABLE}_immutable BEFORE UPDATE ON {_TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION enforce_ingestion_operation_immutability()"
    )
    op.execute(
        f"CREATE TRIGGER trg_{_TABLE}_no_delete BEFORE DELETE ON {_TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION reject_knowledge_provenance_delete()"
    )


def downgrade() -> None:
    op.drop_table(_TABLE)
    op.execute("DROP FUNCTION IF EXISTS enforce_ingestion_operation_immutability()")
