"""NATS JetStream `EventBus` adapter. ADR-004, `docs/PORTS.md` §3.

The bus is **transport only**. PostgreSQL holds the authoritative append-only ledger
(ADR-019), so this adapter never assigns the ordering key: `EventEnvelope.ledger_seq` is
written by the ledger and carried through unchanged, and the `PublishAck.ledger_seq` this
adapter returns is the *stream* sequence, which is a transport offset useful for
reconciliation and nothing else. A consumer that ordered events by the ack would be
ordering by arrival, which is precisely the bug EV-1 exists to prevent.

Delivery is at-least-once: a handler is acked only after it returns, so a crash mid-handler
redelivers. Consumers must therefore deduplicate on `event_id` (EV-2), and the contract
suite asserts that redelivery actually happens rather than trusting this paragraph.

Consumer groups map onto NATS queue groups, which is what makes "one delivery per group,
every event to every group" work across replicas without any coordination here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from contextlib import suppress
from typing import Any

import nats
from nats.aio.client import Client as NatsClient
from nats.errors import (
    AuthorizationError,
    BadSubjectError,
    NoRespondersError,
    NoServersError,
)
from nats.errors import (
    Error as NatsError,
)
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
from nats.js.client import JetStreamContext
from nats.js.errors import NotFoundError
from pydantic import ValidationError

from app.observability.logging import get_logger
from app.ports.errors import PermanentPortError, TransientPortError
from app.ports.event_bus import EventBus, EventEnvelope, EventHandler, PublishAck, Subscription
from app.ports.health import HealthStatus

__all__ = ["NatsJetStreamEventBus"]

_LOG = get_logger("agora.adapters.nats.event_bus")
_PORT = "event_bus"


def _transient(exc: BaseException) -> TransientPortError:
    return TransientPortError(f"nats fault: {exc}", port=_PORT, cause=exc)


def _durable_name(subject: str, group: str) -> str:
    """A durable consumer name that is stable, legal, and cannot collide across subjects.

    NATS forbids whitespace and wildcards in a consumer name, so the subject's dots become
    underscores and anything else exotic is dropped rather than escaped.
    """
    raw = f"{subject}_{group}"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in raw)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return f"{safe[:115]}_{digest}"


class NatsJetStreamEventBus:
    """`EventBus` over NATS JetStream, with one stream per deployment."""

    def __init__(
        self,
        url: str,
        *,
        stream: str = "AGORA",
        subjects: Sequence[str] = ("agora.>", "session.*.*.committed"),
        connect_timeout_s: float = 5.0,
        publish_timeout_s: float = 5.0,
        ack_wait_s: float = 30.0,
        max_deliver: int = 5,
        replay_timeout_s: float = 1.0,
    ) -> None:
        self._url = url
        self._stream = stream
        self._subjects = tuple(subjects)
        self._connect_timeout_s = connect_timeout_s
        self._publish_timeout_s = publish_timeout_s
        self._ack_wait_s = ack_wait_s
        self._max_deliver = max_deliver
        self._replay_timeout_s = replay_timeout_s
        self._nc: NatsClient | None = None
        self._js: JetStreamContext | None = None
        self._subs: dict[str, Any] = {}
        self._connected = False

    async def connect(self) -> None:
        """Idempotent. Called by the composition root at startup, never lazily per call:
        a first-request connection cost would land on a user-visible latency budget."""
        if self._connected:
            return
        try:
            self._nc = await nats.connect(
                servers=self._url,
                name="agora-event-bus",
                connect_timeout=self._connect_timeout_s,
                allow_reconnect=True,
                reconnect_time_wait=1,
                max_reconnect_attempts=60,
                error_cb=self._on_error,
            )
            self._js = self._nc.jetstream()
            await self._ensure_stream()
        except AuthorizationError as exc:
            await self._reset_connection()
            raise PermanentPortError("nats authentication failed", port=_PORT, cause=exc) from exc
        except (TimeoutError, NoServersError, OSError, NatsError) as exc:
            await self._reset_connection()
            raise _transient(exc) from exc
        self._connected = True

    async def _on_error(self, exc: Exception) -> None:
        _LOG.error("nats_client_error", error_type=type(exc).__name__)

    async def _ensure_stream(self) -> None:
        assert self._js is not None
        try:
            info = await self._js.stream_info(self._stream)
            if set(info.config.subjects or ()) != set(self._subjects):
                info.config.subjects = list(self._subjects)
                await self._js.update_stream(info.config)
        except NotFoundError:
            await self._js.add_stream(
                name=self._stream, subjects=list(self._subjects), storage="file", num_replicas=1
            )

    async def publish(self, subject: str, event: EventEnvelope) -> PublishAck:
        js = await self._context("publish")
        try:
            ack = await js.publish(
                subject,
                payload=event.model_dump_json().encode("utf-8"),
                timeout=self._publish_timeout_s,
                headers={"agora-event-id": event.event_id, "agora-session": event.session_id},
            )
        except (BadSubjectError, AuthorizationError) as exc:
            raise PermanentPortError(
                f"nats rejected {subject}: {exc}", port=_PORT, cause=exc
            ) from exc
        except NatsError as exc:
            raise _transient(exc) from exc
        return PublishAck(accepted=True, ledger_seq=ack.seq, subject=subject)

    async def subscribe(
        self,
        subject: str,
        group: str,
        handler: EventHandler,
        *,
        from_start: bool = False,
    ) -> Subscription:
        js = await self._context("subscribe")
        durable = _durable_name(subject, group)
        config = ConsumerConfig(
            durable_name=durable,
            ack_policy=AckPolicy.EXPLICIT,
            deliver_policy=DeliverPolicy.ALL if from_start else DeliverPolicy.NEW,
            ack_wait=self._ack_wait_s,
            max_deliver=self._max_deliver,
            filter_subject=subject,
            deliver_group=durable,
        )
        try:
            sub = await js.subscribe(
                subject,
                queue=durable,
                durable=durable,
                stream=self._stream,
                config=config,
                manual_ack=True,
                cb=self._callback(subject, handler),
            )
        except (BadSubjectError, AuthorizationError) as exc:
            raise PermanentPortError(
                f"nats rejected subscribe: {exc}", port=_PORT, cause=exc
            ) from exc
        except NatsError as exc:
            raise _transient(exc) from exc
        subscription = Subscription(subscription_id=f"sub_{durable}", subject=subject, group=group)
        self._subs[subscription.subscription_id] = sub
        return subscription

    def _callback(self, subject: str, handler: EventHandler) -> Any:
        """Wrap a handler in the ack/nak discipline that makes delivery at-least-once.

        Ack happens only after the handler returns, so a crash mid-handler redelivers. A
        payload that cannot be parsed is *terminated* rather than nacked: a poison message
        that will never parse must not burn `max_deliver` attempts forever, and silently
        dropping it would be worse, so it is logged at error level with its subject.
        """

        async def _on_msg(msg: Any) -> None:
            try:
                event = EventEnvelope.model_validate_json(msg.data)
            except Exception as exc:
                _LOG.error("undecodable_event", subject=subject, error_type=type(exc).__name__)
                await msg.term()
                return
            try:
                await handler(event)
            except Exception as exc:
                await msg.nak()
                _LOG.warning(
                    "handler_failed_nak",
                    subject=subject,
                    event_id=event.event_id,
                    error_type=type(exc).__name__,
                )
                return
            await msg.ack()

        return _on_msg

    async def read_from(
        self, subject: str, sequence: int, *, limit: int
    ) -> Sequence[EventEnvelope]:
        """Replay by stream sequence using an ephemeral pull consumer.

        This is the transport-level replay used to warm a reconnecting client. Once the
        PostgreSQL ledger lands in Phase 3 (ADR-019), the authoritative replay moves there
        and this becomes a bounded optimisation rather than the source of truth.
        """
        js = await self._context("read_from")
        if limit <= 0:
            raise PermanentPortError(f"limit must be positive, got {limit}", port=_PORT)
        config = ConsumerConfig(
            ack_policy=AckPolicy.EXPLICIT,
            deliver_policy=DeliverPolicy.BY_START_SEQUENCE,
            opt_start_seq=sequence,
            max_deliver=1,
            filter_subject=subject,
        )
        try:
            sub = await js.pull_subscribe(subject, stream=self._stream, config=config)
        except NatsError as exc:
            raise _transient(exc) from exc
        try:
            try:
                msgs = await sub.fetch(batch=limit, timeout=self._replay_timeout_s)
            except TimeoutError:
                # A timeout with no messages means the replay tail has been reached.
                msgs = []
            events: list[EventEnvelope] = []
            for msg in msgs:
                try:
                    event = EventEnvelope.model_validate_json(msg.data)
                except ValidationError as exc:
                    await msg.term()
                    raise PermanentPortError(
                        f"invalid event payload on {subject}", port=_PORT, cause=exc
                    ) from exc
                events.append(event)
                await msg.ack()
            return events
        finally:
            await sub.unsubscribe()

    async def request(
        self, subject: str, message: dict[str, Any], *, timeout_s: float
    ) -> dict[str, Any]:
        nc = await self._connection("request")
        try:
            reply = await nc.request(
                subject, payload=json.dumps(message).encode("utf-8"), timeout=timeout_s
            )
        except NoRespondersError as exc:
            # A worker that is not up yet is retryable, not a client error: the caller's
            # retry budget, not a 500, is the right place to absorb a cold start.
            raise TransientPortError(f"no responder on {subject}", port=_PORT, cause=exc) from exc
        except TimeoutError as exc:
            raise TransientPortError(
                f"request on {subject} timed out after {timeout_s}s", port=_PORT, cause=exc
            ) from exc
        except NatsError as exc:
            raise _transient(exc) from exc
        try:
            result = json.loads(reply.data)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PermanentPortError(
                f"invalid JSON response on {subject}", port=_PORT, cause=exc
            ) from exc
        if not isinstance(result, dict):
            raise PermanentPortError(f"response on {subject} must be a JSON object", port=_PORT)
        return result

    async def health(self) -> HealthStatus:
        if self._js is None or self._nc is None or self._nc.is_closed:
            return HealthStatus.DOWN
        try:
            await self._js.stream_info(self._stream)
        except NotFoundError:
            # Reachable but our stream is gone: degraded, because reconnecting alone will
            # not fix it while publish will keep failing.
            return HealthStatus.DEGRADED
        except (NatsError, TimeoutError):
            return HealthStatus.DOWN
        return HealthStatus.OK

    async def close(self) -> None:
        for sub in self._subs.values():
            with suppress(NatsError):
                await sub.unsubscribe()
        self._subs.clear()
        await self._reset_connection()

    async def _reset_connection(self) -> None:
        if self._nc is not None and not self._nc.is_closed:
            with suppress(NatsError):
                await self._nc.close()
        self._nc = None
        self._js = None
        self._connected = False

    async def _context(self, operation: str) -> JetStreamContext:
        await self.connect()
        assert self._js is not None
        return self._js

    async def _connection(self, operation: str) -> NatsClient:
        await self.connect()
        assert self._nc is not None
        return self._nc


#: mypy-checked structural conformance; see `inmemory/cache.py`.
_NATS_BUS_PORT: type[EventBus] = NatsJetStreamEventBus
