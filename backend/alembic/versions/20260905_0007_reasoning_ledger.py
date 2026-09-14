"""Add the tenant-safe append-only Phase 3 reasoning ledger.

Revision ID: 20260905_0007
Revises: 20260905_0006
Migration type: expand
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260905_0007"
down_revision: str | None = "20260905_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GENESIS_HASH = "sha256:" + "0" * 64


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_workspace_isolation ON {table} "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = "
        "NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )


def upgrade() -> None:
    op.create_table(
        "session_ledger_heads",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("next_seq", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "head_hash", sa.Text(), server_default=sa.text(f"'{_GENESIS_HASH}'"), nullable=False
        ),
        sa.CheckConstraint("next_seq > 0", name=op.f("ck_session_ledger_heads_next_seq_positive")),
        sa.CheckConstraint(
            "head_hash ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_session_ledger_heads_head_hash_format"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_session_ledger_heads_session_workspace",
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_session_ledger_heads")),
    )
    op.create_table(
        "reasoning_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ledger_seq", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload_schema_version", sa.Integer(), nullable=False),
        sa.Column("causation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_class", sa.Text(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("round", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prev_hash", sa.Text(), nullable=False),
        sa.Column("event_hash", sa.Text(), nullable=False),
        sa.CheckConstraint("ledger_seq > 0", name=op.f("ck_reasoning_events_ledger_seq_positive")),
        sa.CheckConstraint(
            "payload_schema_version > 0",
            name=op.f("ck_reasoning_events_payload_schema_version_positive"),
        ),
        sa.CheckConstraint(
            "actor_class IN ('HUMAN', 'AGENT', 'SERVICE', 'POLICY')",
            name=op.f("ck_reasoning_events_actor_class"),
        ),
        sa.CheckConstraint("round >= 0", name=op.f("ck_reasoning_events_round_nonnegative")),
        sa.CheckConstraint(
            "payload_hash ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_reasoning_events_payload_hash_format"),
        ),
        sa.CheckConstraint(
            "prev_hash ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_reasoning_events_prev_hash_format"),
        ),
        sa.CheckConstraint(
            "event_hash ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_reasoning_events_event_hash_format"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_reasoning_events_session_workspace",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reasoning_events")),
        sa.UniqueConstraint("session_id", "ledger_seq", name="uq_reasoning_events_session_seq"),
    )
    op.execute(
        "INSERT INTO session_ledger_heads (workspace_id, session_id) "
        "SELECT workspace_id, id FROM sessions"
    )
    op.execute(
        """
        CREATE FUNCTION create_session_ledger_head() RETURNS trigger AS $$
        BEGIN
          INSERT INTO session_ledger_heads (workspace_id, session_id)
          VALUES (NEW.workspace_id, NEW.id);
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_session_ledger_head AFTER INSERT ON sessions "
        "FOR EACH ROW EXECUTE FUNCTION create_session_ledger_head()"
    )
    op.execute(
        """
        CREATE FUNCTION reject_reasoning_event_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'reasoning events are append-only' USING ERRCODE = '27000';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_reasoning_events_append_only "
        "BEFORE UPDATE OR DELETE ON reasoning_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_reasoning_event_mutation()"
    )
    op.execute("REVOKE UPDATE, DELETE ON reasoning_events FROM PUBLIC")
    _enable_rls("session_ledger_heads")
    _enable_rls("reasoning_events")


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_reasoning_events_append_only ON reasoning_events")
    op.execute("DROP FUNCTION reject_reasoning_event_mutation()")
    op.execute("DROP TRIGGER trg_session_ledger_head ON sessions")
    op.execute("DROP FUNCTION create_session_ledger_head()")
    op.drop_table("reasoning_events")
    op.drop_table("session_ledger_heads")
