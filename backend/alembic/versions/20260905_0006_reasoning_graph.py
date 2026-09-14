"""Add the tenant-safe Phase 3 reasoning-graph projection.

Revision ID: 20260905_0006
Revises: 20260905_0005
Migration type: expand
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260905_0006"
down_revision: str | None = "20260905_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ARTIFACT_KINDS = (
    "'CLAIM', 'FACT', 'ASSUMPTION', 'INFERENCE', 'PROPOSITION', 'EVIDENCE', "
    "'UNCERTAINTY', 'RISK', 'IMPACT', 'OBJECTIVE', 'CONSTRAINT', 'ALTERNATIVE', "
    "'POSITION', 'CRITIQUE'"
)
_EDGE_TYPES = (
    "'SUPPORTS', 'OPPOSES', 'CONTRADICTS', 'DERIVED_FROM', 'BASED_ON_ASSUMPTION', "
    "'FORMALIZES', 'QUANTIFIES', 'IMPACTS', 'CONSTRAINS', 'VIOLATES', 'SATISFIES', "
    "'INFEASIBLE_UNKNOWN', 'ATTACKS', 'RESPONDS_TO', 'SUPERSEDES', 'ADVOCATES'"
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


def _create_tables() -> None:
    op.create_table(
        "graph_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("ref_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column(
            "attrs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"kind IN ({_ARTIFACT_KINDS})", name=op.f("ck_graph_nodes_kind")),
        sa.CheckConstraint("length(btrim(label)) > 0", name=op.f("ck_graph_nodes_label_not_blank")),
        sa.CheckConstraint(
            "jsonb_typeof(attrs) = 'object'", name=op.f("ck_graph_nodes_attrs_object")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_graph_nodes_session_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "ref_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_graph_nodes_artifact_workspace_session",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_nodes")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_graph_nodes_workspace_id"),
        sa.UniqueConstraint(
            "workspace_id", "session_id", "id", name="uq_graph_nodes_workspace_session_id"
        ),
        sa.UniqueConstraint("session_id", "ref_id", name="uq_graph_nodes_session_ref"),
    )
    op.create_index(
        "ix_graph_nodes_session_kind",
        "graph_nodes",
        ["workspace_id", "session_id", "kind"],
    )

    op.create_table(
        "graph_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_node", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_node", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("edge_type", sa.Text(), nullable=False),
        sa.Column("weight", sa.Numeric(6, 5), nullable=True),
        sa.Column(
            "qualifier",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("actor_class", sa.Text(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"edge_type IN ({_EDGE_TYPES})", name=op.f("ck_graph_edges_edge_type")),
        sa.CheckConstraint(
            "weight IS NULL OR weight BETWEEN 0 AND 1",
            name=op.f("ck_graph_edges_weight_range"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(qualifier) = 'object'", name=op.f("ck_graph_edges_qualifier_object")
        ),
        sa.CheckConstraint(
            "actor_class IN ('HUMAN', 'AGENT', 'SERVICE', 'POLICY')",
            name=op.f("ck_graph_edges_actor_class"),
        ),
        sa.CheckConstraint("from_node <> to_node", name=op.f("ck_graph_edges_no_self_loop")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_graph_edges_session_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "from_node"],
            ["graph_nodes.workspace_id", "graph_nodes.session_id", "graph_nodes.id"],
            name="fk_graph_edges_from_node_workspace_session",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "session_id", "to_node"],
            ["graph_nodes.workspace_id", "graph_nodes.session_id", "graph_nodes.id"],
            name="fk_graph_edges_to_node_workspace_session",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_edges")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_graph_edges_workspace_id"),
        sa.UniqueConstraint(
            "session_id",
            "from_node",
            "to_node",
            "edge_type",
            name="uq_graph_edges_session_triple",
        ),
    )
    op.create_index("ix_graphedges_from", "graph_edges", ["from_node", "edge_type"])
    op.create_index("ix_graphedges_to", "graph_edges", ["to_node", "edge_type"])


def _create_integrity_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_graph_node_kind() RETURNS trigger AS $$
        DECLARE
          artifact_kind text;
        BEGIN
          SELECT kind INTO artifact_kind
          FROM reasoning_artifacts
          WHERE workspace_id = NEW.workspace_id
            AND session_id = NEW.session_id
            AND id = NEW.ref_id;
          IF artifact_kind IS NULL THEN
            RAISE EXCEPTION 'graph node artifact must exist in the node tenant session'
              USING ERRCODE = '23503';
          END IF;
          IF artifact_kind <> NEW.kind THEN
            RAISE EXCEPTION 'graph node kind must match referenced artifact kind'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_graph_node_kind
        AFTER INSERT OR UPDATE ON graph_nodes
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_graph_node_kind();
        """
    )
    op.execute(
        """
        CREATE FUNCTION graph_edge_endpoint_pair_allowed(
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
            WHEN 'RESPONDS_TO' THEN
              from_kind IN ('POSITION', 'CLAIM') AND to_kind = 'CRITIQUE'
            WHEN 'SUPERSEDES' THEN from_kind = to_kind
            WHEN 'ADVOCATES' THEN from_kind = 'POSITION' AND to_kind = 'ALTERNATIVE'
            ELSE false
          END;
        $$ LANGUAGE sql IMMUTABLE PARALLEL SAFE;
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_graph_edge_endpoints() RETURNS trigger AS $$
        DECLARE
          source_kind text;
          target_kind text;
        BEGIN
          SELECT kind INTO source_kind
          FROM graph_nodes
          WHERE workspace_id = NEW.workspace_id
            AND session_id = NEW.session_id
            AND id = NEW.from_node;
          SELECT kind INTO target_kind
          FROM graph_nodes
          WHERE workspace_id = NEW.workspace_id
            AND session_id = NEW.session_id
            AND id = NEW.to_node;
          IF source_kind IS NULL OR target_kind IS NULL THEN
            RAISE EXCEPTION 'graph edge endpoints must exist in the edge tenant session'
              USING ERRCODE = '23503';
          END IF;
          IF NOT graph_edge_endpoint_pair_allowed(NEW.edge_type, source_kind, target_kind) THEN
            RAISE EXCEPTION 'graph edge type is not allowed for endpoint kinds % -> %',
              source_kind, target_kind
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_graph_edge_endpoints
        AFTER INSERT OR UPDATE ON graph_edges
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_graph_edge_endpoints();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_graph_node_incident_edges() RETURNS trigger AS $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM graph_edges AS edge
            JOIN graph_nodes AS source
              ON source.workspace_id = edge.workspace_id
             AND source.session_id = edge.session_id
             AND source.id = edge.from_node
            JOIN graph_nodes AS target
              ON target.workspace_id = edge.workspace_id
             AND target.session_id = edge.session_id
             AND target.id = edge.to_node
            WHERE edge.workspace_id = NEW.workspace_id
              AND edge.session_id = NEW.session_id
              AND (edge.from_node = NEW.id OR edge.to_node = NEW.id)
              AND NOT graph_edge_endpoint_pair_allowed(
                edge.edge_type, source.kind, target.kind
              )
          ) THEN
            RAISE EXCEPTION 'graph node update invalidates an incident edge endpoint pair'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_graph_node_incident_edges
        AFTER UPDATE ON graph_nodes
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_graph_node_incident_edges();
        """
    )


def upgrade() -> None:
    _create_tables()
    _create_integrity_triggers()
    _enable_rls("graph_nodes")
    _enable_rls("graph_edges")


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_graph_node_incident_edges ON graph_nodes")
    op.execute("DROP FUNCTION enforce_graph_node_incident_edges()")
    op.execute("DROP TRIGGER trg_graph_edge_endpoints ON graph_edges")
    op.execute("DROP FUNCTION enforce_graph_edge_endpoints()")
    op.execute("DROP FUNCTION graph_edge_endpoint_pair_allowed(text, text, text)")
    op.execute("DROP TRIGGER trg_graph_node_kind ON graph_nodes")
    op.execute("DROP FUNCTION enforce_graph_node_kind()")
    op.drop_index("ix_graphedges_to", table_name="graph_edges")
    op.drop_index("ix_graphedges_from", table_name="graph_edges")
    op.drop_table("graph_edges")
    op.drop_index("ix_graph_nodes_session_kind", table_name="graph_nodes")
    op.drop_table("graph_nodes")
