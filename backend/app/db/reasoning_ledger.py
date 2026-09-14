"""SQLAlchemy implementation of the Phase 3 reasoning-ledger boundary."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.reasoning_ledger import ReasoningEventRow, SessionLedgerHeadRow
from app.domain.reasoning import ActorClass
from app.domain.reasoning_ledger import (
    AgentProposalLedger,
    LedgerAppend,
    LedgerEvent,
    LedgerIntegrityError,
    LedgerVerification,
    ReasoningLedger,
    ledger_event_hash,
    ledger_payload_hash,
)

__all__ = ["SqlAlchemyReasoningLedger"]


def _event_from_row(row: ReasoningEventRow) -> LedgerEvent:
    return LedgerEvent(
        id=row.id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        ledger_seq=row.ledger_seq,
        event_type=row.event_type,
        payload_schema_version=row.payload_schema_version,
        causation_id=row.causation_id,
        correlation_id=row.correlation_id,
        actor_class=ActorClass(row.actor_class),
        actor_id=row.actor_id,
        round=row.round,
        payload=row.payload,
        payload_hash=row.payload_hash,
        recorded_at=row.recorded_at,
        prev_hash=row.prev_hash,
        event_hash=row.event_hash,
    )


def _append_preimage(event: LedgerAppend | LedgerEvent) -> tuple[object, ...]:
    return (
        event.id,
        event.workspace_id,
        event.session_id,
        event.event_type,
        event.payload_schema_version,
        event.causation_id,
        event.correlation_id,
        event.actor_class,
        event.actor_id,
        event.round,
        event.payload,
    )


class SqlAlchemyReasoningLedger:
    """Append/read/verify inside a caller-owned transaction without committing it."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.appended: list[LedgerEvent] = []

    async def _event_by_id(self, event_id: UUID) -> LedgerEvent | None:
        row = await self._session.get(ReasoningEventRow, event_id)
        return _event_from_row(row) if row is not None else None

    async def get_by_id(
        self, workspace_id: UUID, session_id: UUID, event_id: UUID
    ) -> LedgerEvent | None:
        event = await self._event_by_id(event_id)
        if event is None or (event.workspace_id, event.session_id) != (workspace_id, session_id):
            return None
        return event

    @staticmethod
    def _idempotent_result(requested: LedgerAppend, existing: LedgerEvent) -> LedgerEvent:
        if _append_preimage(requested) != _append_preimage(existing):
            raise LedgerIntegrityError(
                f"reasoning event id {requested.id} already exists with different caller values"
            )
        return existing

    async def append(self, event: LedgerAppend) -> LedgerEvent:
        existing = await self._event_by_id(event.id)
        if existing is not None:
            return self._idempotent_result(event, existing)

        head = await self._session.scalar(
            select(SessionLedgerHeadRow)
            .where(
                SessionLedgerHeadRow.workspace_id == event.workspace_id,
                SessionLedgerHeadRow.session_id == event.session_id,
            )
            .with_for_update()
        )
        if head is None:
            raise LedgerIntegrityError(
                f"session {event.session_id} has no ledger head in workspace {event.workspace_id}"
            )

        existing = await self._event_by_id(event.id)
        if existing is not None:
            return self._idempotent_result(event, existing)

        persisted = LedgerEvent(
            **event.model_dump(),
            ledger_seq=head.next_seq,
            payload_hash=ledger_payload_hash(event.payload),
            prev_hash=head.head_hash,
            event_hash="sha256:" + "0" * 64,
        )
        persisted = persisted.model_copy(update={"event_hash": ledger_event_hash(persisted)})
        self._session.add(
            ReasoningEventRow(
                id=persisted.id,
                workspace_id=persisted.workspace_id,
                session_id=persisted.session_id,
                ledger_seq=persisted.ledger_seq,
                event_type=persisted.event_type,
                payload_schema_version=persisted.payload_schema_version,
                causation_id=persisted.causation_id,
                correlation_id=persisted.correlation_id,
                actor_class=persisted.actor_class.value,
                actor_id=persisted.actor_id,
                round=persisted.round,
                payload=dict(persisted.payload),
                payload_hash=persisted.payload_hash,
                recorded_at=persisted.recorded_at,
                prev_hash=persisted.prev_hash,
                event_hash=persisted.event_hash,
            )
        )
        head.next_seq = persisted.ledger_seq + 1
        head.head_hash = persisted.event_hash
        await self._session.flush()
        self.appended.append(persisted)
        return persisted

    async def read(
        self, workspace_id: UUID, session_id: UUID, *, from_seq: int = 1, limit: int = 1000
    ) -> Sequence[LedgerEvent]:
        if from_seq <= 0:
            raise ValueError("from_seq must be positive")
        if limit <= 0:
            raise ValueError("limit must be positive")
        rows = (
            await self._session.scalars(
                select(ReasoningEventRow)
                .where(
                    ReasoningEventRow.workspace_id == workspace_id,
                    ReasoningEventRow.session_id == session_id,
                    ReasoningEventRow.ledger_seq >= from_seq,
                )
                .order_by(ReasoningEventRow.ledger_seq)
                .limit(limit)
            )
        ).all()
        return tuple(_event_from_row(row) for row in rows)

    async def verify(self, workspace_id: UUID, session_id: UUID) -> LedgerVerification:
        head = await self._session.scalar(
            select(SessionLedgerHeadRow)
            .where(
                SessionLedgerHeadRow.workspace_id == workspace_id,
                SessionLedgerHeadRow.session_id == session_id,
            )
            .with_for_update(read=True)
        )
        if head is None:
            return LedgerVerification(
                valid=False,
                event_count=0,
                head_hash="sha256:" + "0" * 64,
                reason="session ledger head is missing",
            )
        rows = (
            await self._session.scalars(
                select(ReasoningEventRow)
                .where(
                    ReasoningEventRow.workspace_id == workspace_id,
                    ReasoningEventRow.session_id == session_id,
                )
                .order_by(ReasoningEventRow.ledger_seq)
            )
        ).all()
        events = tuple(_event_from_row(row) for row in rows)
        failure = self._verify_events(events, next_seq=head.next_seq, head_hash=head.head_hash)
        if failure is not None:
            failed_seq, reason = failure
            return LedgerVerification(
                valid=False,
                event_count=len(events),
                head_hash=head.head_hash,
                first_invalid_seq=failed_seq,
                reason=reason,
            )
        return LedgerVerification(valid=True, event_count=len(events), head_hash=head.head_hash)

    @staticmethod
    def _verify_events(
        events: Sequence[LedgerEvent], *, next_seq: int, head_hash: str
    ) -> tuple[int | None, str] | None:
        previous_hash = "sha256:" + "0" * 64
        for expected_seq, event in enumerate(events, start=1):
            if event.ledger_seq != expected_seq:
                return event.ledger_seq, f"expected ledger sequence {expected_seq}"
            if event.payload_hash != ledger_payload_hash(event.payload):
                return event.ledger_seq, "payload hash mismatch"
            if event.prev_hash != previous_hash:
                return event.ledger_seq, "previous hash mismatch"
            if event.event_hash != ledger_event_hash(event):
                return event.ledger_seq, "event hash mismatch"
            previous_hash = event.event_hash
        if next_seq != len(events) + 1:
            return None, "ledger head next sequence mismatch"
        if head_hash != previous_hash:
            return None, "ledger head hash mismatch"
        return None


_LEDGER_PORT: type[ReasoningLedger] = SqlAlchemyReasoningLedger
_AGENT_PROPOSAL_LEDGER_PORT: type[AgentProposalLedger] = SqlAlchemyReasoningLedger
