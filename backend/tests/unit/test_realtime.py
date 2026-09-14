"""T4-06 ledger-authoritative realtime and resume tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.db.realtime import LedgerEventPublisher, RealtimeGateway, event_envelope
from app.domain.reasoning import ActorClass
from app.domain.reasoning_ledger import LedgerEvent
from app.ports.event_bus import EventEnvelope
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 7))


def persisted(sequence: int, event_type: str = "ROUND_STARTED") -> LedgerEvent:
    return LedgerEvent(
        id=U[sequence + 2],
        workspace_id=U[0],
        session_id=U[1],
        ledger_seq=sequence,
        event_type=event_type,
        payload_schema_version=1,
        correlation_id=U[2],
        actor_class=ActorClass.SERVICE,
        actor_id=U[3],
        round=sequence,
        payload={"from": "INITIALIZING", "to": "RUNNING", "artifact_id": str(U[4])},
        recorded_at=datetime(2026, 9, 6, sequence, tzinfo=UTC),
        payload_hash="sha256:" + "1" * 64,
        prev_hash="sha256:" + "2" * 64,
        event_hash="sha256:" + "3" * 64,
    )


class RecordingBus:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[tuple[str, EventEnvelope]] = []

    async def publish(self, subject: str, event: EventEnvelope) -> Any:
        if self.fail:
            raise RuntimeError("transport down")
        self.published.append((subject, event))


@req("FR-106", "NFR-006")
async def test_post_commit_publish_preserves_ledger_sequence_and_filters_bodies() -> None:
    bus = RecordingBus()
    event = persisted(1)

    await LedgerEventPublisher(bus, code_version="sha").publish((event,))  # type: ignore[arg-type]

    subject, envelope = bus.published[0]
    assert subject == f"session.{U[0]}.{U[1]}.committed"
    assert envelope.ledger_seq == 1
    assert envelope.payload == {"artifact_id": str(U[4])}
    assert envelope.code_version == "sha"
    await LedgerEventPublisher(RecordingBus(fail=True), code_version="sha").publish(  # type: ignore[arg-type]
        (event,)
    )


@req("FR-106")
async def test_resume_stream_reads_only_ledger_rows_after_cursor() -> None:
    class Gateway(RealtimeGateway):
        def __init__(self) -> None:
            self._wakeups = {}
            self._code_version = "sha"
            self.calls: list[int] = []

        async def _read(self, workspace_id: UUID, session_id: UUID, from_seq: int) -> Any:
            self.calls.append(from_seq)
            if from_seq == 2:
                return (persisted(2), persisted(3, "SESSION_COMPLETED")), True
            return (), True

    gateway = Gateway()
    frames = [frame async for frame in gateway.stream(U[0], U[1], after=1)]

    assert gateway.calls == [2, 4]
    assert [frame.split(b"\n", 1)[0] for frame in frames] == [b"id: 2", b"id: 3"]
    payloads = [json.loads(frame.split(b"data: ", 1)[1]) for frame in frames]
    assert [payload["ledger_seq"] for payload in payloads] == [2, 3]


@req("FR-106", "NFR-003")
def test_event_envelope_uses_ledger_order_not_transport_order() -> None:
    assert event_envelope(persisted(2), code_version="sha").ledger_seq == 2
