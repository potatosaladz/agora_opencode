"""PostgreSQL-authoritative realtime publication and SSE delivery adapter."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Sequence
from uuid import UUID

from app.db.reasoning_ledger import SqlAlchemyReasoningLedger
from app.db.session import Database
from app.db.session_lifecycle import SqlAlchemySessionLifecycleStore
from app.domain.reasoning_ledger import LedgerEvent
from app.domain.session_lifecycle import TERMINAL_SESSION_STATES
from app.ports.event_bus import EventBus, EventEnvelope

__all__ = [
    "LedgerEventPublisher",
    "RealtimeGateway",
    "event_envelope",
    "session_event_subject",
]

_LOG = logging.getLogger("agora.db.realtime")


def session_event_subject(workspace_id: UUID, session_id: UUID) -> str:
    return f"session.{workspace_id}.{session_id}.committed"


def event_envelope(event: LedgerEvent, *, code_version: str) -> EventEnvelope:
    return EventEnvelope(
        event_id=str(event.id),
        ledger_seq=event.ledger_seq,
        type=event.event_type,
        ts=event.recorded_at,
        session_id=str(event.session_id),
        actor_id=str(event.actor_id),
        actor_class=event.actor_class.value,
        round=event.round,
        payload={
            key: value
            for key, value in event.payload.items()
            if key.endswith("_id") or key.endswith("_ids")
        },
        schema_version=event.payload_schema_version,
        code_version=code_version,
    )


class LedgerEventPublisher:
    """Publish committed rows without making transport part of commit authority."""

    def __init__(self, event_bus: EventBus, *, code_version: str) -> None:
        self._event_bus = event_bus
        self._code_version = code_version

    async def publish(self, events: Sequence[LedgerEvent]) -> None:
        for event in events:
            try:
                await self._event_bus.publish(
                    session_event_subject(event.workspace_id, event.session_id),
                    event_envelope(event, code_version=self._code_version),
                )
            except Exception as exc:
                _LOG.warning(
                    "committed_event_publish_failed",
                    extra={
                        "event_id": str(event.id),
                        "ledger_seq": event.ledger_seq,
                        "error_type": type(exc).__name__,
                    },
                )


class RealtimeGateway:
    """Use NATS only as a wake-up; replay and ordering always come from PostgreSQL."""

    def __init__(self, database: Database, event_bus: EventBus, *, code_version: str) -> None:
        self._database = database
        self._event_bus = event_bus
        self._code_version = code_version
        self._wakeups: dict[UUID, set[asyncio.Event]] = {}

    async def start(self) -> None:
        await self._event_bus.subscribe(
            "session.*.*.committed",
            f"realtime-{id(self)}",
            self._wake,
            from_start=False,
        )

    async def _wake(self, event: EventEnvelope) -> None:
        try:
            session_id = UUID(event.session_id)
        except ValueError:
            return
        for wakeup in self._wakeups.get(session_id, ()):
            wakeup.set()

    async def stream(
        self,
        workspace_id: UUID,
        session_id: UUID,
        *,
        after: int = 0,
        heartbeat_s: float = 15.0,
    ) -> AsyncIterator[bytes]:
        if after < 0:
            raise ValueError("after must not be negative")
        next_seq = after + 1
        wakeup = asyncio.Event()
        self._wakeups.setdefault(session_id, set()).add(wakeup)
        try:
            while True:
                wakeup.clear()
                events, terminal = await self._read(workspace_id, session_id, next_seq)
                for event in events:
                    next_seq = event.ledger_seq + 1
                    yield _sse(event_envelope(event, code_version=self._code_version))
                if events:
                    continue
                if terminal:
                    return
                try:
                    await asyncio.wait_for(wakeup.wait(), timeout=heartbeat_s)
                except TimeoutError:
                    yield b": keep-alive\n\n"
        finally:
            listeners = self._wakeups.get(session_id)
            if listeners is not None:
                listeners.discard(wakeup)
                if not listeners:
                    self._wakeups.pop(session_id, None)

    async def _read(
        self, workspace_id: UUID, session_id: UUID, from_seq: int
    ) -> tuple[Sequence[LedgerEvent], bool]:
        async with self._database.session(workspace_id) as session:
            ledger = SqlAlchemyReasoningLedger(session)
            lifecycle = await SqlAlchemySessionLifecycleStore(session, ledger).get(
                workspace_id, session_id
            )
            events = await ledger.read(workspace_id, session_id, from_seq=from_seq, limit=250)
            terminal = lifecycle is not None and lifecycle.state in TERMINAL_SESSION_STATES
            return events, terminal


def _sse(event: EventEnvelope) -> bytes:
    data = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
    return f"id: {event.ledger_seq}\nevent: {event.type}\ndata: {data}\n\n".encode()
