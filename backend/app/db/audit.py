"""PostgreSQL persistence for Phase 13 audit records (T13-02)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentDefinitionRow
from app.db.models.audit import AccessLogRow, AuditAnchorRow
from app.db.models.reasoning import SessionAgentRow
from app.db.models.source_impact import RecommendationRow
from app.domain.agent_registry import AgentRoleKind
from app.domain.audit import (
    AccessLogEntry,
    AccessLogRepository,
    AccessResult,
    AuditAction,
    AuditAnchor,
    AuditAnchorRepository,
    AuditConflictError,
    AuditResourceKind,
    SessionParticipant,
    SessionParticipantReader,
    access_cursor_decode,
    access_cursor_encode,
)
from app.domain.reasoning import ActorClass

__all__ = [
    "SqlAlchemyAccessLogRepository",
    "SqlAlchemyAuditAnchorRepository",
    "SqlAlchemySessionParticipantReader",
]


def _log_entry(row: AccessLogRow) -> AccessLogEntry:
    return AccessLogEntry(
        id=row.id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        principal_class=ActorClass(row.principal_class),
        principal_id=row.principal_id,
        resource_kind=AuditResourceKind(row.resource_kind),
        resource_id=row.resource_id,
        action=AuditAction(row.action),
        result=AccessResult(row.result),
        scope_ids=tuple(row.scope_ids),
        source_ip=row.source_ip,
        trace_id=row.trace_id,
        recorded_at=row.recorded_at,
    )


# trace: FR-807, NFR-006
class SqlAlchemyAccessLogRepository:
    """Append-only read-log persistence inside a caller-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, entry: AccessLogEntry) -> None:
        self._session.add(
            AccessLogRow(
                id=entry.id,
                workspace_id=entry.workspace_id,
                session_id=entry.session_id,
                principal_class=entry.principal_class.value,
                principal_id=entry.principal_id,
                resource_kind=entry.resource_kind.value,
                resource_id=entry.resource_id,
                action=entry.action.value,
                result=entry.result.value,
                scope_ids=list(entry.scope_ids),
                source_ip=entry.source_ip,
                trace_id=entry.trace_id,
                recorded_at=entry.recorded_at,
            )
        )
        await self._session.flush()

    async def list_for_resource(
        self,
        workspace_id: UUID,
        *,
        resource_kind: AuditResourceKind,
        resource_id: UUID,
        session_id: UUID | None = None,
        before: datetime | None = None,
        result: AccessResult | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[tuple[AccessLogEntry, ...], str | None]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        statement = select(AccessLogRow).where(
            AccessLogRow.workspace_id == workspace_id,
            AccessLogRow.resource_kind == resource_kind.value,
            AccessLogRow.resource_id == resource_id,
        )
        if session_id is not None:
            statement = statement.where(AccessLogRow.session_id == session_id)
        if before is not None:
            statement = statement.where(AccessLogRow.recorded_at < before)
        if result is not None:
            statement = statement.where(AccessLogRow.result == result.value)
        if cursor is not None:
            cursor_at, cursor_id = access_cursor_decode(cursor)
            statement = statement.where(
                or_(
                    AccessLogRow.recorded_at > cursor_at,
                    and_(
                        AccessLogRow.recorded_at == cursor_at,
                        AccessLogRow.id > cursor_id,
                    ),
                )
            )
        rows = (
            await self._session.scalars(
                statement.order_by(AccessLogRow.recorded_at, AccessLogRow.id).limit(limit + 1)
            )
        ).all()
        entries = tuple(_log_entry(row) for row in rows[:limit])
        next_cursor: str | None = None
        if len(rows) > limit and entries:
            last = entries[-1]
            next_cursor = access_cursor_encode(last.recorded_at, last.id)
        return entries, next_cursor

    async def recommendation_created_at(
        self,
        workspace_id: UUID,
        recommendation_id: UUID,
        *,
        session_id: UUID | None = None,
    ) -> datetime | None:
        statement = select(RecommendationRow.created_at).where(
            RecommendationRow.workspace_id == workspace_id,
            RecommendationRow.id == recommendation_id,
        )
        if session_id is not None:
            statement = statement.where(RecommendationRow.session_id == session_id)
        result: datetime | None = await self._session.scalar(statement)
        return result


def _anchor(row: AuditAnchorRow) -> AuditAnchor:
    return AuditAnchor(
        id=row.id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        anchor_day=row.anchor_day,
        head_seq=row.head_seq,
        head_hash=row.head_hash,
        prev_head_hash=row.prev_head_hash,
        anchor_hash=row.anchor_hash,
        anchored_at=row.anchored_at,
    )


class SqlAlchemyAuditAnchorRepository:
    """Append-or-conflict daily-anchor persistence inside a caller transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest(self, workspace_id: UUID, session_id: UUID) -> AuditAnchor | None:
        row = await self._session.scalar(
            select(AuditAnchorRow)
            .where(
                AuditAnchorRow.workspace_id == workspace_id,
                AuditAnchorRow.session_id == session_id,
            )
            .order_by(AuditAnchorRow.anchor_day.desc(), AuditAnchorRow.id.desc())
            .limit(1)
        )
        return _anchor(row) if row is not None else None

    async def all(self, workspace_id: UUID, session_id: UUID) -> tuple[AuditAnchor, ...]:
        rows = (
            await self._session.scalars(
                select(AuditAnchorRow)
                .where(
                    AuditAnchorRow.workspace_id == workspace_id,
                    AuditAnchorRow.session_id == session_id,
                )
                .order_by(AuditAnchorRow.anchor_day, AuditAnchorRow.id)
            )
        ).all()
        return tuple(_anchor(row) for row in rows)

    async def publish(self, anchor: AuditAnchor) -> AuditAnchor:
        self._session.add(
            AuditAnchorRow(
                id=anchor.id,
                workspace_id=anchor.workspace_id,
                session_id=anchor.session_id,
                anchor_day=anchor.anchor_day,
                head_seq=anchor.head_seq,
                head_hash=anchor.head_hash,
                prev_head_hash=anchor.prev_head_hash,
                anchor_hash=anchor.anchor_hash,
                anchored_at=anchor.anchored_at,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if "audit_anchors_session_day" in str(exc.orig):
                raise AuditConflictError(
                    f"anchor for session {anchor.session_id} on {anchor.anchor_day} already exists"
                ) from exc
            raise
        return anchor


class SqlAlchemySessionParticipantReader:
    """Join the versioned agent definitions bound to a session (Q3 membership)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def participants(
        self, workspace_id: UUID, session_id: UUID
    ) -> tuple[SessionParticipant, ...]:
        rows = (
            await self._session.scalars(
                select(AgentDefinitionRow)
                .join(
                    SessionAgentRow,
                    and_(
                        SessionAgentRow.agent_def_id == AgentDefinitionRow.id,
                        SessionAgentRow.workspace_id == AgentDefinitionRow.workspace_id,
                    ),
                )
                .where(
                    AgentDefinitionRow.workspace_id == workspace_id,
                    SessionAgentRow.session_id == session_id,
                )
                .order_by(AgentDefinitionRow.name, AgentDefinitionRow.id)
            )
        ).all()
        return tuple(
            SessionParticipant(
                agent_definition_id=row.id,
                logical_id=row.logical_id,
                name=row.name,
                domain=row.domain,
                role_kind=AgentRoleKind(row.role_kind),
            )
            for row in rows
        )


_ACCESS_LOG_PORT: type[AccessLogRepository] = SqlAlchemyAccessLogRepository
_ANCHORS_PORT: type[AuditAnchorRepository] = SqlAlchemyAuditAnchorRepository
_PARTICIPANTS_PORT: type[SessionParticipantReader] = SqlAlchemySessionParticipantReader
