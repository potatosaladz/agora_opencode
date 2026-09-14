"""Concurrency-safe in-memory lifecycle reference adapter."""

from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import UUID

from app.domain.reasoning_ledger import ReasoningLedger
from app.domain.session_lifecycle import (
    TERMINAL_SESSION_STATES,
    InvalidSessionTransition,
    SessionLifecycle,
    SessionLifecycleState,
    SessionTransition,
    validate_session_transition,
)

__all__ = ["InMemorySessionLifecycleStore"]


class InMemorySessionLifecycleStore:
    def __init__(self, ledger: ReasoningLedger) -> None:
        self._ledger = ledger
        self._values: dict[tuple[UUID, UUID], SessionLifecycle] = {}
        self._lock = asyncio.Lock()

    async def add_draft(
        self, workspace_id: UUID, session_id: UUID, *, created_at: datetime
    ) -> SessionLifecycle:
        value = SessionLifecycle(
            workspace_id=workspace_id,
            session_id=session_id,
            created_at=created_at,
            updated_at=created_at,
        )
        async with self._lock:
            key = (workspace_id, session_id)
            if key in self._values:
                raise InvalidSessionTransition("session lifecycle already exists")
            self._values[key] = value
        return value

    async def get(self, workspace_id: UUID, session_id: UUID) -> SessionLifecycle | None:
        async with self._lock:
            return self._values.get((workspace_id, session_id))

    async def attach_workflow(
        self, workspace_id: UUID, session_id: UUID, *, workflow_id: str, run_id: str
    ) -> SessionLifecycle:
        if not workflow_id.strip() or not run_id.strip():
            raise ValueError("workflow_id and run_id must not be blank")
        async with self._lock:
            value = self._required(workspace_id, session_id)
            if value.workflow_id is not None and (value.workflow_id, value.run_id) != (
                workflow_id,
                run_id,
            ):
                raise InvalidSessionTransition(
                    "session is attached to a different workflow execution"
                )
            value = value.model_copy(update={"workflow_id": workflow_id, "run_id": run_id})
            self._values[(workspace_id, session_id)] = value
            return value

    async def transition(self, command: SessionTransition) -> SessionLifecycle:
        event = command.event
        async with self._lock:
            key = (event.workspace_id, event.session_id)
            current = self._required(*key)
            if current.state is command.target and current.last_event_id == event.id:
                await self._ledger.append(event)
                return current
            if current.state is not command.source:
                raise InvalidSessionTransition(
                    f"expected session state {command.source}, found {current.state}"
                )
            validate_session_transition(
                current.state,
                command.target,
                current_round=current.round,
                next_round=command.round,
                allow_same_state=command.allow_same_state,
            )
            await self._ledger.append(event)
            changes: dict[str, object] = {
                "state": command.target,
                "round": command.round,
                "last_event_id": event.id,
                "updated_at": event.recorded_at,
            }
            if current.state is SessionLifecycleState.DRAFT:
                changes["initialized_at"] = event.recorded_at
                changes["started_at"] = event.recorded_at
            if command.target is SessionLifecycleState.RUNNING and current.started_at is None:
                changes["started_at"] = event.recorded_at
            if command.target in TERMINAL_SESSION_STATES:
                changes["ended_at"] = event.recorded_at
            updated = current.model_copy(update=changes)
            self._values[key] = updated
            return updated

    def _required(self, workspace_id: UUID, session_id: UUID) -> SessionLifecycle:
        try:
            return self._values[(workspace_id, session_id)]
        except KeyError as exc:
            raise InvalidSessionTransition("session lifecycle does not exist") from exc
