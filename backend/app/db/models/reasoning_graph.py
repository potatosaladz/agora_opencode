"""Tenant-safe SQLAlchemy rows for the Phase 3 reasoning-graph projection."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["GraphEdgeRow", "GraphNodeRow"]

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


class GraphNodeRow(Base):
    """A cached graph projection that resolves to exactly one reasoning artifact."""

    __tablename__ = "graph_nodes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_graph_nodes_session_workspace",
        ),
        ForeignKeyConstraint(
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
        CheckConstraint(f"kind IN ({_ARTIFACT_KINDS})", name="kind"),
        CheckConstraint("length(btrim(label)) > 0", name="label_not_blank"),
        CheckConstraint("jsonb_typeof(attrs) = 'object'", name="attrs_object"),
        UniqueConstraint("workspace_id", "id", name="uq_graph_nodes_workspace_id"),
        UniqueConstraint(
            "workspace_id", "session_id", "id", name="uq_graph_nodes_workspace_session_id"
        ),
        UniqueConstraint("session_id", "ref_id", name="uq_graph_nodes_session_ref"),
        Index("ix_graph_nodes_session_kind", "workspace_id", "session_id", "kind"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    ref_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    attrs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GraphEdgeRow(Base):
    """A typed directed relationship between graph nodes in one tenant session."""

    __tablename__ = "graph_edges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_graph_edges_session_workspace",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "from_node"],
            ["graph_nodes.workspace_id", "graph_nodes.session_id", "graph_nodes.id"],
            name="fk_graph_edges_from_node_workspace_session",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "to_node"],
            ["graph_nodes.workspace_id", "graph_nodes.session_id", "graph_nodes.id"],
            name="fk_graph_edges_to_node_workspace_session",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(f"edge_type IN ({_EDGE_TYPES})", name="edge_type"),
        CheckConstraint("weight IS NULL OR weight BETWEEN 0 AND 1", name="weight_range"),
        CheckConstraint("jsonb_typeof(qualifier) = 'object'", name="qualifier_object"),
        CheckConstraint(
            "actor_class IN ('HUMAN', 'AGENT', 'SERVICE', 'POLICY')", name="actor_class"
        ),
        CheckConstraint("from_node <> to_node", name="no_self_loop"),
        UniqueConstraint("workspace_id", "id", name="uq_graph_edges_workspace_id"),
        UniqueConstraint(
            "session_id",
            "from_node",
            "to_node",
            "edge_type",
            name="uq_graph_edges_session_triple",
        ),
        Index("ix_graphedges_from", "from_node", "edge_type"),
        Index("ix_graphedges_to", "to_node", "edge_type"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    from_node: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    to_node: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    edge_type: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    qualifier: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    actor_class: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
