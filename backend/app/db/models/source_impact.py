"""Tenant-safe durable source-impact and workspace outbox rows."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = [
    "ConsensusExplanationRow",
    "ConsensusResultRow",
    "ImpactReportRow",
    "RecommendationRow",
    "WorkspaceEventOutboxRow",
]


class ConsensusResultRow(Base):
    __tablename__ = "consensus_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_consensus_results_session",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "selected_alternative_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_consensus_results_selected_alternative",
            ondelete="RESTRICT",
        ),
        CheckConstraint("round >= 1", name="round"),
        CheckConstraint(
            "outcome IN ('FULL_CONSENSUS','PARTIAL_CONSENSUS','CONDITIONAL_CONSENSUS',"
            "'PARETO_SET','NO_CONSENSUS','DEADLOCK','INSUFFICIENT_EVIDENCE','INFEASIBLE')",
            name="outcome",
        ),
        CheckConstraint(
            "selected_alternative_id IS NULL OR outcome IN "
            "('FULL_CONSENSUS','PARTIAL_CONSENSUS','CONDITIONAL_CONSENSUS')",
            name="selection_feasible",
        ),
        CheckConstraint("input_hash ~ '^sha256:[0-9a-f]{64}$'", name="input_hash"),
        UniqueConstraint("workspace_id", "id", name="uq_consensus_results_workspace_id"),
        UniqueConstraint(
            "session_id",
            "round",
            "strategy",
            "strategy_version",
            name="uq_consensus_results_session_strategy",
        ),
        Index(
            "ix_consensus_results_selected_alternative", "workspace_id", "selected_alternative_id"
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_version: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    selected_alternative_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    pareto_set: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), nullable=False)
    support: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    dissent: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    abstention: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    coverage: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    constraint_report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    conditions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecommendationRow(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_recommendations_session",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "consensus_id"],
            ["consensus_results.workspace_id", "consensus_results.id"],
            name="fk_recommendations_consensus",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "alternative_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_recommendations_alternative",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["override_by", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name="fk_recommendations_override_actor",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_recommendations_workspace_id"),
        UniqueConstraint("consensus_id", "rank", name="uq_recommendations_rank"),
        CheckConstraint("rank >= 1", name="rank"),
        CheckConstraint(
            "is_override OR (override_by IS NULL AND override_reason IS NULL)",
            name="override_labelled",
        ),
        Index("ix_recommendations_alternative", "workspace_id", "alternative_id"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    consensus_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    alternative_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    conditions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    risks: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), nullable=False)
    open_questions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    is_override: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    override_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    override_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConsensusExplanationRow(Base):
    __tablename__ = "consensus_explanations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "consensus_id"],
            ["consensus_results.workspace_id", "consensus_results.id"],
            name="fk_consensus_explanations_consensus",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_consensus_explanations_workspace_id"),
        UniqueConstraint("consensus_id", name="uq_consensus_explanations_consensus"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    consensus_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ImpactReportRow(Base):
    __tablename__ = "impact_reports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_impact_reports_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "retraction_id"],
            ["source_retractions.workspace_id", "source_retractions.id"],
            name="fk_impact_reports_retraction",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_id", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name="fk_impact_reports_actor",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(btrim(reason)) > 0", name="reason"),
        CheckConstraint("analysis_status IN ('COMPLETE','INCOMPLETE')", name="analysis_status"),
        CheckConstraint("complete = (analysis_status = 'COMPLETE')", name="complete"),
        CheckConstraint("truncated = NOT complete", name="truncated"),
        UniqueConstraint("workspace_id", "id", name="uq_impact_reports_workspace_id"),
        UniqueConstraint("workspace_id", "source_id", name="uq_impact_reports_source"),
        UniqueConstraint("workspace_id", "retraction_id", name="uq_impact_reports_retraction"),
        UniqueConstraint("workspace_id", "event_id", name="uq_impact_reports_event"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    retraction_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    analysis_status: Mapped[str] = mapped_column(Text, nullable=False)
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class ImpactReportDependencyRow(Base):
    __tablename__ = "impact_report_dependencies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "report_id"],
            ["impact_reports.workspace_id", "impact_reports.id"],
            name="fk_impact_report_dependencies_report",
            ondelete="RESTRICT",
        ),
        PrimaryKeyConstraint(
            "report_id",
            "dependency_type",
            "dependent_id",
            "root_evidence_id",
            name="pk_impact_report_dependencies",
        ),
        CheckConstraint(
            "dependency_type IN ('ARTIFACT','CONSENSUS_RESULT','RECOMMENDATION')", name="type"
        ),
        CheckConstraint("min_depth >= 0", name="depth"),
        CheckConstraint("path_count >= 1", name="paths"),
        CheckConstraint("evidence_weight >= 0", name="weight"),
        CheckConstraint(
            "(dependency_type = 'ARTIFACT') = "
            "(artifact_kind IS NOT NULL AND logical_id IS NOT NULL "
            "AND artifact_version IS NOT NULL)",
            name="artifact_snapshot",
        ),
    )
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    report_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    dependency_type: Mapped[str] = mapped_column(Text, nullable=False)
    dependent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    root_evidence_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    artifact_kind: Mapped[str | None] = mapped_column(Text)
    logical_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    artifact_version: Mapped[int | None] = mapped_column(Integer)
    min_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    path_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    evidence_weight: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)


class WorkspaceEventOutboxRow(Base):
    __tablename__ = "workspace_event_outbox"
    __table_args__ = (
        ForeignKeyConstraint(
            ["actor_id", "workspace_id"],
            ["workspace_members.user_id", "workspace_members.workspace_id"],
            name="fk_workspace_event_outbox_actor",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "event_type IN ('SOURCE_RETRACTED','FORMALIZATION_CREATED','FORMALIZATION_REVISED',"
            "'FORMALIZATION_VALIDATION_RECORDED','FORMALIZATION_CONFIRMED',"
            "'FORMALIZATION_REJECTED')",
            name="type",
        ),
        CheckConstraint("payload_schema_version = 1", name="schema"),
        UniqueConstraint("workspace_id", "id", name="uq_workspace_event_outbox_workspace_id"),
        Index(
            "ix_workspace_event_outbox_unpublished",
            "recorded_at",
            "id",
            postgresql_where=text("published_at IS NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
