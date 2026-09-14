"""SQLAlchemy implementation of append-only Phase 7 Critique response persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.critique_response import CritiqueResponseRequestRow, CritiqueResponseResultRow
from app.domain.critique import (
    CritiqueResponseDisposition,
    CritiqueResponseRequest,
    CritiqueResponseResult,
    CritiqueResponseResultStatus,
    CritiqueResponseStore,
)
from app.domain.reasoning import Resolution

__all__ = ["SqlAlchemyCritiqueResponseStore"]


# trace: FR-503
def _request_from_row(row: CritiqueResponseRequestRow) -> CritiqueResponseRequest:
    return CritiqueResponseRequest(
        response_id=row.response_id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        turn_id=row.turn_id,
        responding_definition_id=row.responding_definition_id,
        responding_definition_version=row.responding_definition_version,
        critique_id=row.critique_id,
        critique_version=row.critique_version,
        target_artifact_id=row.target_artifact_id,
        target_artifact_version=row.target_artifact_version,
        disposition=CritiqueResponseDisposition(row.disposition),
        request_hash=row.request_hash,
        request_payload=row.request_payload,
        execution_metadata=row.execution_metadata,
        requested_at=row.requested_at,
        schema_version=row.schema_version,
    )


def _result_from_row(row: CritiqueResponseResultRow) -> CritiqueResponseResult:
    return CritiqueResponseResult(
        response_id=row.response_id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        status=CritiqueResponseResultStatus(row.status),
        disposition=CritiqueResponseDisposition(row.disposition),
        resolution=Resolution(row.resolution),
        critique_revision_id=row.critique_revision_id,
        critique_revision_version=row.critique_revision_version,
        target_revision_id=row.target_revision_id,
        target_revision_version=row.target_revision_version,
        response_event_id=row.response_event_id,
        committed_at=row.committed_at,
        schema_version=row.schema_version,
    )


class SqlAlchemyCritiqueResponseStore:
    """Flush response request/result rows without committing the caller transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_response(self, workspace_id: UUID, session_id: UUID, response_id: UUID) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {"identity": f"critique-response:{workspace_id}:{session_id}:{response_id}"},
        )

    async def get_request(
        self, workspace_id: UUID, session_id: UUID, response_id: UUID
    ) -> CritiqueResponseRequest | None:
        row = await self._session.scalar(
            select(CritiqueResponseRequestRow).where(
                CritiqueResponseRequestRow.workspace_id == workspace_id,
                CritiqueResponseRequestRow.session_id == session_id,
                CritiqueResponseRequestRow.response_id == response_id,
            )
        )
        return _request_from_row(row) if row is not None else None

    async def get_result(
        self, workspace_id: UUID, session_id: UUID, response_id: UUID
    ) -> CritiqueResponseResult | None:
        row = await self._session.scalar(
            select(CritiqueResponseResultRow).where(
                CritiqueResponseResultRow.workspace_id == workspace_id,
                CritiqueResponseResultRow.session_id == session_id,
                CritiqueResponseResultRow.response_id == response_id,
            )
        )
        return _result_from_row(row) if row is not None else None

    async def add_request(self, request: CritiqueResponseRequest) -> None:
        self._session.add(
            CritiqueResponseRequestRow(
                response_id=request.response_id,
                workspace_id=request.workspace_id,
                session_id=request.session_id,
                turn_id=request.turn_id,
                responding_definition_id=request.responding_definition_id,
                responding_definition_version=request.responding_definition_version,
                critique_id=request.critique_id,
                critique_version=request.critique_version,
                target_artifact_id=request.target_artifact_id,
                target_artifact_version=request.target_artifact_version,
                disposition=request.disposition.value,
                request_hash=request.request_hash,
                request_payload=dict(request.request_payload),
                execution_metadata=dict(request.execution_metadata),
                requested_at=request.requested_at,
                schema_version=request.schema_version,
            )
        )
        await self._session.flush()

    async def add_result(self, result: CritiqueResponseResult) -> None:
        self._session.add(
            CritiqueResponseResultRow(
                response_id=result.response_id,
                workspace_id=result.workspace_id,
                session_id=result.session_id,
                status=result.status.value,
                disposition=result.disposition.value,
                resolution=result.resolution.value,
                critique_revision_id=result.critique_revision_id,
                critique_revision_version=result.critique_revision_version,
                target_revision_id=result.target_revision_id,
                target_revision_version=result.target_revision_version,
                response_event_id=result.response_event_id,
                committed_at=result.committed_at,
                schema_version=result.schema_version,
            )
        )
        await self._session.flush()


_CRITIQUE_RESPONSE_STORE_PORT: type[CritiqueResponseStore] = SqlAlchemyCritiqueResponseStore
