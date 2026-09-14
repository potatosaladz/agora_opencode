"""Add simulation_runs and simulation_results tables (DATA_MODEL §10).

Revision ID: 20260909_0020
Revises: 20260907_0019
Migration type: expand

trace: T8-05, FR-701, FR-702
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260909_0020"
down_revision: str | None = "20260907_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN_STATUSES = "'PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'TIMEOUT', 'REJECTED'"


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    policy = f"rls_{table}_workspace"
    op.execute(
        f"CREATE POLICY {policy} ON {table} "
        f"USING (workspace_id = current_setting("
        f"'app.current_workspace_id')::uuid)"
    )


def upgrade() -> None:
    # -- simulation_runs --
    op.create_table(
        "simulation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "requested_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_definitions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("engine", sa.Text(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("spec_ref", sa.Text(), nullable=False),
        sa.Column("spec_hash", sa.Text(), nullable=False),
        sa.Column("sandboxed", sa.Boolean(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("n_runs", sa.Integer(), nullable=False),
        sa.Column("horizon", sa.Text(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            f"status IN ({_RUN_STATUSES})",
            name=op.f("ck_simulation_runs_status"),
        ),
    )
    op.create_index(
        "ix_simulation_runs_workspace_session",
        "simulation_runs",
        ["workspace_id", "session_id"],
    )
    op.create_index(
        "ix_simulation_runs_spec_hash",
        "simulation_runs",
        ["spec_hash"],
    )
    _enable_rls("simulation_runs")

    # -- simulation_results --
    op.create_table(
        "simulation_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("variable", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("mean", sa.Numeric(18, 6), nullable=True),
        sa.Column("sd", sa.Numeric(18, 6), nullable=True),
        sa.Column("ci_low", sa.Numeric(18, 6), nullable=True),
        sa.Column("ci_high", sa.Numeric(18, 6), nullable=True),
        sa.Column(
            "quantiles", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("distribution", postgresql.JSONB(), nullable=True),
        sa.Column(
            "sensitivity", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("validity_domain", postgresql.JSONB(), nullable=False),
        sa.Column("object_ref", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "run_id",
            "variable",
            name="uq_simulation_results_run_variable",
        ),
    )
    op.create_index(
        "ix_simulation_results_run_id",
        "simulation_results",
        ["run_id"],
    )
    _enable_rls("simulation_results")


def downgrade() -> None:
    op.drop_table("simulation_results")
    op.drop_table("simulation_runs")
