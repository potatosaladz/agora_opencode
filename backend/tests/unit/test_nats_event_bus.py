"""Unit tests for the NATS JetStream event-bus adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from nats.js.api import AckPolicy, DeliverPolicy

from app.adapters.nats.event_bus import NatsJetStreamEventBus, _durable_name
from app.observability.logging import get_logger
from app.ports.errors import PermanentPortError
from app.ports.event_bus import EventEnvelope
from tests.traceability import req


def _event() -> EventEnvelope:
    return EventEnvelope(
        event_id="019c0000-0000-7000-8000-000000000001",
        ledger_seq=7,
        type="CLAIM_PROPOSED",
        ts=datetime(2026, 9, 4, tzinfo=UTC),
        session_id="session-1",
        actor_id="agent-1",
        actor_class="AGENT",
    )


def _connected_bus(js: Any, nc: Any | None = None) -> NatsJetStreamEventBus:
    bus = NatsJetStreamEventBus("nats://unused")
    bus._js = cast(Any, js)
    bus._nc = cast(Any, nc or SimpleNamespace(is_closed=False))
    bus._connected = True
    return bus


@req("NFR-016")
def test_structured_error_logging_does_not_raise() -> None:
    get_logger("agora.tests.nats").error("expected_test_error", subject="agora.events")


@req("NFR-016")
def test_durable_name_is_legal_stable_and_collision_resistant() -> None:
    first = _durable_name("agora." + "a" * 150, "workers")
    repeated = _durable_name("agora." + "a" * 150, "workers")
    different = _durable_name("agora." + "a" * 149 + "b", "workers")

    assert first == repeated
    assert first != different
    assert len(first) == 128
    assert all(character.isalnum() or character in "-_" for character in first)


@req("NFR-016")
async def test_existing_stream_is_reconciled_for_realtime_subjects() -> None:
    config = SimpleNamespace(subjects=["agora.>"])
    js = SimpleNamespace(
        stream_info=AsyncMock(return_value=SimpleNamespace(config=config)),
        update_stream=AsyncMock(),
    )
    bus = NatsJetStreamEventBus("nats://unused")
    bus._js = cast(Any, js)

    await bus._ensure_stream()

    assert set(config.subjects) == {"agora.>", "session.*.*.committed"}
    js.update_stream.assert_awaited_once_with(config)


@req("NFR-016")
@pytest.mark.parametrize("handler_raises", [False, True])
async def test_subscription_acks_success_and_naks_handler_failure(handler_raises: bool) -> None:
    js = SimpleNamespace(subscribe=AsyncMock(return_value=SimpleNamespace()))
    bus = _connected_bus(js)

    async def handler(event: EventEnvelope) -> None:
        assert event == _event()
        if handler_raises:
            raise RuntimeError("retry me")

    subscription = await bus.subscribe("agora.events", "workers", handler, from_start=True)
    callback = js.subscribe.await_args.kwargs["cb"]
    config = js.subscribe.await_args.kwargs["config"]
    message = SimpleNamespace(
        data=_event().model_dump_json().encode(),
        ack=AsyncMock(),
        nak=AsyncMock(),
        term=AsyncMock(),
    )

    await callback(message)

    durable = _durable_name("agora.events", "workers")
    assert subscription.subject == "agora.events"
    assert subscription.group == "workers"
    assert js.subscribe.await_args.kwargs["queue"] == durable
    assert js.subscribe.await_args.kwargs["durable"] == durable
    assert js.subscribe.await_args.kwargs["manual_ack"] is True
    assert config.durable_name == durable
    assert config.deliver_group == durable
    assert config.ack_policy is AckPolicy.EXPLICIT
    assert config.deliver_policy is DeliverPolicy.ALL
    assert config.filter_subject == "agora.events"
    if handler_raises:
        message.nak.assert_awaited_once_with()
        message.ack.assert_not_awaited()
    else:
        message.ack.assert_awaited_once_with()
        message.nak.assert_not_awaited()
    message.term.assert_not_awaited()


@req("NFR-016")
async def test_subscription_terminates_malformed_event() -> None:
    js = SimpleNamespace(subscribe=AsyncMock(return_value=SimpleNamespace()))
    bus = _connected_bus(js)

    async def handler(event: EventEnvelope) -> None:
        raise AssertionError(f"handler received malformed event: {event}")

    await bus.subscribe("agora.events", "workers", handler)
    callback = js.subscribe.await_args.kwargs["cb"]
    message = SimpleNamespace(data=b"not-json", ack=AsyncMock(), nak=AsyncMock(), term=AsyncMock())

    await callback(message)

    message.term.assert_awaited_once_with()
    message.ack.assert_not_awaited()
    message.nak.assert_not_awaited()


@req("NFR-016")
async def test_read_from_terminates_invalid_payload_and_unsubscribes() -> None:
    message = SimpleNamespace(data=b"{}", ack=AsyncMock(), term=AsyncMock())
    pull_subscription = SimpleNamespace(
        fetch=AsyncMock(return_value=[message]), unsubscribe=AsyncMock()
    )
    js = SimpleNamespace(pull_subscribe=AsyncMock(return_value=pull_subscription))
    bus = _connected_bus(js)

    with pytest.raises(PermanentPortError, match="invalid event payload"):
        await bus.read_from("agora.events", 4, limit=10)

    message.term.assert_awaited_once_with()
    message.ack.assert_not_awaited()
    pull_subscription.unsubscribe.assert_awaited_once_with()
    config = js.pull_subscribe.await_args.kwargs["config"]
    assert config.deliver_policy is DeliverPolicy.BY_START_SEQUENCE
    assert config.opt_start_seq == 4


@req("NFR-016")
async def test_request_rejects_non_object_json_response() -> None:
    nc = SimpleNamespace(
        is_closed=False,
        request=AsyncMock(return_value=SimpleNamespace(data=b'["not", "an", "object"]')),
    )
    bus = _connected_bus(SimpleNamespace(), nc)

    with pytest.raises(PermanentPortError, match="must be a JSON object"):
        await bus.request("agora.rpc", {"question": "why"}, timeout_s=0.5)
