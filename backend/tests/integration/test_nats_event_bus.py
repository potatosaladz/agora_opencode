"""NATS JetStream acceptance proof for round-trip and idempotent redelivery."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest

from app.adapters.nats.event_bus import NatsJetStreamEventBus
from app.ports.event_bus import EventEnvelope
from app.ports.health import HealthStatus
from tests.traceability import req

_NATS_URL = os.getenv("TEST_NATS_URL")
_NATS_STREAM = os.getenv("TEST_NATS_STREAM", "AGORA_T108")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _NATS_URL, reason="TEST_NATS_URL is not configured"),
]


def _event() -> EventEnvelope:
    return EventEnvelope(
        event_id="019c0000-0000-7000-8000-000000000108",
        ledger_seq=108,
        type="CLAIM_PROPOSED",
        ts=datetime(2026, 9, 4, tzinfo=UTC),
        session_id="session-t108",
        actor_id="agent-t108",
        actor_class="AGENT",
        payload={"claim_id": "claim-t108"},
        code_version="t1-08-proof",
    )


@req("FR-106", "NFR-001")
async def test_publish_subscribe_redelivery_is_idempotent_by_event_id() -> None:
    assert _NATS_URL is not None
    bus = NatsJetStreamEventBus(
        _NATS_URL,
        stream=_NATS_STREAM,
        subjects=("agora.t108.>",),
        ack_wait_s=0.25,
        max_deliver=3,
    )
    try:
        await bus.connect()
        assert await bus.health() is HealthStatus.OK

        delivered_ids: list[str] = []
        applied_effects: list[str] = []
        processed_ids: set[str] = set()
        redelivered = asyncio.Event()

        async def idempotent_handler(event: EventEnvelope) -> None:
            delivered_ids.append(event.event_id)
            if event.event_id not in processed_ids:
                processed_ids.add(event.event_id)
                applied_effects.append(event.payload["claim_id"])
            if len(delivered_ids) == 1:
                raise RuntimeError("simulate a crash after applying the effect")
            redelivered.set()

        subscription = await bus.subscribe(
            "agora.t108.committed",
            "t108-workers",
            idempotent_handler,
            from_start=False,
        )
        ack = await bus.publish("agora.t108.committed", _event())

        await asyncio.wait_for(redelivered.wait(), timeout=5.0)
        assert ack.accepted is True
        assert ack.subject == "agora.t108.committed"
        assert ack.ledger_seq is not None
        assert ack.ledger_seq > 0
        assert subscription.group == "t108-workers"
        assert delivered_ids == [_event().event_id, _event().event_id]
        assert applied_effects == ["claim-t108"]
        assert processed_ids == {_event().event_id}
    finally:
        await bus.close()
    assert await bus.health() is HealthStatus.DOWN
