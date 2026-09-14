"""Add tenant-scoped LLM configuration, agent registry, and call accounting.

Revision ID: 20260905_0004
Revises: 20260904_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260905_0004"
down_revision: str | None = "20260904_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_TABLES = (
    "llm_configurations",
    "llm_credential_envelopes",
    "agent_definitions",
    "llm_call_records",
)


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
        "llm_configurations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("provider_kind", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.Column("api_version", sa.Text(), nullable=True),
        sa.Column("secret_provider", sa.Text(), nullable=False),
        sa.Column("secret_name", sa.Text(), nullable=False),
        sa.Column("secret_version", sa.Integer(), nullable=True),
        sa.Column(
            "capabilities",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "rate_limit", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "provider_kind IN ('openai_compatible', 'mock')",
            name=op.f("ck_llm_configurations_provider_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_llm_configurations_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_configurations")),
        sa.UniqueConstraint("id", "workspace_id", name="uq_llm_configurations_id_workspace"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_llm_configurations_workspace_name"),
    )
    op.create_table(
        "llm_credential_envelopes",
        sa.Column("llm_config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("credential_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_data_key", sa.LargeBinary(), nullable=False),
        sa.Column("wrapping_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("algorithm", sa.String(length=32), server_default="AES-256-GCM", nullable=False),
        sa.Column("master_key_provider", sa.Text(), nullable=False),
        sa.Column("master_key_name", sa.Text(), nullable=False),
        sa.Column("master_key_version", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "algorithm = 'AES-256-GCM'",
            name=op.f("ck_llm_credential_envelopes_algorithm"),
        ),
        sa.ForeignKeyConstraint(
            ["llm_config_id", "workspace_id"],
            ["llm_configurations.id", "llm_configurations.workspace_id"],
            name="fk_llm_credential_envelopes_config_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("llm_config_id", name=op.f("pk_llm_credential_envelopes")),
    )
    op.create_table(
        "agent_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logical_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("role_kind", sa.Text(), nullable=False),
        sa.Column(
            "objectives", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "constraints", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "knowledge_ns",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column("strategy_ref", sa.Text(), nullable=False),
        sa.Column("strategy_ver", sa.Text(), nullable=False),
        sa.Column("prompt_ref", sa.Text(), nullable=False),
        sa.Column("prompt_hash", sa.Text(), nullable=False),
        sa.Column("llm_config_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "tool_perms", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "budget", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("status", sa.Text(), server_default="DRAFT", nullable=False),
        sa.Column("superseded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("referenced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "role_kind IN ('domain_expert', 'critic', 'orchestrator', 'retriever', 'evaluator')",
            name=op.f("ck_agent_definitions_role_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'DEPRECATED', 'WITHDRAWN')",
            name=op.f("ck_agent_definitions_status"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_agent_definitions_version_positive")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_agent_definitions_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["llm_config_id", "workspace_id"],
            ["llm_configurations.id", "llm_configurations.workspace_id"],
            name="fk_agent_definitions_llm_config_workspace",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_definitions")),
        sa.UniqueConstraint("id", "workspace_id", name="uq_agent_definitions_id_workspace"),
        sa.UniqueConstraint("logical_id", "version", name="uq_agent_definitions_logical_version"),
        sa.UniqueConstraint(
            "workspace_id",
            "name",
            "version",
            name="uq_agent_definitions_workspace_name_version",
        ),
    )
    op.create_foreign_key(
        "fk_agent_definitions_superseded_workspace",
        "agent_definitions",
        "agent_definitions",
        ["superseded_by", "workspace_id"],
        ["id", "workspace_id"],
    )
    op.create_index("ix_agentdef_lookup", "agent_definitions", ["workspace_id", "domain", "status"])
    op.create_table(
        "llm_call_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_def_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("llm_config_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(18, 8), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("finish_reason", sa.Text(), nullable=False),
        sa.Column("retry_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("raw_artifact_ref", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "input_tokens >= 0", name=op.f("ck_llm_call_records_input_tokens_nonnegative")
        ),
        sa.CheckConstraint(
            "output_tokens >= 0", name=op.f("ck_llm_call_records_output_tokens_nonnegative")
        ),
        sa.CheckConstraint("cost_usd >= 0", name=op.f("ck_llm_call_records_cost_nonnegative")),
        sa.CheckConstraint("latency_ms >= 0", name=op.f("ck_llm_call_records_latency_nonnegative")),
        sa.CheckConstraint(
            "retry_attempts >= 0", name=op.f("ck_llm_call_records_retries_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_llm_call_records_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_def_id", "workspace_id"],
            ["agent_definitions.id", "agent_definitions.workspace_id"],
            name="fk_llm_call_records_agent_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["llm_config_id", "workspace_id"],
            ["llm_configurations.id", "llm_configurations.workspace_id"],
            name="fk_llm_call_records_config_workspace",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_call_records")),
    )
    op.create_index(
        "ix_llm_calls_workspace_created", "llm_call_records", ["workspace_id", "created_at"]
    )
    op.create_index("ix_llm_calls_session", "llm_call_records", ["session_id", "created_at"])

    for table in _TENANT_TABLES:
        _enable_rls(table)

    op.execute(
        """
        CREATE FUNCTION enforce_agent_definition_immutability() RETURNS trigger AS $$
        BEGIN
          IF OLD.referenced_at IS NOT NULL AND (
            NEW.id IS DISTINCT FROM OLD.id OR
            NEW.workspace_id IS DISTINCT FROM OLD.workspace_id OR
            NEW.logical_id IS DISTINCT FROM OLD.logical_id OR
            NEW.version IS DISTINCT FROM OLD.version OR
            NEW.name IS DISTINCT FROM OLD.name OR
            NEW.domain IS DISTINCT FROM OLD.domain OR
            NEW.role_kind IS DISTINCT FROM OLD.role_kind OR
            NEW.objectives IS DISTINCT FROM OLD.objectives OR
            NEW.constraints IS DISTINCT FROM OLD.constraints OR
            NEW.knowledge_ns IS DISTINCT FROM OLD.knowledge_ns OR
            NEW.strategy_ref IS DISTINCT FROM OLD.strategy_ref OR
            NEW.strategy_ver IS DISTINCT FROM OLD.strategy_ver OR
            NEW.prompt_ref IS DISTINCT FROM OLD.prompt_ref OR
            NEW.prompt_hash IS DISTINCT FROM OLD.prompt_hash OR
            NEW.llm_config_id IS DISTINCT FROM OLD.llm_config_id OR
            NEW.tool_perms IS DISTINCT FROM OLD.tool_perms OR
            NEW.budget IS DISTINCT FROM OLD.budget OR
            NEW.referenced_at IS DISTINCT FROM OLD.referenced_at OR
            NEW.created_at IS DISTINCT FROM OLD.created_at OR
            (OLD.superseded_by IS NOT NULL AND NEW.superseded_by IS DISTINCT FROM OLD.superseded_by)
          ) THEN
            RAISE EXCEPTION 'referenced agent definitions are immutable' USING ERRCODE = '27000';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agentdef_immutable
        BEFORE UPDATE ON agent_definitions
        FOR EACH ROW EXECUTE FUNCTION enforce_agent_definition_immutability();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_agentdef_immutable ON agent_definitions")
    op.execute("DROP FUNCTION IF EXISTS enforce_agent_definition_immutability()")
    op.drop_table("llm_call_records")
    op.drop_table("agent_definitions")
    op.drop_table("llm_credential_envelopes")
    op.drop_table("llm_configurations")
