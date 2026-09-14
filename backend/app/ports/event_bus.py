"""`EventBus` port — `docs/PORTS.md` §3.

The bus is **transport only**. PostgreSQL holds the authoritative ledger
(ADR-004, ADR-019); a publish failure never rolls back committed state. That is why
`publish` returns an ack rather than a confirmation of consumption, and why
`read_from` exists at all: replay always comes from the ledger, not from the bus.

Delivery is at-least-once, so every handler must be idempotent by `event_id` (EV-2).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.ports.health import HealthStatus

__all__ = ["EventBus", "EventEnvelope", "EventHandler", "PublishAck", "Subscription"]


class EventEnvelope(BaseModel):
    """The wire shape of a reasoning event. Mirrors `docs/API_CONTRACTS.md` §7.

    `extra="forbid"` is deliberate: an unknown field in an event is a contract breach,
    not something to quietly tolerate. EV-4 still requires that a *consumer* ignore an
    unknown `type` value — that is about forward compatibility of the enum, not of the
    schema.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(description="UUIDv7 string; the idempotency key for consumers")
    ledger_seq: int = Field(description="Monotonic per session; the only ordering key (EV-1)")
    type: str = Field(description="SCREAMING_SNAKE event type, e.g. CLAIM_PROPOSED")
    ts: datetime = Field(description="UTC-aware occurrence time")
    session_id: str
    actor_id: str
    actor_class: str = Field(description="AGENT | HUMAN | SERVICE | POLICY")
    round: int | None = None
    payload: dict[str, Any] = Field(
        default_factory=dict, description="ids only, never bodies (EV-3)"
    )
    schema_version: int = 1
    code_version: str = Field(default="", description="git commit that emitted this event")


class PublishAck(BaseModel):
    model_config = ConfigDict(frozen=True)

    accepted: bool
    ledger_seq: int | None = None
    subject: str = ""


class Subscription(BaseModel):
    model_config = ConfigDict(frozen=True)

    subscription_id: str
    subject: str
    group: str


#: Handlers receive one event and must be idempotent. Returning normally acknowledges it.
EventHandler = Callable[[EventEnvelope], Awaitable[None]]


@runtime_checkable
class EventBus(Protocol):
    """Publish/subscribe with at-least-once delivery and sequence-based replay."""

    async def publish(self, subject: str, event: EventEnvelope) -> PublishAck: ...

    async def subscribe(
        self,
        subject: str,
        group: str,
        handler: EventHandler,
        *,
        from_start: bool = False,
    ) -> Subscription: ...

    async def read_from(
        self, subject: str, sequence: int, *, limit: int
    ) -> Sequence[EventEnvelope]: ...

    async def request(
        self, subject: str, message: dict[str, Any], *, timeout_s: float
    ) -> dict[str, Any]: ...

    async def health(self) -> HealthStatus: ...

    async def close(self) -> None: ...
