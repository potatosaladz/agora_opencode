"""Add validated semantic memory promotion history.

Revision ID: 20260906_0016
Revises: 20260906_0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260906_0016"
down_revision: str | None = "20260906_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "semantic_memory_entries",
    "memory_promotions",
    "memory_promotion_evidence",
    "memory_lifecycle_events",
)


def _tenant_and_append_only(table: str) -> None:
    op.execute(sa.text(f'REVOKE UPDATE, DELETE ON "{table}" FROM PUBLIC'))
    op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            f'CREATE POLICY "tenant_isolation_{table}" ON "{table}" '
            "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
            "WITH CHECK (workspace_id = "
            "NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
        )
    )
    op.execute(
        sa.text(
            f'CREATE TRIGGER "trg_{table}_append_only" BEFORE UPDATE OR DELETE ON "{table}" '
            "FOR EACH ROW EXECUTE FUNCTION reject_memory_history_mutation()"
        )
    )


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION reject_memory_history_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'memory history is append-only' USING ERRCODE = '27000';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.create_table(
        "semantic_memory_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("namespace_id", sa.UUID(), nullable=False),
        sa.Column("source_session_id", sa.UUID(), nullable=False),
        sa.Column("source_artifact_id", sa.UUID(), nullable=False),
        sa.Column("source_artifact_kind", sa.Text(), nullable=False),
        sa.Column("source_content_hash", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("supersedes_entry_id", sa.UUID(), nullable=True),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_content_hash ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_semantic_memory_entries_source_hash"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_semantic_memory_entries_version_positive")),
        sa.CheckConstraint(
            "(version = 1 AND supersedes_entry_id IS NULL) OR (version > 1 AND supersedes_entry_id IS NOT NULL)",  # noqa: E501
            name=op.f("ck_semantic_memory_entries_version_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "namespace_id"],
            ["knowledge_namespaces.workspace_id", "knowledge_namespaces.id"],
            name=op.f("fk_semantic_memory_entries_namespace"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_session_id", "source_artifact_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name=op.f("fk_semantic_memory_entries_artifact"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "supersedes_entry_id"],
            ["semantic_memory_entries.workspace_id", "semantic_memory_entries.id"],
            name=op.f("fk_semantic_memory_entries_supersedes"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_semantic_memory_entries")),
        sa.UniqueConstraint(
            "workspace_id", "id", name=op.f("uq_semantic_memory_entries_workspace_id")
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "source_artifact_id",
            "version",
            name=op.f("uq_semantic_memory_entries_artifact_version"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "supersedes_entry_id",
            name=op.f("uq_semantic_memory_entries_supersedes"),
        ),
    )
    op.create_index(
        "ix_semantic_memory_entries_namespace",
        "semantic_memory_entries",
        ["workspace_id", "namespace_id", "promoted_at"],
    )
    op.create_table(
        "memory_promotions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("entry_id", sa.UUID(), nullable=False),
        sa.Column("validator_id", sa.UUID(), nullable=False),
        sa.Column("second_validator_id", sa.UUID(), nullable=True),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("caveats", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_by", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "second_validator_id IS NULL OR second_validator_id <> validator_id",
            name=op.f("ck_memory_promotions_independent_validator"),
        ),
        sa.CheckConstraint(
            "length(btrim(justification)) > 0", name=op.f("ck_memory_promotions_justification")
        ),
        sa.CheckConstraint(
            "cardinality(caveats) > 0", name=op.f("ck_memory_promotions_caveats_nonempty")
        ),
        sa.CheckConstraint(
            "review_by IS NULL OR review_by > promoted_at",
            name=op.f("ck_memory_promotions_review_after_promotion"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "entry_id"],
            ["semantic_memory_entries.workspace_id", "semantic_memory_entries.id"],
            name=op.f("fk_memory_promotions_entry"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["validator_id", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name=op.f("fk_memory_promotions_validator"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["second_validator_id", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name=op.f("fk_memory_promotions_second_validator"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_promotions")),
        sa.UniqueConstraint("workspace_id", "entry_id", name=op.f("uq_memory_promotions_entry")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_memory_promotions_workspace_id")),
    )
    op.create_table(
        "memory_promotion_evidence",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("promotion_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("evidence_artifact_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "promotion_id"],
            ["memory_promotions.workspace_id", "memory_promotions.id"],
            name=op.f("fk_memory_promotion_evidence_promotion"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "evidence_artifact_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name=op.f("fk_memory_promotion_evidence_artifact"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "promotion_id",
            "evidence_artifact_id",
            name=op.f("pk_memory_promotion_evidence"),
        ),
    )
    op.create_table(
        "memory_lifecycle_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("entry_id", sa.UUID(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0", name=op.f("ck_memory_lifecycle_events_reason")
        ),
        sa.CheckConstraint(
            "state IN ('STALE','ARCHIVED')", name=op.f("ck_memory_lifecycle_events_state")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "entry_id"],
            ["semantic_memory_entries.workspace_id", "semantic_memory_entries.id"],
            name=op.f("fk_memory_lifecycle_events_entry"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name=op.f("fk_memory_lifecycle_events_actor"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_lifecycle_events")),
        sa.UniqueConstraint(
            "workspace_id", "entry_id", "state", name=op.f("uq_memory_lifecycle_events_state")
        ),
    )
    op.create_index(
        "ix_memory_lifecycle_events_entry_time",
        "memory_lifecycle_events",
        ["workspace_id", "entry_id", "recorded_at"],
    )
    op.execute("""
        CREATE FUNCTION validate_semantic_memory_entry() RETURNS trigger AS $$
        DECLARE
          namespace_tier text;
          artifact_kind text;
          artifact_hash text;
          artifact_status text;
          prior_version integer;
          prior_namespace uuid;
        BEGIN
          SELECT tier INTO namespace_tier FROM knowledge_namespaces
           WHERE workspace_id = NEW.workspace_id AND id = NEW.namespace_id;
          IF namespace_tier IS NULL OR namespace_tier NOT IN ('HISTORICAL', 'GLOBAL') THEN
            RAISE EXCEPTION 'semantic memory target must be HISTORICAL or GLOBAL';
          END IF;
          SELECT kind, content_hash, status INTO artifact_kind, artifact_hash, artifact_status
            FROM reasoning_artifacts WHERE workspace_id = NEW.workspace_id
             AND session_id = NEW.source_session_id AND id = NEW.source_artifact_id;
          IF artifact_kind IS NULL OR artifact_status <> 'ACTIVE'
             OR artifact_kind <> NEW.source_artifact_kind
             OR artifact_hash <> NEW.source_content_hash THEN
            RAISE EXCEPTION 'semantic memory source snapshot does not resolve';
          END IF;
          IF NEW.supersedes_entry_id IS NOT NULL THEN
            SELECT version, namespace_id INTO prior_version, prior_namespace
              FROM semantic_memory_entries WHERE workspace_id = NEW.workspace_id
               AND id = NEW.supersedes_entry_id;
            IF prior_version IS NULL OR NEW.version <> prior_version + 1
               OR NEW.namespace_id <> prior_namespace THEN
              RAISE EXCEPTION 'semantic memory supersession chain is invalid';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute(
        "CREATE TRIGGER trg_semantic_memory_entries_validate BEFORE INSERT "
        "ON semantic_memory_entries FOR EACH ROW EXECUTE FUNCTION validate_semantic_memory_entry()"
    )
    op.execute("""
        CREATE FUNCTION validate_memory_promotion() RETURNS trigger AS $$
        DECLARE target_tier text;
        DECLARE entry_promoted_at timestamptz;
        BEGIN
          IF NOT EXISTS (
              SELECT 1 FROM workspace_members m JOIN users u ON u.id = m.user_id
               WHERE m.workspace_id = NEW.workspace_id
                 AND m.user_id = NEW.validator_id AND u.is_active) THEN
            RAISE EXCEPTION 'memory validator must be active';
          END IF;
          SELECT n.tier, e.promoted_at INTO target_tier, entry_promoted_at
            FROM semantic_memory_entries e
            JOIN knowledge_namespaces n ON n.workspace_id = e.workspace_id AND n.id = e.namespace_id
            WHERE e.workspace_id = NEW.workspace_id AND e.id = NEW.entry_id;
          IF entry_promoted_at IS NULL OR entry_promoted_at <> NEW.promoted_at THEN
            RAISE EXCEPTION 'promotion timestamp must match semantic entry';
          END IF;
          IF EXISTS (SELECT 1 FROM unnest(NEW.caveats) AS caveat
                     WHERE length(btrim(caveat)) = 0) THEN
            RAISE EXCEPTION 'promotion caveats must not be blank';
          END IF;
          IF target_tier = 'GLOBAL' AND NEW.second_validator_id IS NULL THEN
            RAISE EXCEPTION 'global memory requires an independent second validator';
          END IF;
          IF NEW.second_validator_id IS NOT NULL AND NOT EXISTS (
              SELECT 1 FROM workspace_members m JOIN users u ON u.id = m.user_id
               WHERE m.workspace_id = NEW.workspace_id
                 AND m.user_id = NEW.second_validator_id AND u.is_active) THEN
            RAISE EXCEPTION 'second memory validator must be active';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute(
        "CREATE TRIGGER trg_memory_promotions_validate BEFORE INSERT ON memory_promotions "
        "FOR EACH ROW EXECUTE FUNCTION validate_memory_promotion()"
    )
    op.execute("""
        CREATE FUNCTION validate_memory_promotion_evidence()
        RETURNS trigger AS $$
        DECLARE source_session uuid;
        BEGIN
          SELECT e.source_session_id INTO source_session FROM memory_promotions p
            JOIN semantic_memory_entries e ON e.workspace_id = p.workspace_id AND e.id = p.entry_id
            WHERE p.workspace_id = NEW.workspace_id AND p.id = NEW.promotion_id;
          IF source_session IS NULL OR source_session <> NEW.session_id OR NOT EXISTS (
              SELECT 1 FROM reasoning_artifacts a WHERE a.workspace_id = NEW.workspace_id
               AND a.session_id = NEW.session_id AND a.id = NEW.evidence_artifact_id
               AND a.kind = 'EVIDENCE' AND a.status = 'ACTIVE') THEN
            RAISE EXCEPTION 'promotion evidence must be active session evidence';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute(
        "CREATE TRIGGER trg_memory_promotion_evidence_validate BEFORE INSERT "
        "ON memory_promotion_evidence FOR EACH ROW "
        "EXECUTE FUNCTION validate_memory_promotion_evidence()"
    )
    op.execute("""
        CREATE FUNCTION require_memory_promotion_evidence() RETURNS trigger AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM memory_promotion_evidence
                         WHERE workspace_id = NEW.workspace_id AND promotion_id = NEW.id) THEN
            RAISE EXCEPTION 'memory promotion requires evidence';
          END IF;
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_memory_promotions_require_evidence AFTER INSERT "
        "ON memory_promotions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION require_memory_promotion_evidence()"
    )
    op.execute("""
        CREATE FUNCTION require_semantic_memory_promotion() RETURNS trigger AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM memory_promotions
                         WHERE workspace_id = NEW.workspace_id AND entry_id = NEW.id) THEN
            RAISE EXCEPTION 'semantic memory entry requires validated promotion';
          END IF;
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_semantic_memory_entries_require_promotion "
        "AFTER INSERT ON semantic_memory_entries DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION require_semantic_memory_promotion()"
    )
    op.execute("""
        CREATE FUNCTION validate_memory_lifecycle_event() RETURNS trigger AS $$
        DECLARE prior_state text;
        DECLARE prior_time timestamptz;
        DECLARE promoted_time timestamptz;
        BEGIN
          IF NOT EXISTS (
              SELECT 1 FROM workspace_members m JOIN users u ON u.id = m.user_id
               WHERE m.workspace_id = NEW.workspace_id
                 AND m.user_id = NEW.actor_id AND u.is_active) THEN
            RAISE EXCEPTION 'memory lifecycle actor must be active';
          END IF;
          SELECT promoted_at INTO promoted_time FROM semantic_memory_entries
           WHERE workspace_id = NEW.workspace_id AND id = NEW.entry_id FOR UPDATE;
          SELECT state, recorded_at INTO prior_state, prior_time FROM memory_lifecycle_events
           WHERE workspace_id = NEW.workspace_id AND entry_id = NEW.entry_id
           ORDER BY recorded_at DESC, id DESC LIMIT 1;
          IF NEW.recorded_at < promoted_time OR
             (prior_time IS NOT NULL AND NEW.recorded_at <= prior_time) OR
             prior_state = 'ARCHIVED' OR
             (prior_state = 'STALE' AND NEW.state <> 'ARCHIVED') THEN
            RAISE EXCEPTION 'memory lifecycle transition is not monotonic';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute(
        "CREATE TRIGGER trg_memory_lifecycle_events_validate BEFORE INSERT "
        "ON memory_lifecycle_events FOR EACH ROW "
        "EXECUTE FUNCTION validate_memory_lifecycle_event()"
    )
    for table in _TABLES:
        _tenant_and_append_only(table)


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION validate_memory_lifecycle_event()")
    op.execute("DROP FUNCTION require_semantic_memory_promotion()")
    op.execute("DROP FUNCTION require_memory_promotion_evidence()")
    op.execute("DROP FUNCTION validate_memory_promotion_evidence()")
    op.execute("DROP FUNCTION validate_memory_promotion()")
    op.execute("DROP FUNCTION validate_semantic_memory_entry()")
    op.execute("DROP FUNCTION reject_memory_history_mutation()")
