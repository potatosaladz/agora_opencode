"""Append-only SQLAlchemy rows for Phase 7 Critique responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = ["CritiqueResponseRequestRow", "CritiqueResponseResultRow"]

_DISPOSITIONS = (
    "'ACCEPT', 'PARTIALLY_ACCEPT', 'REJECT_WITH_JUSTIFICATION', 'REVISE', "
    "'REQUEST_EVIDENCE', 'REQUEST_SIMULATION', 'ABSTAIN'"
)
_RESULT_STATUSES = (
    "'RESOLVED', 'UNRESOLVED', 'DISPUTED', 'REVISED', 'EVIDENCE_REQUESTED', "
    "'SIMULATION_DEFERRED', 'ABSTAINED'"
)
_RESOLUTIONS = "'RESOLVED', 'UNRESOLVED', 'DISPUTED'"


class CritiqueResponseRequestRow(Base):
    """Exact immutable input and execution attribution for one response identity."""

    __tablename__ = "critique_response_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_critique_response_requests_session_workspace",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "critique_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_critique_response_requests_critique_workspace_session",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "target_artifact_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_critique_response_requests_target_workspace_session",
        ),
        ForeignKeyConstraint(
            ["responding_definition_id", "workspace_id"],
            ["agent_definitions.id", "agent_definitions.workspace_id"],
            name="fk_critique_response_requests_definition_workspace",
        ),
        CheckConstraint("responding_definition_version > 0", name="definition_version_positive"),
        CheckConstraint("critique_version > 0", name="critique_version_positive"),
        CheckConstraint("target_artifact_version > 0", name="target_version_positive"),
        CheckConstraint(f"disposition IN ({_DISPOSITIONS})", name="disposition"),
        CheckConstraint("request_hash ~ '^sha256:[0-9a-f]{64}$'", name="request_hash_format"),
        CheckConstraint("jsonb_typeof(request_payload) = 'object'", name="request_payload_object"),
        CheckConstraint(
            "jsonb_typeof(execution_metadata) = 'object'", name="execution_metadata_object"
        ),
        CheckConstraint("schema_version = 1", name="schema_version"),
        UniqueConstraint(
            "workspace_id", "session_id", "response_id", name="uq_critique_response_requests_scope"
        ),
        Index(
            "ix_critique_response_requests_session_critique",
            "workspace_id",
            "session_id",
            "critique_id",
            "requested_at",
        ),
    )

    response_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    turn_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    responding_definition_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    responding_definition_version: Mapped[int] = mapped_column(Integer, nullable=False)
    critique_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    critique_version: Mapped[int] = mapped_column(Integer, nullable=False)
    target_artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    target_artifact_version: Mapped[int] = mapped_column(Integer, nullable=False)
    disposition: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    execution_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )


class CritiqueResponseResultRow(Base):
    """Immutable committed effect census for one response request."""

    __tablename__ = "critique_response_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "session_id"],
            ["sessions.workspace_id", "sessions.id"],
            name="fk_critique_response_results_session_workspace",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "response_id"],
            [
                "critique_response_requests.workspace_id",
                "critique_response_requests.session_id",
                "critique_response_requests.response_id",
            ],
            name="fk_critique_response_results_request_scope",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "critique_revision_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_critique_response_results_critique_workspace_session",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "target_revision_id"],
            [
                "reasoning_artifacts.workspace_id",
                "reasoning_artifacts.session_id",
                "reasoning_artifacts.id",
            ],
            name="fk_critique_response_results_target_workspace_session",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "session_id", "response_event_id"],
            [
                "reasoning_events.workspace_id",
                "reasoning_events.session_id",
                "reasoning_events.id",
            ],
            name="fk_critique_response_results_event_workspace_session",
        ),
        CheckConstraint(f"status IN ({_RESULT_STATUSES})", name="status"),
        CheckConstraint(f"disposition IN ({_DISPOSITIONS})", name="disposition"),
        CheckConstraint(f"resolution IN ({_RESOLUTIONS})", name="resolution"),
        CheckConstraint("critique_revision_version > 1", name="critique_version_revision"),
        CheckConstraint(
            "(target_revision_id IS NULL AND target_revision_version IS NULL) OR "
            "(target_revision_id IS NOT NULL AND target_revision_version > 1)",
            name="target_revision_shape",
        ),
        CheckConstraint(
            "(disposition = 'REVISE') = (target_revision_id IS NOT NULL)",
            name="revise_target_required",
        ),
        CheckConstraint(
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
            name="disposition_outcome",
        ),
        CheckConstraint("schema_version = 1", name="schema_version"),
        Index(
            "ix_critique_response_results_session_committed",
            "workspace_id",
            "session_id",
            "committed_at",
        ),
    )

    response_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    disposition: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str] = mapped_column(Text, nullable=False)
    critique_revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    critique_revision_version: Mapped[int] = mapped_column(Integer, nullable=False)
    target_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    target_revision_version: Mapped[int | None] = mapped_column(Integer)
    response_event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
