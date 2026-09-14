"""Add immutable formalization revisions, validation facts, and human decisions.

Revision ID: 20260912_0022
Revises: 20260911_0021
Migration type: expand
"""

# ruff: noqa: E501 -- PostgreSQL trigger SQL is kept readable and audit-equivalent to installed DDL.

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260912_0022"
down_revision: str | None = "20260911_0021"
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


# trace: FR-707
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "formalizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logical_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_artifact_logical_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_artifact_version", sa.Integer(), nullable=False),
        sa.Column("ast", postgresql.JSONB(), nullable=False),
        sa.Column("ast_canonical", sa.Text(), nullable=False),
        sa.Column("ast_hash", sa.Text(), nullable=False),
        sa.Column("symbols", postgresql.JSONB(), nullable=False),
        sa.Column("canonical_rendering", sa.Text(), nullable=False),
        sa.Column(
            "premise_artifact_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False
        ),
        sa.Column("limitations", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("fidelity_notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_class", sa.Text(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_formalizations_revision")),
        sa.CheckConstraint(
            "source_artifact_version >= 1", name=op.f("ck_formalizations_source_version")
        ),
        sa.CheckConstraint(
            "ast_hash ~ '^sha256:[0-9a-f]{64}$'", name=op.f("ck_formalizations_ast_hash")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(ast) = 'object'", name=op.f("ck_formalizations_ast_object")
        ),
        sa.CheckConstraint(
            "ast = CAST(ast_canonical AS jsonb)",
            name=op.f("ck_formalizations_ast_canonical_content"),
        ),
        sa.CheckConstraint(
            "ast_hash = 'sha256:' || encode(digest(convert_to(ast_canonical, 'UTF8'), "
            "'sha256'), 'hex')",
            name=op.f("ck_formalizations_ast_hash_consistent"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(symbols) = 'array'", name=op.f("ck_formalizations_symbols_array")
        ),
        sa.CheckConstraint(
            "length(btrim(canonical_rendering)) > 0", name=op.f("ck_formalizations_rendering")
        ),
        sa.CheckConstraint(
            "length(btrim(fidelity_notes)) > 0", name=op.f("ck_formalizations_fidelity")
        ),
        sa.CheckConstraint(
            "cardinality(limitations) > 0", name=op.f("ck_formalizations_limitations")
        ),
        sa.CheckConstraint(
            "(revision = 1) = (supersedes_id IS NULL)",
            name=op.f("ck_formalizations_revision_shape"),
        ),
        sa.CheckConstraint(
            "actor_class IN ('HUMAN','AGENT','SERVICE','POLICY')",
            name=op.f("ck_formalizations_actor_class"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name=op.f("fk_formalizations_session"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "source_artifact_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name=op.f("fk_formalizations_source"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_formalizations")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_formalizations_workspace_id")),
        sa.UniqueConstraint(
            "workspace_id", "session_id", "id", name=op.f("uq_formalizations_workspace_session_id")
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "logical_id",
            "revision",
            name=op.f("uq_formalizations_logical_revision"),
        ),
        sa.UniqueConstraint(
            "workspace_id", "supersedes_id", name=op.f("uq_formalizations_successor")
        ),
    )
    op.create_foreign_key(
        op.f("fk_formalizations_supersedes"),
        "formalizations",
        "formalizations",
        ["workspace_id", "session_id", "supersedes_id"],
        ["workspace_id", "session_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_formalizations_head", "formalizations", ["workspace_id", "logical_id", "revision"]
    )

    op.create_table(
        "formalization_validations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("formalization_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ast_hash", sa.Text(), nullable=False),
        sa.Column("validator_ruleset", sa.Text(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("issues", postgresql.JSONB(), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_class", sa.Text(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "ast_hash ~ '^sha256:[0-9a-f]{64}$'", name=op.f("ck_formalization_validations_ast_hash")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(issues) = 'array'", name=op.f("ck_formalization_validations_issues_array")
        ),
        sa.CheckConstraint(
            "success = (jsonb_array_length(issues) = 0)",
            name=op.f("ck_formalization_validations_result"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "formalization_revision_id"],
            ["formalizations.workspace_id", "formalizations.id"],
            name=op.f("fk_formalization_validations_revision"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_formalization_validations")),
        sa.UniqueConstraint(
            "workspace_id",
            "formalization_revision_id",
            name=op.f("uq_formalization_validations_revision"),
        ),
    )
    op.create_table(
        "formalization_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("formalization_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ast_hash", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('CONFIRMED','REJECTED')", name=op.f("ck_formalization_decisions_kind")
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0", name=op.f("ck_formalization_decisions_reason")
        ),
        sa.CheckConstraint(
            "ast_hash ~ '^sha256:[0-9a-f]{64}$'", name=op.f("ck_formalization_decisions_ast_hash")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "formalization_revision_id"],
            ["formalizations.workspace_id", "formalizations.id"],
            name=op.f("fk_formalization_decisions_revision"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_formalization_decisions")),
        sa.UniqueConstraint(
            "workspace_id",
            "formalization_revision_id",
            name=op.f("uq_formalization_decisions_revision"),
        ),
    )

    for table in ("formalizations", "formalization_validations", "formalization_decisions"):
        _rls(table)
    op.execute("""
        CREATE FUNCTION enforce_formalization_revision() RETURNS trigger AS $$
        DECLARE source_row reasoning_artifacts%ROWTYPE; predecessor formalizations%ROWTYPE;
        BEGIN
          SELECT * INTO source_row FROM reasoning_artifacts WHERE workspace_id=NEW.workspace_id AND session_id=NEW.session_id AND id=NEW.source_artifact_id;
          IF source_row.id IS NULL OR source_row.kind NOT IN ('CLAIM','CONSTRAINT','PROPOSITION') OR source_row.logical_id<>NEW.source_artifact_logical_id OR source_row.version<>NEW.source_artifact_version THEN
            RAISE EXCEPTION 'formalization source revision mismatch' USING ERRCODE='23514';
          END IF;
          IF NEW.revision=1 THEN
            IF NEW.logical_id<>NEW.id THEN RAISE EXCEPTION 'initial logical id mismatch' USING ERRCODE='23514'; END IF;
          ELSE
            SELECT * INTO predecessor FROM formalizations WHERE workspace_id=NEW.workspace_id AND session_id=NEW.session_id AND id=NEW.supersedes_id;
            IF predecessor.id IS NULL OR predecessor.logical_id<>NEW.logical_id OR predecessor.revision<>NEW.revision-1 OR predecessor.source_artifact_logical_id<>NEW.source_artifact_logical_id THEN
              RAISE EXCEPTION 'invalid formalization revision chain' USING ERRCODE='23514';
            END IF;
          END IF;
          IF EXISTS (SELECT 1 FROM unnest(NEW.premise_artifact_ids) p LEFT JOIN reasoning_artifacts a ON a.workspace_id=NEW.workspace_id AND a.session_id=NEW.session_id AND a.id=p WHERE a.id IS NULL) THEN
            RAISE EXCEPTION 'formalization premise revision missing' USING ERRCODE='23503';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_formalization_revision AFTER INSERT ON formalizations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_formalization_revision()"
    )
    op.execute("""
        CREATE FUNCTION enforce_formalization_fact() RETURNS trigger AS $$
        DECLARE revision_hash text; passed boolean;
        BEGIN
          SELECT ast_hash INTO revision_hash FROM formalizations WHERE workspace_id=NEW.workspace_id AND id=NEW.formalization_revision_id;
          IF revision_hash IS NULL OR revision_hash<>NEW.ast_hash THEN RAISE EXCEPTION 'formalization fact AST hash mismatch' USING ERRCODE='23514'; END IF;
          IF TG_TABLE_NAME='formalization_decisions'
             AND (to_jsonb(NEW) ->> 'kind')='CONFIRMED' THEN
            SELECT success INTO passed FROM formalization_validations WHERE workspace_id=NEW.workspace_id AND formalization_revision_id=NEW.formalization_revision_id;
            IF passed IS DISTINCT FROM true THEN RAISE EXCEPTION 'confirmation requires successful validation' USING ERRCODE='23514'; END IF;
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
    """)
    for table in ("formalization_validations", "formalization_decisions"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER trg_{table}_fact AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION enforce_formalization_fact()"
        )
    op.execute("""
        CREATE FUNCTION reject_formalization_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'formalization records are append-only' USING ERRCODE='27000'; END; $$ LANGUAGE plpgsql;
    """)
    for table in ("formalizations", "formalization_validations", "formalization_decisions"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_formalization_mutation()"
        )
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM PUBLIC")

    op.drop_constraint(
        op.f("ck_workspace_event_outbox_type"), "workspace_event_outbox", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_workspace_event_outbox_type"),
        "workspace_event_outbox",
        "event_type IN ('SOURCE_RETRACTED','FORMALIZATION_CREATED','FORMALIZATION_REVISED','FORMALIZATION_VALIDATION_RECORDED','FORMALIZATION_CONFIRMED','FORMALIZATION_REJECTED')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_workspace_event_outbox_type"), "workspace_event_outbox", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_workspace_event_outbox_type"),
        "workspace_event_outbox",
        "event_type = 'SOURCE_RETRACTED'",
    )
    for table in ("formalization_decisions", "formalization_validations", "formalizations"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP TRIGGER IF EXISTS trg_formalization_decisions_fact ON formalization_decisions")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_formalization_validations_fact ON formalization_validations"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_formalization_revision ON formalizations")
    op.drop_table("formalization_decisions")
    op.drop_table("formalization_validations")
    op.drop_table("formalizations")
    op.execute("DROP FUNCTION enforce_formalization_fact()")
    op.execute("DROP FUNCTION reject_formalization_mutation()")
    op.execute("DROP FUNCTION enforce_formalization_revision()")
