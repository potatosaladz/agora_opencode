"""Add append-only Critique response requests and results.

Revision ID: 20260907_0019
Revises: 20260907_0018
Migration type: expand
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260907_0019"
down_revision: str | None = "20260907_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DISPOSITIONS = (
    "'ACCEPT', 'PARTIALLY_ACCEPT', 'REJECT_WITH_JUSTIFICATION', 'REVISE', "
    "'REQUEST_EVIDENCE', 'REQUEST_SIMULATION', 'ABSTAIN'"
)
_RESULT_STATUSES = (
    "'RESOLVED', 'UNRESOLVED', 'DISPUTED', 'REVISED', 'EVIDENCE_REQUESTED', "
    "'SIMULATION_DEFERRED', 'ABSTAINED'"
)


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_workspace_isolation ON {table} "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )


def _replace_graph_policy(*, all_artifact_sources: bool) -> None:
    response_sources = (
        "from_kind IN ('CLAIM', 'FACT', 'ASSUMPTION', 'INFERENCE', 'PROPOSITION', "
        "'EVIDENCE', 'UNCERTAINTY', 'RISK', 'IMPACT', 'OBJECTIVE', 'CONSTRAINT', "
        "'ALTERNATIVE', 'POSITION', 'CRITIQUE')"
        if all_artifact_sources
        else "from_kind IN ('POSITION', 'CLAIM')"
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION graph_edge_endpoint_pair_allowed(
          edge_value text,
          from_kind text,
          to_kind text
        ) RETURNS boolean AS $$
          SELECT CASE edge_value
            WHEN 'SUPPORTS' THEN from_kind IN ('EVIDENCE', 'CLAIM') AND to_kind = 'CLAIM'
            WHEN 'OPPOSES' THEN from_kind IN ('EVIDENCE', 'CLAIM') AND to_kind = 'CLAIM'
            WHEN 'CONTRADICTS' THEN from_kind = 'CLAIM' AND to_kind = 'CLAIM'
            WHEN 'DERIVED_FROM' THEN
              from_kind = 'CLAIM' AND to_kind IN ('CLAIM', 'ASSUMPTION', 'FACT')
            WHEN 'BASED_ON_ASSUMPTION' THEN
              from_kind IN ('CLAIM', 'ALTERNATIVE') AND to_kind = 'ASSUMPTION'
            WHEN 'FORMALIZES' THEN from_kind = 'PROPOSITION' AND to_kind = 'CLAIM'
            WHEN 'QUANTIFIES' THEN from_kind = 'UNCERTAINTY'
            WHEN 'IMPACTS' THEN from_kind = 'ALTERNATIVE' AND to_kind = 'OBJECTIVE'
            WHEN 'CONSTRAINS' THEN
              from_kind = 'CONSTRAINT' AND to_kind IN ('ALTERNATIVE', 'OBJECTIVE')
            WHEN 'VIOLATES' THEN from_kind = 'ALTERNATIVE' AND to_kind = 'CONSTRAINT'
            WHEN 'SATISFIES' THEN from_kind = 'ALTERNATIVE' AND to_kind = 'CONSTRAINT'
            WHEN 'INFEASIBLE_UNKNOWN' THEN
              from_kind = 'ALTERNATIVE' AND to_kind = 'CONSTRAINT'
            WHEN 'ATTACKS' THEN from_kind = 'CRITIQUE'
            WHEN 'RESPONDS_TO' THEN {response_sources} AND to_kind = 'CRITIQUE'
            WHEN 'SUPERSEDES' THEN from_kind = to_kind
            WHEN 'ADVOCATES' THEN from_kind = 'POSITION' AND to_kind = 'ALTERNATIVE'
            ELSE false
          END;
        $$ LANGUAGE sql IMMUTABLE PARALLEL SAFE;
        """
    )


def upgrade() -> None:
    op.create_table(
        "critique_response_requests",
        sa.Column("response_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("responding_definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("responding_definition_version", sa.Integer(), nullable=False),
        sa.Column("critique_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("critique_version", sa.Integer(), nullable=False),
        sa.Column("target_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_artifact_version", sa.Integer(), nullable=False),
        sa.Column("disposition", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("execution_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "responding_definition_version > 0",
            name=op.f("ck_critique_response_requests_definition_version_positive"),
        ),
        sa.CheckConstraint(
            "critique_version > 0",
            name=op.f("ck_critique_response_requests_critique_version_positive"),
        ),
        sa.CheckConstraint(
            "target_artifact_version > 0",
            name=op.f("ck_critique_response_requests_target_version_positive"),
        ),
        sa.CheckConstraint(
            f"disposition IN ({_DISPOSITIONS})",
            name=op.f("ck_critique_response_requests_disposition"),
        ),
        sa.CheckConstraint(
            "request_hash ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_critique_response_requests_request_hash_format"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(request_payload) = 'object'",
            name=op.f("ck_critique_response_requests_request_payload_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(execution_metadata) = 'object'",
            name=op.f("ck_critique_response_requests_execution_metadata_object"),
        ),
        sa.CheckConstraint(
            "schema_version = 1", name=op.f("ck_critique_response_requests_schema_version")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_critique_response_requests_session_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "critique_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_critique_response_requests_critique_workspace_session",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "target_artifact_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_critique_response_requests_target_workspace_session",
        ),
        sa.ForeignKeyConstraint(
            ["responding_definition_id", "workspace_id"],
            ["agent_definitions.id", "agent_definitions.workspace_id"],
            name="fk_critique_response_requests_definition_workspace",
        ),
        sa.PrimaryKeyConstraint("response_id", name=op.f("pk_critique_response_requests")),
        sa.UniqueConstraint(
            "workspace_id", "session_id", "response_id", name="uq_critique_response_requests_scope"
        ),
    )
    op.create_index(
        "ix_critique_response_requests_session_critique",
        "critique_response_requests",
        ["workspace_id", "session_id", "critique_id", "requested_at"],
    )
    op.create_table(
        "critique_response_results",
        sa.Column("response_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("disposition", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("critique_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("critique_revision_version", sa.Integer(), nullable=False),
        sa.Column("target_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_revision_version", sa.Integer(), nullable=True),
        sa.Column("response_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            f"status IN ({_RESULT_STATUSES})",
            name=op.f("ck_critique_response_results_status"),
        ),
        sa.CheckConstraint(
            f"disposition IN ({_DISPOSITIONS})",
            name=op.f("ck_critique_response_results_disposition"),
        ),
        sa.CheckConstraint(
            "resolution IN ('RESOLVED', 'UNRESOLVED', 'DISPUTED')",
            name=op.f("ck_critique_response_results_resolution"),
        ),
        sa.CheckConstraint(
            "critique_revision_version > 1",
            name=op.f("ck_critique_response_results_critique_version_revision"),
        ),
        sa.CheckConstraint(
            "(target_revision_id IS NULL AND target_revision_version IS NULL) OR "
            "(target_revision_id IS NOT NULL AND target_revision_version > 1)",
            name=op.f("ck_critique_response_results_target_revision_shape"),
        ),
        sa.CheckConstraint(
            "(disposition = 'REVISE') = (target_revision_id IS NOT NULL)",
            name=op.f("ck_critique_response_results_revise_target_required"),
        ),
        sa.CheckConstraint(
            "(disposition = 'ACCEPT' AND status = 'RESOLVED' AND resolution = 'RESOLVED') OR "
            "(disposition = 'PARTIALLY_ACCEPT' AND status = 'UNRESOLVED' "
            "AND resolution = 'UNRESOLVED') OR "
            "(disposition = 'REJECT_WITH_JUSTIFICATION' AND status = 'DISPUTED' "
            "AND resolution = 'DISPUTED') OR "
            "(disposition = 'REVISE' AND status = 'REVISED' AND resolution = 'RESOLVED') OR "
            "(disposition = 'REQUEST_EVIDENCE' AND status = 'EVIDENCE_REQUESTED' "
            "AND resolution = 'UNRESOLVED') OR "
            "(disposition = 'REQUEST_SIMULATION' AND status = 'SIMULATION_DEFERRED' "
            "AND resolution = 'UNRESOLVED') OR "
            "(disposition = 'ABSTAIN' AND status = 'ABSTAINED' "
            "AND resolution = 'UNRESOLVED')",
            name=op.f("ck_critique_response_results_disposition_outcome"),
        ),
        sa.CheckConstraint(
            "schema_version = 1", name=op.f("ck_critique_response_results_schema_version")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_critique_response_results_session_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "response_id"],
            [
                "critique_response_requests.workspace_id",
                "critique_response_requests.session_id",
                "critique_response_requests.response_id",
            ],
            name="fk_critique_response_results_request_scope",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "critique_revision_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_critique_response_results_critique_workspace_session",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "target_revision_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_critique_response_results_target_workspace_session",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "response_event_id"],
            ["reasoning_events.workspace_id", "reasoning_events.session_id", "reasoning_events.id"],
            name="fk_critique_response_results_event_workspace_session",
        ),
        sa.PrimaryKeyConstraint("response_id", name=op.f("pk_critique_response_results")),
    )
    op.create_index(
        "ix_critique_response_results_session_committed",
        "critique_response_results",
        ["workspace_id", "session_id", "committed_at"],
    )
    for table in ("critique_response_requests", "critique_response_results"):
        _enable_rls(table)
        op.execute(
            f"""
            CREATE FUNCTION reject_{table}_mutation() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION '{table} are append-only' USING ERRCODE = '27000';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION reject_{table}_mutation()"
        )
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM PUBLIC")
    _replace_graph_policy(all_artifact_sources=True)


def downgrade() -> None:
    _replace_graph_policy(all_artifact_sources=False)
    for table in ("critique_response_results", "critique_response_requests"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS reject_{table}_mutation()")
        op.drop_table(table)