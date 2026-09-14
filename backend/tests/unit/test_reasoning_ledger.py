"""Phase 3 reasoning-ledger domain and SQLAlchemy mapping tests."""

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.reasoning_ledger import ReasoningEventRow, SessionLedgerHeadRow
from app.db.reasoning_ledger import SqlAlchemyReasoningLedger
from app.domain import (
    GENESIS_HASH,
    ActorClass,
    LedgerAppend,
    LedgerEvent,
    LedgerIntegrityError,
    ledger_event_hash,
    ledger_payload_hash,
)
from tests.traceability import req

U1 = UUID("018f0000-0000-7000-8000-000000000001")
U2 = UUID("018f0000-0000-7000-8000-000000000002")
U3 = UUID("018f0000-0000-7000-8000-000000000003")
U4 = UUID("018f0000-0000-7000-8000-000000000004")
U5 = UUID("018f0000-0000-7000-8000-000000000005")
NOW = datetime(2026, 9, 5, 12, 34, 56, 123456, tzinfo=UTC)


def append_value(**changes: object) -> LedgerAppend:
    values: dict[str, object] = {
        "id": U1,
        "workspace_id": U2,
        "session_id": U3,
        "event_type": "ARTIFACT_COMMITTED",
        "payload_schema_version": 1,
        "causation_id": None,
        "correlation_id": U4,
        "actor_class": ActorClass.HUMAN,
        "actor_id": U5,
        "round": 0,
        "payload": {"artifact_id": str(U1), "nested": {"b": 2, "a": 1}},
        "recorded_at": NOW,
    }
    values.update(changes)
    return LedgerAppend.model_validate(values)


def persisted(**changes: object) -> LedgerEvent:
    request = append_value()
    values = {
        **request.model_dump(),
        "ledger_seq": 1,
        "payload_hash": ledger_payload_hash(request.payload),
        "prev_hash": GENESIS_HASH,
        "event_hash": GENESIS_HASH,
    }
    values.update(changes)
    candidate = LedgerEvent.model_validate(values)
    if "event_hash" not in changes:
        candidate = candidate.model_copy(update={"event_hash": ledger_event_hash(candidate)})
    return candidate


@req("FR-807", "NFR-003", "NFR-006")
def test_hashes_are_deterministic_and_use_normative_timestamp_shape() -> None:
    first = persisted()
    reordered = persisted(payload={"nested": {"a": 1, "b": 2}, "artifact_id": str(U1)})
    offset = persisted(recorded_at=NOW.astimezone(timezone(timedelta(hours=2))))

    assert first.payload_hash == reordered.payload_hash
    assert first.event_hash == reordered.event_hash == offset.event_hash
    assert (
        first.event_hash
        == "sha256:991536488f394333d5b33c567291fdd515b58289ed99d4ee405f2b8e97b98653"
    )


@req("FR-807", "NFR-003", "NFR-006")
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_type", "  "),
        ("payload_schema_version", 0),
        ("round", -1),
        ("recorded_at", NOW.replace(tzinfo=None)),
    ],
)
def test_append_rejects_invalid_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        append_value(**{field: value})


@req("FR-807", "NFR-003", "NFR-006")
def test_append_rejects_noncanonical_json_numbers() -> None:
    with pytest.raises(ValidationError, match="floats are forbidden"):
        append_value(payload={"value": 0.5})


@req("FR-807", "NFR-003", "NFR-006")
def test_append_payload_is_deeply_immutable() -> None:
    event = append_value(payload={"nested": {"ids": [1, 2]}})

    with pytest.raises(TypeError, match="frozen JSON object"):
        event.payload["changed"] = True
    with pytest.raises(TypeError, match="frozen JSON object"):
        event.payload["nested"]["changed"] = True
    assert event.payload["nested"]["ids"] == (1, 2)
    assert ledger_payload_hash(event.payload) == ledger_payload_hash({"nested": {"ids": [1, 2]}})


@req("FR-807", "NFR-003", "NFR-006")
async def test_adapter_appends_and_advances_head_without_commit() -> None:
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=None)
    head = SessionLedgerHeadRow(workspace_id=U2, session_id=U3)
    head.next_seq, head.head_hash = 1, GENESIS_HASH
    session.scalar = AsyncMock(return_value=head)
    ledger = SqlAlchemyReasoningLedger(session)

    event = await ledger.append(append_value())

    row = session.add.call_args.args[0]
    assert isinstance(row, ReasoningEventRow)
    assert (event.ledger_seq, event.prev_hash, head.next_seq, head.head_hash) == (
        1,
        GENESIS_HASH,
        2,
        event.event_hash,
    )
    session.flush.assert_awaited_once_with()
    session.commit.assert_not_called()


@req("FR-807", "NFR-003", "NFR-006")
async def test_idempotent_retry_returns_matching_row_and_rejects_mismatch() -> None:
    existing = persisted()
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=ReasoningEventRow(**existing.model_dump(mode="python")))
    ledger = SqlAlchemyReasoningLedger(session)

    assert await ledger.append(append_value()) == existing
    with pytest.raises(LedgerIntegrityError, match="different caller values"):
        await ledger.append(append_value(event_type="STATUS_CHANGED"))
    session.flush.assert_not_called()


@req("FR-807", "NFR-003", "NFR-006")
def test_verification_detects_payload_chain_sequence_and_head_changes() -> None:
    first = persisted()
    second = persisted(
        id=U4,
        ledger_seq=2,
        prev_hash=first.event_hash,
        payload={"artifact_id": str(U4)},
        payload_hash=ledger_payload_hash({"artifact_id": str(U4)}),
    )
    assert (
        SqlAlchemyReasoningLedger._verify_events(
            (first, second), next_seq=3, head_hash=second.event_hash
        )
        is None
    )
    assert SqlAlchemyReasoningLedger._verify_events(
        (first.model_copy(update={"payload": {"tampered": True}}),),
        next_seq=2,
        head_hash=first.event_hash,
    ) == (1, "payload hash mismatch")
    assert SqlAlchemyReasoningLedger._verify_events(
        (second,), next_seq=2, head_hash=second.event_hash
    ) == (2, "expected ledger sequence 1")
    assert SqlAlchemyReasoningLedger._verify_events(
        (first,), next_seq=2, head_hash=GENESIS_HASH
    ) == (None, "ledger head hash mismatch")
