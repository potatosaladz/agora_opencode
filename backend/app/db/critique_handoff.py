"""SQLAlchemy read model for deterministic Phase 7 Critique explanation handoffs."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import String, and_, func, select
from sqlalchemy import cast as sql_cast
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.agents import AgentDefinitionRow
from app.db.models.critique_response import CritiqueResponseRequestRow, CritiqueResponseResultRow
from app.db.models.reasoning import ReasoningArtifactRow
from app.db.models.reasoning_ledger import ReasoningEventRow
from app.domain.critique import CritiqueResponseDisposition
from app.domain.critique_handoff import (
    CritiqueExplanationEntry,
    CritiqueExplanationHandoff,
    CritiqueExplanationHandoffReader,
    CritiqueHandoffEmptyReason,
)
from app.domain.reasoning import CritiquePayload

__all__ = ["SqlAlchemyCritiqueExplanationHandoffReader"]


# trace: FR-504
class SqlAlchemyCritiqueExplanationHandoffReader:
    """Build a complete chain-head handoff from PostgreSQL authority."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def read(self, workspace_id: UUID, session_id: UUID) -> CritiqueExplanationHandoff:
        head = aliased(ReasoningArtifactRow, name="critique_head")
        root = aliased(ReasoningArtifactRow, name="critique_root")
        successor = aliased(ReasoningArtifactRow, name="critique_successor")
        creation = aliased(ReasoningEventRow, name="critique_creation")

        rows = (
            await self._session.execute(
                select(
                    head.id,
                    head.logical_id,
                    head.version,
                    head.payload,
                    creation.ledger_seq,
                    CritiqueResponseRequestRow.disposition,
                    CritiqueResponseRequestRow.request_payload,
                    CritiqueResponseResultRow.target_revision_id,
                )
                .join(
                    root,
                    and_(
                        root.workspace_id == head.workspace_id,
                        root.session_id == head.session_id,
                        root.logical_id == head.logical_id,
                        root.kind == "CRITIQUE",
                        root.version == 1,
                    ),
                )
                .outerjoin(
                    successor,
                    and_(
                        successor.workspace_id == head.workspace_id,
                        successor.session_id == head.session_id,
                        successor.logical_id == head.logical_id,
                        successor.kind == "CRITIQUE",
                        successor.version > head.version,
                    ),
                )
                .outerjoin(
                    creation,
                    and_(
                        creation.workspace_id == root.workspace_id,
                        creation.session_id == root.session_id,
                        creation.event_type == "ARTIFACT_COMMITTED",
                        creation.payload["artifact_id"].as_string() == sql_cast(root.id, String),
                        creation.payload["kind"].as_string() == "CRITIQUE",
                        creation.payload["version"].as_integer() == 1,
                    ),
                )
                .outerjoin(
                    CritiqueResponseResultRow,
                    and_(
                        CritiqueResponseResultRow.workspace_id == head.workspace_id,
                        CritiqueResponseResultRow.session_id == head.session_id,
                        CritiqueResponseResultRow.critique_revision_id == head.id,
                    ),
                )
                .outerjoin(
                    CritiqueResponseRequestRow,
                    and_(
                        CritiqueResponseRequestRow.workspace_id
                        == CritiqueResponseResultRow.workspace_id,
                        CritiqueResponseRequestRow.session_id
                        == CritiqueResponseResultRow.session_id,
                        CritiqueResponseRequestRow.response_id
                        == CritiqueResponseResultRow.response_id,
                    ),
                )
                .where(
                    head.workspace_id == workspace_id,
                    head.session_id == session_id,
                    head.kind == "CRITIQUE",
                    successor.id.is_(None),
                )
                .order_by(creation.ledger_seq, head.id)
            )
        ).all()

        entries: list[CritiqueExplanationEntry] = []
        seen_heads: set[UUID] = set()
        for row in rows:
            if row.id in seen_heads:
                raise RuntimeError("Critique handoff persistence has duplicate chain-head metadata")
            seen_heads.add(row.id)
            if row.ledger_seq is None:
                raise RuntimeError("Critique chain root has no creation ledger event")
            payload = CritiquePayload.model_validate_json(json.dumps(row.payload))
            disposition = (
                CritiqueResponseDisposition(row.disposition)
                if row.disposition is not None
                else None
            )
            request_payload = cast(dict[str, Any] | None, row.request_payload)
            warrants = (
                tuple(UUID(str(value)) for value in request_payload["warrant_artifact_ids"])
                if request_payload is not None
                else ()
            )
            entries.append(
                CritiqueExplanationEntry(
                    critique_id=row.id,
                    logical_id=row.logical_id,
                    version=row.version,
                    target_artifact_id=payload.target_id,
                    critique_type=payload.critique_type,
                    severity=payload.severity,
                    resolution=payload.resolution,
                    response_disposition=disposition,
                    warrant_artifact_ids=warrants,
                    replacement_target_artifact_id=row.target_revision_id,
                    creation_ledger_seq=row.ledger_seq,
                )
            )

        if entries:
            return CritiqueExplanationHandoff(
                workspace_id=workspace_id,
                session_id=session_id,
                entries=tuple(entries),
            )
        return CritiqueExplanationHandoff(
            workspace_id=workspace_id,
            session_id=session_id,
            entries=(),
            empty_reason=(
                CritiqueHandoffEmptyReason.COMPLETED_CRITIC_RUN_WITHOUT_CRITIQUES
                if await self._has_completed_critic_run(workspace_id, session_id)
                else CritiqueHandoffEmptyReason.NO_COMPLETED_CRITIC_RUN
            ),
        )

    async def _has_completed_critic_run(self, workspace_id: UUID, session_id: UUID) -> bool:
        completed = await self._session.scalar(
            select(func.count())
            .select_from(ReasoningEventRow)
            .join(
                AgentDefinitionRow,
                and_(
                    AgentDefinitionRow.workspace_id == ReasoningEventRow.workspace_id,
                    AgentDefinitionRow.id == ReasoningEventRow.actor_id,
                ),
            )
            .where(
                ReasoningEventRow.workspace_id == workspace_id,
                ReasoningEventRow.session_id == session_id,
                ReasoningEventRow.event_type == "AGENT_TURN_COMPLETED",
                ReasoningEventRow.actor_class == "AGENT",
                ReasoningEventRow.payload["attribution"]["phase"].as_string() == "CRITIQUE",
                AgentDefinitionRow.role_kind == "critic",
            )
        )
        return bool(completed)


_CRITIQUE_HANDOFF_READER_PORT: type[CritiqueExplanationHandoffReader] = (
    SqlAlchemyCritiqueExplanationHandoffReader
)
