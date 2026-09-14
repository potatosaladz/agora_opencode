"""In-memory `EventBus`. The reference implementation of the port's semantics.

This adapter is not merely a convenience for tests — it is the executable definition of
what `EventBus` promises. `tests/contracts/test_event_bus.py` runs one suite against both
this and NATS, so a NATS-specific interpretation of "at-least-once" cannot pass while the
in-memory one fails, or the reverse.

Semantics implemented (docs/PORTS.md §3):

* at-least-once delivery; consumers deduplicate on `event_id` (EV-2)
* per-subject monotonic `ledger_seq`, assigned on publish (EV-1)
* `read_from` replays by sequence, which is how a reconnecting SSE client catches up
* a raising handler is logged and isolated; it never corrupts the subject for other
  consumers, but it does propagate, because silently swallowing a failed handler would
  turn a delivery bug into a missing event with no trace of either

Nothing here survives a restart. That is deliberate and is the reason PostgreSQL, not the
bus, holds the authoritative ledger (ADR-004, ADR-019).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from fnmatch import fnmatchcase
from typing import Any

from app.adapters.prometheus.metrics import EVENT_PUBLISHES
from app.common.ids import uuid7
from app.observability.logging import get_logger
from app.ports.errors import PermanentPortError, TransientPortError
from app.ports.event_bus import EventBus, EventEnvelope, EventHandler, PublishAck, Subscription
from app.ports.health import HealthStatus

__all__ = ["InMemoryEventBus", "Responder"]

_LOG = get_logger("agora.adapters.inmemory.event_bus")

#: A request/reply handler. Distinct from `EventHandler` because it returns a body.
Responder = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class InMemoryEventBus:
    """Single-process bus implementing `docs/PORTS.md` §3."""

    def __init__(self) -> None:
        self._subjects: dict[str, list[EventEnvelope]] = defaultdict(list)
        self._sequences: dict[str, int] = defaultdict(int)
        self._handlers: dict[tuple[str, str], list[tuple[str, EventHandler]]] = defaultdict(list)
        self._round_robin: dict[tuple[str, str], int] = defaultdict(int)
        self._responders: dict[str, Responder] = {}
        self._subscriptions: dict[str, Subscription] = {}
        self._closed = False
        self._lock = asyncio.Lock()

    async def publish(self, subject: str, event: EventEnvelope) -> PublishAck:
        self._guard("publish")
        async with self._lock:
            self._sequences[subject] += 1
            seq = self._sequences[subject]
            stored = event.model_copy(update={"ledger_seq": seq})
            self._subjects[subject].append(stored)
            targets = self._select_deliveries(subject)
        EVENT_PUBLISHES.labels(subject, "ok").inc()
        for handler in targets:
            await self._invoke(subject, handler, stored)
        return PublishAck(accepted=True, ledger_seq=seq, subject=subject)

    def _select_deliveries(self, subject: str) -> list[EventHandler]:
        """One delivery per consumer group.

        Groups are independent subscribers (each sees every event); within a group the
        handlers are competing consumers, so exactly one gets each event. This mirrors
        what a NATS durable work-queue group does, which is the property the shared
        contract suite exists to pin down. Caller must hold `self._lock`.
        """
        matching = [key for key in self._handlers if fnmatchcase(subject, key[0].replace(">", "*"))]
        groups = sorted({key[1] for key in matching})
        selected: list[EventHandler] = []
        for group in groups:
            members = [
                member
                for pattern, member_group in matching
                if member_group == group
                for member in self._handlers[(pattern, member_group)]
            ]
            if not members:
                continue
            index = self._round_robin[(subject, group)] % len(members)
            self._round_robin[(subject, group)] = index + 1
            selected.append(members[index][1])
        return selected

    async def subscribe(
        self,
        subject: str,
        group: str,
        handler: EventHandler,
        *,
        from_start: bool = False,
    ) -> Subscription:
        self._guard("subscribe")
        subscription = Subscription(
            subscription_id=f"sub_{uuid7().hex}", subject=subject, group=group
        )
        async with self._lock:
            self._subscriptions[subscription.subscription_id] = subscription
            self._handlers[(subject, group)].append((subscription.subscription_id, handler))
            backlog = list(self._subjects.get(subject, ())) if from_start else []
        for event in backlog:
            await self._invoke(subject, handler, event)
        return subscription

    async def unsubscribe(self, subscription_id: str) -> None:
        """Idempotent: an unknown id is a no-op, not an error."""
        subscription = self._subscriptions.pop(subscription_id, None)
        if subscription is None:
            return
        key = (subscription.subject, subscription.group)
        async with self._lock:
            self._handlers[key] = [
                pair for pair in self._handlers[key] if pair[0] != subscription_id
            ]
            if not self._handlers[key]:
                del self._handlers[key]

    async def read_from(
        self, subject: str, sequence: int, *, limit: int
    ) -> Sequence[EventEnvelope]:
        self._guard("read_from")
        if limit <= 0:
            raise PermanentPortError(f"limit must be positive, got {limit}", port="event_bus")
        async with self._lock:
            return tuple(
                event for event in self._subjects.get(subject, ()) if event.ledger_seq >= sequence
            )[:limit]

    async def request(
        self, subject: str, message: dict[str, Any], *, timeout_s: float
    ) -> dict[str, Any]:
        self._guard("request")
        responder = self._responders.get(subject)
        if responder is None:
            raise TransientPortError(
                f"no responder registered on subject {subject!r}", port="event_bus"
            )
        try:
            return await asyncio.wait_for(responder(dict(message)), timeout=timeout_s)
        except TimeoutError as exc:
            raise TransientPortError(
                f"request on {subject!r} timed out after {timeout_s}s", port="event_bus"
            ) from exc

    async def register_responder(self, subject: str, responder: Responder) -> None:
        """Make a subject answer `request`. Test and single-process-dev only."""
        self._responders[subject] = responder

    async def health(self) -> HealthStatus:
        return HealthStatus.DOWN if self._closed else HealthStatus.OK

    async def close(self) -> None:
        """Idempotent. After close every operation raises `TransientPortError`, because a
        closed bus is a configuration mistake worth failing loudly on."""
        self._closed = True
        self._handlers.clear()
        self._responders.clear()

    async def _invoke(self, subject: str, handler: EventHandler, event: EventEnvelope) -> None:
        try:
            await handler(event)
        except Exception as exc:
            EVENT_PUBLISHES.labels(subject, "handler_error").inc()
            _LOG.error(
                "handler_raised",
                subject=subject,
                event_id=event.event_id,
                ledger_seq=event.ledger_seq,
                error_type=type(exc).__name__,
            )
            raise TransientPortError(
                f"handler for {subject!r} raised {type(exc).__name__}", port="event_bus"
            ) from exc

    def _guard(self, operation: str) -> None:
        if self._closed:
            raise TransientPortError(f"event bus is closed; cannot {operation}", port="event_bus")


#: Structural conformance, checked by mypy. See the same note in `cache.py`.
_BUS_PORT: type[EventBus] = InMemoryEventBus
