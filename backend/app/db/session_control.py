"""Atomic PostgreSQL lifecycle and ledger commit for workflow-interpreted controls."""

from __future__ import annotations

from app.db.realtime import LedgerEventPublisher
from app.db.reasoning_ledger import SqlAlchemyReasoningLedger
from app.db.session import Database
from app.db.session_lifecycle import SqlAlchemySessionLifecycleStore
from app.domain.reasoning import ActorClass
from app.domain.reasoning_ledger import LedgerAppend
from app.domain.session_control import (
    SessionControlTransition,
    SessionControlTransitionCommitter,
    control_event_type,
)
from app.domain.session_lifecycle import SessionLifecycle, SessionTransition
from app.ports.event_bus import EventBus

__all__ = ["SqlAlchemySessionControlTransitionCommitter"]


class SqlAlchemySessionControlTransitionCommitter:
    def __init__(
        self, database: Database, *, event_bus: EventBus | None = None, code_version: str = ""
    ) -> None:
        self._database = database
        self._publisher = (
            LedgerEventPublisher(event_bus, code_version=code_version)
            if event_bus is not None
            else None
        )

    async def commit(self, transition: SessionControlTransition) -> SessionLifecycle:
        command = transition.command
        directive = (
            command.directive.model_dump(mode="json") if command.directive is not None else None
        )
        async with self._database.session(command.workspace_id) as session:
            ledger = SqlAlchemyReasoningLedger(session)
            lifecycle = SqlAlchemySessionLifecycleStore(session, ledger)
            result = await lifecycle.transition(
                SessionTransition(
                    source=transition.source,
                    target=transition.target,
                    round=transition.round,
                    allow_same_state=transition.source is transition.target,
                    event=LedgerAppend(
                        id=command.event_id,
                        workspace_id=command.workspace_id,
                        session_id=command.session_id,
                        event_type=control_event_type(command.kind),
                        payload_schema_version=1,
                        correlation_id=command.correlation_id,
                        actor_class=ActorClass.HUMAN,
                        actor_id=command.actor_id,
                        round=transition.round,
                        payload={
                            "command_id": str(command.command_id),
                            "command": command.kind.value,
                            "from": transition.source.value,
                            "to": transition.target.value,
                            "observed_state": command.observed_state.value,
                            "reason": command.reason,
                            "directive": directive,
                            "requested_at": command.requested_at.isoformat().replace("+00:00", "Z"),
                        },
                        recorded_at=command.requested_at,
                    ),
                )
            )
        if self._publisher is not None:
            await self._publisher.publish(ledger.appended)
        return result


_COMMITTER_PORT: type[SessionControlTransitionCommitter] = (
    SqlAlchemySessionControlTransitionCommitter
)
