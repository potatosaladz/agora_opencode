"""Add immutable exact-revision symbolic evaluation evidence.

Revision ID: 20260912_0023
Revises: 20260912_0022
Migration type: expand
"""

# ruff: noqa: E501 -- PostgreSQL trigger SQL is kept audit-readable.

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260912_0023"
down_revision: str | None = "20260912_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# trace: FR-705, FR-706
def upgrade() -> None:
    op.create_table(
        "symbolic_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("formalization_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ast_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("witness", postgresql.JSONB(), nullable=False),
        sa.Column("unsat_core", postgresql.JSONB(), nullable=False),
        sa.Column("reason_unknown", sa.Text(), nullable=True),
        sa.Column("solver", sa.Text(), nullable=False),
        sa.Column("solver_version", sa.Text(), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=False),
        sa.Column("configuration_id", sa.Text(), nullable=False),
        sa.Column("evidence_hash", sa.Text(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "ast_hash ~ '^sha256:[0-9a-f]{64}$'", name=op.f("ck_symbolic_evaluations_ast_hash")
        ),
        sa.CheckConstraint(
            "evidence_hash ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_symbolic_evaluations_evidence_hash"),
        ),
        sa.CheckConstraint(
            "status IN ('SAT','UNSAT','UNKNOWN')", name=op.f("ck_symbolic_evaluations_status")
        ),
        sa.CheckConstraint(
            "timeout_ms BETWEEN 1 AND 60000", name=op.f("ck_symbolic_evaluations_timeout")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(witness) = 'array'", name=op.f("ck_symbolic_evaluations_witness_array")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(unsat_core) = 'array'", name=op.f("ck_symbolic_evaluations_core_array")
        ),
        sa.CheckConstraint(
            "(status='SAT' AND reason_unknown IS NULL AND jsonb_array_length(unsat_core)=0) OR (status='UNSAT' AND reason_unknown IS NULL AND jsonb_array_length(witness)=0 AND jsonb_array_length(unsat_core)>0) OR (status='UNKNOWN' AND length(btrim(reason_unknown))>0 AND jsonb_array_length(witness)=0 AND jsonb_array_length(unsat_core)=0)",
            name=op.f("ck_symbolic_evaluations_evidence_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name=op.f("fk_symbolic_evaluations_session"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "formalization_revision_id"],
            ["formalizations.workspace_id", "formalizations.id"],
            name=op.f("fk_symbolic_evaluations_revision"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name=op.f("fk_symbolic_evaluations_actor"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_symbolic_evaluations")),
        sa.UniqueConstraint(
            "workspace_id", "id", name=op.f("uq_symbolic_evaluations_workspace_id")
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "formalization_revision_id",
            "solver",
            "solver_version",
            "configuration_id",
            name=op.f("uq_symbolic_evaluations_exact_run"),
        ),
    )
    op.create_index(
        "ix_symbolic_evaluations_revision",
        "symbolic_evaluations",
        ["workspace_id", "formalization_revision_id", "evaluated_at"],
    )
    op.execute("""
        CREATE FUNCTION enforce_symbolic_evaluation_revision() RETURNS trigger AS $$
        DECLARE revision_hash text; revision_session uuid;
        BEGIN
          SELECT ast_hash, session_id INTO revision_hash, revision_session
          FROM formalizations
          WHERE workspace_id=NEW.workspace_id AND id=NEW.formalization_revision_id;
          IF revision_hash IS NULL OR revision_hash<>NEW.ast_hash OR revision_session<>NEW.session_id THEN
            RAISE EXCEPTION 'symbolic evaluation revision mismatch' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_symbolic_evaluations_revision AFTER INSERT ON symbolic_evaluations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_symbolic_evaluation_revision()"
    )
    op.execute(
        "CREATE TRIGGER trg_symbolic_evaluations_append_only BEFORE UPDATE OR DELETE ON symbolic_evaluations FOR EACH ROW EXECUTE FUNCTION reject_formalization_mutation()"
    )
    op.execute("REVOKE UPDATE, DELETE ON symbolic_evaluations FROM PUBLIC")
    op.execute("ALTER TABLE symbolic_evaluations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE symbolic_evaluations FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY symbolic_evaluations_workspace_isolation ON symbolic_evaluations USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_symbolic_evaluations_append_only ON symbolic_evaluations"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_symbolic_evaluations_revision ON symbolic_evaluations")
    op.drop_table("symbolic_evaluations")
    op.execute("DROP FUNCTION enforce_symbolic_evaluation_revision()")
