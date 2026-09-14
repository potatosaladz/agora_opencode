"""Add durable source-impact reports, dependency snapshots, and workspace outbox.

Revision ID: 20260911_0021
Revises: 20260909_0020
Migration type: expand
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260911_0021"
down_revision: str | None = "20260909_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_workspace_isolation ON {table} "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = "
        "NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )


# trace: FR-408
def upgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_source_retractions_workspace_id"),
        "source_retractions",
        ["workspace_id", "id"],
    )
    op.create_table(
        "consensus_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("strategy", sa.Text(), nullable=False),
        sa.Column("strategy_version", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("selected_alternative_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pareto_set", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False),
        sa.Column("support", sa.Numeric(6, 5), nullable=True),
        sa.Column("dissent", sa.Numeric(6, 5), nullable=True),
        sa.Column("abstention", sa.Numeric(6, 5), nullable=True),
        sa.Column("coverage", sa.Numeric(6, 5), nullable=True),
        sa.Column("constraint_report", postgresql.JSONB(), nullable=False),
        sa.Column("conditions", postgresql.JSONB(), nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('FULL_CONSENSUS','PARTIAL_CONSENSUS','CONDITIONAL_CONSENSUS',"
            "'PARETO_SET','NO_CONSENSUS','DEADLOCK','INSUFFICIENT_EVIDENCE','INFEASIBLE')",
            name=op.f("ck_consensus_results_outcome"),
        ),
        sa.CheckConstraint("round >= 1", name=op.f("ck_consensus_results_round")),
        sa.CheckConstraint(
            "selected_alternative_id IS NULL OR outcome IN "
            "('FULL_CONSENSUS','PARTIAL_CONSENSUS','CONDITIONAL_CONSENSUS')",
            name=op.f("ck_consensus_results_selection_feasible"),
        ),
        sa.CheckConstraint(
            "input_hash ~ '^sha256:[0-9a-f]{64}$'", name=op.f("ck_consensus_results_input_hash")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name=op.f("fk_consensus_results_session"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "selected_alternative_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name=op.f("fk_consensus_results_selected_alternative"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consensus_results")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_consensus_results_workspace_id")),
        sa.UniqueConstraint(
            "session_id",
            "round",
            "strategy",
            "strategy_version",
            name=op.f("uq_consensus_results_session_strategy"),
        ),
    )
    op.create_index(
        "ix_consensus_results_selected_alternative",
        "consensus_results",
        ["workspace_id", "selected_alternative_id"],
    )

    op.create_table(
        "consensus_explanations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consensus_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("explanation", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "consensus_id"],
            ["consensus_results.workspace_id", "consensus_results.id"],
            name=op.f("fk_consensus_explanations_consensus"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consensus_explanations")),
        sa.UniqueConstraint(
            "workspace_id", "id", name=op.f("uq_consensus_explanations_workspace_id")
        ),
        sa.UniqueConstraint("consensus_id", name=op.f("uq_consensus_explanations_consensus")),
    )

    op.create_table(
        "recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consensus_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alternative_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("conditions", postgresql.JSONB(), nullable=False),
        sa.Column("risks", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False),
        sa.Column("open_questions", postgresql.JSONB(), nullable=False),
        sa.Column("is_override", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("override_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rank >= 1", name=op.f("ck_recommendations_rank")),
        sa.CheckConstraint(
            "is_override OR (override_by IS NULL AND override_reason IS NULL)",
            name=op.f("ck_recommendations_override_labelled"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name=op.f("fk_recommendations_session"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "consensus_id"],
            ["consensus_results.workspace_id", "consensus_results.id"],
            name=op.f("fk_recommendations_consensus"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "alternative_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name=op.f("fk_recommendations_alternative"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["override_by", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name=op.f("fk_recommendations_override_actor"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendations")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_recommendations_workspace_id")),
        sa.UniqueConstraint("consensus_id", "rank", name=op.f("uq_recommendations_rank")),
    )
    op.create_index(
        "ix_recommendations_alternative", "recommendations", ["workspace_id", "alternative_id"]
    )

    op.create_table(
        "impact_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retraction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analysis_status", sa.Text(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint("length(btrim(reason)) > 0", name=op.f("ck_impact_reports_reason")),
        sa.CheckConstraint(
            "analysis_status IN ('COMPLETE','INCOMPLETE')",
            name=op.f("ck_impact_reports_analysis_status"),
        ),
        sa.CheckConstraint(
            "complete = (analysis_status = 'COMPLETE')",
            name=op.f("ck_impact_reports_complete"),
        ),
        sa.CheckConstraint(
            "truncated = NOT complete", name=op.f("ck_impact_reports_truncated")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name=op.f("fk_impact_reports_source"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "retraction_id"],
            ["source_retractions.workspace_id", "source_retractions.id"],
            name=op.f("fk_impact_reports_retraction"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name=op.f("fk_impact_reports_actor"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_impact_reports")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_impact_reports_workspace_id")),
        sa.UniqueConstraint("workspace_id", "source_id", name=op.f("uq_impact_reports_source")),
        sa.UniqueConstraint(
            "workspace_id", "retraction_id", name=op.f("uq_impact_reports_retraction")
        ),
        sa.UniqueConstraint("workspace_id", "event_id", name=op.f("uq_impact_reports_event")),
    )

    op.create_table(
        "impact_report_dependencies",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dependency_type", sa.Text(), nullable=False),
        sa.Column("dependent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("root_evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_kind", sa.Text(), nullable=True),
        sa.Column("logical_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("artifact_version", sa.Integer(), nullable=True),
        sa.Column("min_depth", sa.Integer(), nullable=False),
        sa.Column("path_count", sa.BigInteger(), nullable=False),
        sa.Column("evidence_weight", sa.Numeric(20, 10), nullable=False),
        sa.CheckConstraint(
            "dependency_type IN ('ARTIFACT','CONSENSUS_RESULT','RECOMMENDATION')",
            name=op.f("ck_impact_report_dependencies_type"),
        ),
        sa.CheckConstraint("min_depth >= 0", name=op.f("ck_impact_report_dependencies_depth")),
        sa.CheckConstraint("path_count >= 1", name=op.f("ck_impact_report_dependencies_paths")),
        sa.CheckConstraint(
            "evidence_weight >= 0", name=op.f("ck_impact_report_dependencies_weight")
        ),
        sa.CheckConstraint(
            "(dependency_type = 'ARTIFACT') = "
            "(artifact_kind IS NOT NULL AND logical_id IS NOT NULL "
            "AND artifact_version IS NOT NULL)",
            name=op.f("ck_impact_report_dependencies_artifact_snapshot"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "report_id"],
            ["impact_reports.workspace_id", "impact_reports.id"],
            name=op.f("fk_impact_report_dependencies_report"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "report_id",
            "dependency_type",
            "dependent_id",
            "root_evidence_id",
            name=op.f("pk_impact_report_dependencies"),
        ),
    )

    op.create_table(
        "workspace_event_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload_schema_version", sa.Integer(), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "event_type = 'SOURCE_RETRACTED'", name=op.f("ck_workspace_event_outbox_type")
        ),
        sa.CheckConstraint(
            "payload_schema_version = 1", name=op.f("ck_workspace_event_outbox_schema")
        ),
        sa.ForeignKeyConstraint(
            ["actor_id", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name=op.f("fk_workspace_event_outbox_actor"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_event_outbox")),
        sa.UniqueConstraint(
            "workspace_id", "id", name=op.f("uq_workspace_event_outbox_workspace_id")
        ),
    )
    op.create_index(
        "ix_workspace_event_outbox_unpublished",
        "workspace_event_outbox",
        ["recorded_at", "id"],
        postgresql_where=sa.text("published_at IS NULL"),
    )

    for table in (
        "consensus_results",
        "consensus_explanations",
        "recommendations",
        "impact_reports",
        "impact_report_dependencies",
        "workspace_event_outbox",
    ):
        _rls(table)

    op.execute(
        """
        CREATE FUNCTION reject_source_impact_fact_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'source-impact facts are append-only' USING ERRCODE = '27000';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in (
        "consensus_results",
        "consensus_explanations",
        "recommendations",
        "impact_reports",
        "impact_report_dependencies",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_source_impact_fact_mutation()"
        )
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM PUBLIC")


def downgrade() -> None:
    op.drop_table("workspace_event_outbox")
    op.drop_table("impact_report_dependencies")
    op.drop_table("impact_reports")
    op.drop_table("recommendations")
    op.drop_table("consensus_explanations")
    op.drop_table("consensus_results")
    op.execute("DROP FUNCTION reject_source_impact_fact_mutation()")
    op.drop_constraint(
        op.f("uq_source_retractions_workspace_id"),
        "source_retractions",
        type_="unique",
    )
