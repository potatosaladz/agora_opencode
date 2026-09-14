"""Database transaction boundary used by session-bootstrap Temporal activities."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.db.realtime import LedgerEventPublisher
from app.db.reasoning_ledger import SqlAlchemyReasoningLedger
from app.db.session import Database
from app.db.session_lifecycle import SqlAlchemySessionLifecycleStore
from app.domain.reasoning import ActorClass
from app.domain.reasoning_ledger import LedgerAppend
from app.domain.session_bootstrap import SessionBootstrapTransition, SessionTransitionCommitter
from app.domain.session_lifecycle import SessionLifecycle, SessionTransition
from app.ports.event_bus import EventBus

__all__ = ["SqlAlchemySessionTransitionCommitter"]


class SqlAlchemySessionTransitionCommitter:
    """Commit one projection transition and ledger append in one tenant transaction."""

    def __init__(
        self,
        database: Database,
        *,
        service_actor_id: UUID,
        event_bus: EventBus | None = None,
        code_version: str = "",
    ) -> None:
        self._database = database
        self._service_actor_id = service_actor_id
        self._publisher = (
            LedgerEventPublisher(event_bus, code_version=code_version)
            if event_bus is not None
            else None
        )

    async def commit(self, command: SessionBootstrapTransition) -> SessionLifecycle:
        async with self._database.session(command.workspace_id) as session:
            ledger = SqlAlchemyReasoningLedger(session)
            lifecycle = SqlAlchemySessionLifecycleStore(session, ledger)
            result = await lifecycle.transition(
                SessionTransition(
                    source=command.source,
                    target=command.target,
                    round=command.round,
                    event=LedgerAppend(
                        id=command.event_id,
                        workspace_id=command.workspace_id,
                        session_id=command.session_id,
                        event_type=command.event_type,
                        payload_schema_version=1,
                        causation_id=command.causation_id,
                        correlation_id=command.correlation_id,
                        actor_class=ActorClass.SERVICE,
                        actor_id=self._service_actor_id,
                        round=command.round,
                        payload=_transition_payload(command),
                        recorded_at=datetime.now(UTC),
                    ),
                )
            )
        if self._publisher is not None:
            await self._publisher.publish(ledger.appended)
        return result


_COMMITTER_PORT: type[SessionTransitionCommitter] = SqlAlchemySessionTransitionCommitter


def _transition_payload(command: SessionBootstrapTransition) -> dict[str, object]:
    payload: dict[str, object] = {
        "from": command.source.value,
        "to": command.target.value,
    }
    if command.failure is not None:
        payload["failure"] = command.failure.model_dump(mode="json")
    return payload
