"""Add tenant-safe append-only access logging and daily audit anchors.

Revision ID: 20260912_0025
Revises: 20260912_0024
Migration type: expand

Phase 13 minimal audit persistence (T13-02): ``access_log`` answers the §4
"who saw what" question for Q7 and ``audit_anchors`` makes the reasoning-ledger
chain verifiable across sessions and days for Q8. Both tables are forced-RLS,
caller-append-only through application roles (REVOKE + rejecting trigger), and
use the same composite ``(workspace_id, session_id)`` tenant-safe foreign key
into ``sessions`` as every other post-Phase-3 table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260912_0025"
down_revision: str | None = "20260912_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_workspace_isolation ON {table} "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )


# trace: FR-807, NFR-006
def upgrade() -> None:
    op.create_table(
        "access_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_class", sa.Text(), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_kind", sa.Text(), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column(
            "scope_ids", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("source_ip", postgresql.INET(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "principal_class IN ('HUMAN','AGENT','SERVICE','POLICY')",
            name=op.f("ck_access_log_principal_class"),
        ),
        sa.CheckConstraint("action = 'READ'", name=op.f("ck_access_log_action")),
        sa.CheckConstraint(
            "result IN ('ALLOWED','DENIED','FAILED')", name=op.f("ck_access_log_result")
        ),
        sa.CheckConstraint(
            "length(btrim(resource_kind)) > 0", name=op.f("ck_access_log_resource_kind")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(scope_ids) = 'array'", name=op.f("ck_access_log_scope_ids_array")
        ),
        sa.CheckConstraint("length(btrim(trace_id)) > 0", name=op.f("ck_access_log_trace_id")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name=op.f("fk_access_log_session"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_log")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_access_log_workspace_id")),
    )
    op.create_index(
        "ix_access_log_resource",
        "access_log",
        ["workspace_id", "resource_kind", "resource_id", "recorded_at", "id"],
    )
    op.create_table(
        "audit_anchors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("anchor_day", sa.Date(), nullable=False),
        sa.Column("head_seq", sa.BigInteger(), nullable=False),
        sa.Column("head_hash", sa.Text(), nullable=False),
        sa.Column("prev_head_hash", sa.Text(), nullable=False),
        sa.Column("anchor_hash", sa.Text(), nullable=False),
        sa.Column("anchored_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("head_seq > 0", name=op.f("ck_audit_anchors_head_seq")),
        sa.CheckConstraint(
            "head_hash ~ '^sha256:[0-9a-f]{64}$'", name=op.f("ck_audit_anchors_head_hash")
        ),
        sa.CheckConstraint(
            "prev_head_hash ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_audit_anchors_prev_head_hash"),
        ),
        sa.CheckConstraint(
            "anchor_hash ~ '^sha256:[0-9a-f]{64}$'", name=op.f("ck_audit_anchors_anchor_hash")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name=op.f("fk_audit_anchors_session"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_anchors")),
        sa.UniqueConstraint(
            "workspace_id", "session_id", "anchor_day", name=op.f("uq_audit_anchors_session_day")
        ),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_audit_anchors_workspace_id")),
    )
    op.execute("""
        CREATE FUNCTION reject_audit_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'audit rows are append-only' USING ERRCODE = '27000';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute(
        "CREATE TRIGGER trg_access_log_append_only BEFORE UPDATE OR DELETE ON access_log "
        "FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation()"
    )
    op.execute(
        "CREATE TRIGGER trg_audit_anchors_append_only BEFORE UPDATE OR DELETE ON audit_anchors "
        "FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation()"
    )
    op.execute("REVOKE UPDATE, DELETE ON access_log FROM PUBLIC")
    op.execute("REVOKE UPDATE, DELETE ON audit_anchors FROM PUBLIC")
    _rls("access_log")
    _rls("audit_anchors")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_anchors_append_only ON audit_anchors")
    op.execute("DROP TRIGGER IF EXISTS trg_access_log_append_only ON access_log")
    op.drop_table("audit_anchors")
    op.drop_table("access_log")
    op.execute("DROP FUNCTION reject_audit_mutation()")
