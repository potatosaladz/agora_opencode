"""Add the authoritative mutable Phase 4 session lifecycle projection.

Revision ID: 20260905_0009
Revises: 20260905_0008
Migration type: expand
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260905_0009"
down_revision: str | None = "20260905_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATES = (
    "'DRAFT','INITIALIZING','RUNNING','WAITING_FOR_AGENT','WAITING_FOR_EVIDENCE',"
    "'WAITING_FOR_CRITIQUE','WAITING_FOR_SIMULATION','WAITING_FOR_HUMAN',"
    "'EVALUATING_CONSENSUS','PAUSED','FAILED_RETRYABLE','COMPLETED',"
    "'PARTIAL_CONSENSUS_STATE','NO_CONSENSUS','DEADLOCK','FAILED','CANCELLED'"
)
_TERMINAL_STATES = (
    "'COMPLETED','PARTIAL_CONSENSUS_STATE','NO_CONSENSUS','DEADLOCK','FAILED','CANCELLED'"
)


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_reasoning_events_workspace_session_id",
        "reasoning_events",
        ["workspace_id", "session_id", "id"],
    )
    op.create_table(
        "session_lifecycles",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.Text(), server_default="DRAFT", nullable=False),
        sa.Column("round", sa.Integer(), server_default="0", nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=True),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("last_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"state IN ({_STATES})", name=op.f("ck_session_lifecycles_state")),
        sa.CheckConstraint("round >= 0", name=op.f("ck_session_lifecycles_round_nonnegative")),
        sa.CheckConstraint(
            "(workflow_id IS NULL) = (run_id IS NULL)",
            name=op.f("ck_session_lifecycles_workflow_identity_pair"),
        ),
        sa.CheckConstraint(
            "(state = 'DRAFT') = (last_event_id IS NULL)",
            name=op.f("ck_session_lifecycles_transition_event"),
        ),
        sa.CheckConstraint(
            "state = 'DRAFT' OR initialized_at IS NOT NULL",
            name=op.f("ck_session_lifecycles_initialized_timestamp"),
        ),
        sa.CheckConstraint(
            "state IN ('DRAFT','INITIALIZING') OR started_at IS NOT NULL",
            name=op.f("ck_session_lifecycles_started_timestamp"),
        ),
        sa.CheckConstraint(
            f"(state IN ({_TERMINAL_STATES})) = (ended_at IS NOT NULL)",
            name=op.f("ck_session_lifecycles_terminal_timestamp"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_session_lifecycles_session_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "last_event_id"],
            [
                "reasoning_events.workspace_id",
                "reasoning_events.session_id",
                "reasoning_events.id",
            ],
            name="fk_session_lifecycles_last_event_workspace",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_session_lifecycles")),
        sa.UniqueConstraint(
            "workspace_id", "session_id", name="uq_session_lifecycles_workspace_id"
        ),
        sa.UniqueConstraint("workflow_id", name="uq_session_lifecycles_workflow_id"),
    )
    op.create_index(
        "ix_session_lifecycles_workspace_state",
        "session_lifecycles",
        ["workspace_id", "state", "updated_at"],
    )
    op.execute(
        "INSERT INTO session_lifecycles "
        "(session_id, workspace_id, state, round, created_at, updated_at) "
        "SELECT id, workspace_id, 'DRAFT', 0, created_at, updated_at FROM sessions"
    )
    op.execute("ALTER TABLE session_lifecycles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE session_lifecycles FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY session_lifecycles_workspace_isolation ON session_lifecycles "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.drop_index("ix_session_lifecycles_workspace_state", table_name="session_lifecycles")
    op.drop_table("session_lifecycles")
    op.drop_constraint(
        "uq_reasoning_events_workspace_session_id", "reasoning_events", type_="unique"
    )
