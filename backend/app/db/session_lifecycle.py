"""Lock-safe PostgreSQL lifecycle projection with atomic reasoning-ledger transitions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.session_lifecycle import SessionLifecycleRow
from app.domain.reasoning_ledger import ReasoningLedger
from app.domain.session_lifecycle import (
    TERMINAL_SESSION_STATES,
    InvalidSessionTransition,
    SessionLifecycle,
    SessionLifecycleState,
    SessionLifecycleStore,
    SessionTransition,
    validate_session_transition,
)

__all__ = ["SqlAlchemySessionLifecycleStore"]


def _projection(row: SessionLifecycleRow) -> SessionLifecycle:
    return SessionLifecycle(
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        state=SessionLifecycleState(row.state),
        round=row.round,
        workflow_id=row.workflow_id,
        run_id=row.run_id,
        last_event_id=row.last_event_id,
        initialized_at=row.initialized_at,
        started_at=row.started_at,
        ended_at=row.ended_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemySessionLifecycleStore:
    def __init__(self, session: AsyncSession, ledger: ReasoningLedger) -> None:
        self._session = session
        self._ledger = ledger

    async def add_draft(
        self, workspace_id: UUID, session_id: UUID, *, created_at: datetime
    ) -> SessionLifecycle:
        row = SessionLifecycleRow(
            workspace_id=workspace_id,
            session_id=session_id,
            state=SessionLifecycleState.DRAFT.value,
            round=0,
            created_at=created_at,
            updated_at=created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return _projection(row)

    async def get(self, workspace_id: UUID, session_id: UUID) -> SessionLifecycle | None:
        row = await self._row(workspace_id, session_id, lock=False)
        return _projection(row) if row is not None else None

    async def attach_workflow(
        self, workspace_id: UUID, session_id: UUID, *, workflow_id: str, run_id: str
    ) -> SessionLifecycle:
        if not workflow_id.strip() or not run_id.strip():
            raise ValueError("workflow_id and run_id must not be blank")
        row = await self._required_row(workspace_id, session_id)
        if row.workflow_id is not None:
            if (row.workflow_id, row.run_id) != (workflow_id, run_id):
                raise InvalidSessionTransition(
                    "session is attached to a different workflow execution"
                )
            return _projection(row)
        row.workflow_id, row.run_id = workflow_id, run_id
        await self._session.flush()
        return _projection(row)

    async def transition(self, command: SessionTransition) -> SessionLifecycle:
        event = command.event
        row = await self._required_row(event.workspace_id, event.session_id)
        current = SessionLifecycleState(row.state)
        if current is command.target and row.last_event_id == event.id:
            await self._ledger.append(event)
            return _projection(row)
        if current is not command.source:
            raise InvalidSessionTransition(
                f"expected session state {command.source}, found {current}"
            )
        validate_session_transition(
            current,
            command.target,
            current_round=row.round,
            next_round=command.round,
            allow_same_state=command.allow_same_state,
        )
        await self._ledger.append(event)
        row.state = command.target.value
        row.round = command.round
        row.last_event_id = event.id
        row.updated_at = event.recorded_at
        if current is SessionLifecycleState.DRAFT:
            row.initialized_at = event.recorded_at
            row.started_at = event.recorded_at
        if command.target is SessionLifecycleState.RUNNING and row.started_at is None:
            row.started_at = event.recorded_at
        if command.target in TERMINAL_SESSION_STATES:
            row.ended_at = event.recorded_at
        await self._session.flush()
        return _projection(row)

    async def _required_row(self, workspace_id: UUID, session_id: UUID) -> SessionLifecycleRow:
        row = await self._row(workspace_id, session_id, lock=True)
        if row is None:
            raise InvalidSessionTransition(
                f"session {session_id} has no lifecycle in workspace {workspace_id}"
            )
        return row

    async def _row(
        self, workspace_id: UUID, session_id: UUID, *, lock: bool
    ) -> SessionLifecycleRow | None:
        statement = select(SessionLifecycleRow).where(
            SessionLifecycleRow.workspace_id == workspace_id,
            SessionLifecycleRow.session_id == session_id,
        )
        if lock:
            statement = statement.with_for_update()
        result: SessionLifecycleRow | None = await self._session.scalar(statement)
        return result


_LIFECYCLE_PORT: type[SessionLifecycleStore] = SqlAlchemySessionLifecycleStore
