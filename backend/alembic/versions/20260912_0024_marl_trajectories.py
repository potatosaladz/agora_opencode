# ruff: noqa: E501 -- PostgreSQL DDL is kept audit-readable.
"""Add deterministic append-only MARL trajectory persistence.

Revision ID: 20260912_0024
Revises: 20260912_0023
Migration type: expand
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260912_0024"
down_revision: str | None = "20260912_0023"
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


# trace: FR-906, NFR-003, NFR-010, NFR-016
def upgrade() -> None:
    op.create_table(
        "marl_episodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("environment_version", sa.Text(), nullable=False),
        sa.Column("code_identity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("incomplete_marker", postgresql.JSONB(), nullable=True),
        sa.Column("incomplete_hash", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('OPEN','COMPLETE','INCOMPLETE')", name=op.f("ck_marl_episodes_status")
        ),
        sa.CheckConstraint("schema_version = 1", name=op.f("ck_marl_episodes_schema_version")),
        sa.CheckConstraint(
            "code_identity ~ '^sha256:[0-9a-f]{64}$'", name=op.f("ck_marl_episodes_code_identity")
        ),
        sa.CheckConstraint(
            "(status='OPEN' AND incomplete_marker IS NULL AND incomplete_hash IS NULL) OR "
            "(status='COMPLETE' AND incomplete_marker IS NULL AND incomplete_hash IS NULL) OR "
            "(status='INCOMPLETE' AND jsonb_typeof(incomplete_marker)='object' AND incomplete_hash ~ '^sha256:[0-9a-f]{64}$')",
            name=op.f("ck_marl_episodes_status_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name=op.f("fk_marl_episodes_session"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marl_episodes")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_marl_episodes_workspace_id")),
        sa.UniqueConstraint(
            "workspace_id", "session_id", "id", name=op.f("uq_marl_episodes_workspace_session_id")
        ),
    )
    op.create_index(
        "ix_marl_episodes_workspace_status", "marl_episodes", ["workspace_id", "status", "id"]
    )
    op.create_table(
        "marl_trajectory_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision_index", sa.Integer(), nullable=False),
        sa.Column("record_kind", sa.Text(), nullable=False),
        sa.Column("record_hash", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "decision_index >= 0", name=op.f("ck_marl_trajectory_records_decision_index")
        ),
        sa.CheckConstraint(
            "record_kind IN ('DECISION_BOUNDARY','TRANSITION')",
            name=op.f("ck_marl_trajectory_records_record_kind"),
        ),
        sa.CheckConstraint(
            "record_hash ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_marl_trajectory_records_record_hash"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name=op.f("ck_marl_trajectory_records_payload_object"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "episode_id"],
            ["marl_episodes.workspace_id", "marl_episodes.session_id", "marl_episodes.id"],
            name=op.f("fk_marl_records_episode"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marl_trajectory_records")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_marl_records_workspace_id")),
        sa.UniqueConstraint(
            "workspace_id",
            "episode_id",
            "decision_index",
            "record_kind",
            name=op.f("uq_marl_records_decision_kind"),
        ),
    )
    op.create_index(
        "ix_marl_records_order",
        "marl_trajectory_records",
        ["workspace_id", "episode_id", "decision_index", "record_kind"],
    )
    op.execute("""
        CREATE FUNCTION enforce_marl_episode_transition() RETURNS trigger AS $$
        BEGIN
          IF OLD.status <> 'OPEN' OR NEW.id <> OLD.id OR NEW.workspace_id <> OLD.workspace_id
             OR NEW.session_id <> OLD.session_id OR NEW.schema_version <> OLD.schema_version
             OR NEW.environment_version <> OLD.environment_version
             OR NEW.code_identity <> OLD.code_identity
             OR NEW.status NOT IN ('COMPLETE','INCOMPLETE') THEN
            RAISE EXCEPTION 'MARL episode identity is immutable and status transition is invalid' USING ERRCODE='27000';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE FUNCTION reject_marl_record_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'MARL trajectory records are append-only' USING ERRCODE='27000'; END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute(
        "CREATE TRIGGER trg_marl_episodes_transition BEFORE UPDATE ON marl_episodes "
        "FOR EACH ROW EXECUTE FUNCTION enforce_marl_episode_transition()"
    )
    op.execute(
        "CREATE TRIGGER trg_marl_episodes_no_delete BEFORE DELETE ON marl_episodes "
        "FOR EACH ROW EXECUTE FUNCTION reject_marl_record_mutation()"
    )
    op.execute(
        "CREATE TRIGGER trg_marl_records_append_only BEFORE UPDATE OR DELETE ON marl_trajectory_records "
        "FOR EACH ROW EXECUTE FUNCTION reject_marl_record_mutation()"
    )
    op.execute("REVOKE DELETE ON marl_episodes FROM PUBLIC")
    op.execute("REVOKE UPDATE, DELETE ON marl_trajectory_records FROM PUBLIC")
    _rls("marl_episodes")
    _rls("marl_trajectory_records")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_marl_records_append_only ON marl_trajectory_records")
    op.execute("DROP TRIGGER IF EXISTS trg_marl_episodes_no_delete ON marl_episodes")
    op.execute("DROP TRIGGER IF EXISTS trg_marl_episodes_transition ON marl_episodes")
    op.drop_table("marl_trajectory_records")
    op.drop_table("marl_episodes")
    op.execute("DROP FUNCTION reject_marl_record_mutation()")
    op.execute("DROP FUNCTION enforce_marl_episode_transition()")
