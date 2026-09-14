"""Phase 1 golden replay gate for the smallest valid event stream."""

from __future__ import annotations

import json
from pathlib import Path

from app.adapters.inmemory.event_bus import InMemoryEventBus
from app.ports.event_bus import EventEnvelope
from tests.traceability import req

_FIXTURES = Path(__file__).parents[1] / "fixtures"


@req("NFR-003")
async def test_empty_session_replay_is_byte_stable() -> None:
    source = (_FIXTURES / "empty_session_events.json").read_bytes()
    expected = (_FIXTURES / "empty_session_replay.json").read_text(encoding="utf-8").rstrip() + "\n"
    events = [EventEnvelope.model_validate(value) for value in json.loads(source)]
    bus = InMemoryEventBus()

    for event in events:
        await bus.publish("agora.sessions.empty", event)

    replayed = await bus.read_from("agora.sessions.empty", 1, limit=10)
    actual = (
        json.dumps(
            [event.model_dump(mode="json") for event in replayed],
            indent=2,
            sort_keys=False,
        )
        + "\n"
    )

    assert actual == expected
