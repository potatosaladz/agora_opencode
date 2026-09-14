"""Unit tests for the in-memory event-bus reference adapter."""

from datetime import UTC, datetime

import pytest

from app.adapters.inmemory.event_bus import InMemoryEventBus
from app.ports.errors import PermanentPortError
from app.ports.event_bus import EventEnvelope
from tests.traceability import req


def _event(event_id: str) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        ledger_seq=0,
        type="CLAIM_PROPOSED",
        ts=datetime(2026, 9, 4, tzinfo=UTC),
        session_id="session-1",
        actor_id="agent-1",
        actor_class="AGENT",
    )


@req("NFR-016")
async def test_read_from_replays_from_sequence_with_limit() -> None:
    bus = InMemoryEventBus()
    for event_id in ("event-1", "event-2", "event-3"):
        await bus.publish("agora.events", _event(event_id))

    replayed = await bus.read_from("agora.events", 2, limit=1)

    assert [event.event_id for event in replayed] == ["event-2"]
    assert [event.ledger_seq for event in replayed] == [2]


@req("NFR-016")
async def test_read_from_rejects_non_positive_limit() -> None:
    bus = InMemoryEventBus()

    with pytest.raises(PermanentPortError, match="limit must be positive"):
        await bus.read_from("agora.events", 1, limit=0)
