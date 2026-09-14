"""Add append-only effective-round session membership interventions.

Revision ID: 20260907_0018
Revises: 20260906_0017
Migration type: expand
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260907_0018"
down_revision: str | None = "20260906_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_agent_interventions",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("replaced_agent_def_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_def_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("effective_round", sa.Integer(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('REPLACE','INJECT')", name=op.f("ck_session_agent_interventions_kind")
        ),
        sa.CheckConstraint(
            "effective_round >= 1",
            name=op.f("ck_session_agent_interventions_effective_round_positive"),
        ),
        sa.CheckConstraint(
            "(kind = 'REPLACE' AND replaced_agent_def_id IS NOT NULL) OR "
            "(kind = 'INJECT' AND replaced_agent_def_id IS NULL)",
            name=op.f("ck_session_agent_interventions_replacement_shape"),
        ),
        sa.CheckConstraint(
            "replaced_agent_def_id IS NULL OR replaced_agent_def_id <> agent_def_id",
            name=op.f("ck_session_agent_interventions_replacement_differs"),
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0",
            name=op.f("ck_session_agent_interventions_reason_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_session_agent_interventions_session_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "event_id"],
            ["reasoning_events.workspace_id", "reasoning_events.session_id", "reasoning_events.id"],
            name="fk_session_agent_interventions_event_workspace_session",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_def_id", "workspace_id"],
            ["agent_definitions.id", "agent_definitions.workspace_id"],
            name="fk_session_agent_interventions_agent_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_agent_def_id", "workspace_id"],
            ["agent_definitions.id", "agent_definitions.workspace_id"],
            name="fk_session_agent_interventions_replaced_agent_workspace",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_session_agent_interventions")),
        sa.UniqueConstraint(
            "workspace_id", "session_id", "event_id", name="uq_session_agent_interventions_scope"
        ),
    )
    op.create_index(
        "ix_session_agent_interventions_effective",
        "session_agent_interventions",
        ["workspace_id", "session_id", "effective_round", "recorded_at", "event_id"],
    )
    op.execute("ALTER TABLE session_agent_interventions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE session_agent_interventions FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY session_agent_interventions_workspace_isolation "
        "ON session_agent_interventions "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )
    op.execute(
        """
        CREATE FUNCTION reject_session_agent_intervention_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'session agent interventions are append-only' USING ERRCODE = '27000';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_session_agent_interventions_append_only "
        "BEFORE UPDATE OR DELETE ON session_agent_interventions "
        "FOR EACH ROW EXECUTE FUNCTION reject_session_agent_intervention_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_session_agent_interventions_append_only "
        "ON session_agent_interventions"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_session_agent_intervention_mutation()")
    op.drop_index(
        "ix_session_agent_interventions_effective",
        table_name="session_agent_interventions",
    )
    op.drop_table("session_agent_interventions")
