"""T13-02 unit tests: access log, daily anchors and the eight audit queries.

The audit services are pure orchestration over caller-scoped ports, so these
tests exercise them with in-memory fakes plus the real domain value objects.
Chain-integrity tamper cases mutate a fake ledger to prove that a changed
day-head or an invalid ledger verification is detected (Q8, FR-807/NFR-006).

trace: FR-807, NFR-006
"""

from __future__ import annotations

import binascii
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from app.application.audit import AccessAuditService, AuditQueryService, ChainVerificationService
from app.application.provenance import ProvenanceService
from app.domain import (
    GENESIS_HASH,
    ActorClass,
    ArtifactKind,
    Bearing,
    ClaimPayload,
    ClaimType,
    LedgerAppend,
    LedgerEvent,
    LedgerVerification,
    LifecycleStatus,
    ParentRelationship,
    Provenance,
    ProvenanceOrigin,
    ReasoningArtifact,
    ReasoningGraphStore,
    ReviewStatus,
    Strength,
    artifact_content_hash,
    content_hash,
    validate_artifact,
)
from app.domain.agent_registry import AgentRoleKind
from app.domain.audit import (
    AccessLogEntry,
    AccessResult,
    AuditAction,
    AuditAnchor,
    AuditConflictError,
    AuditResourceKind,
    AuditVerificationError,
    SessionParticipant,
    access_cursor_decode,
    access_cursor_encode,
    audit_anchor_hash,
)
from app.domain.citations import CitationRepository
from app.domain.consensus import (
    ConsensusExplanation,
    ConsensusOutcome,
    ConsensusRunRecord,
)
from app.domain.reasoning_graph import GraphNode
from app.domain.session_lifecycle import (
    SessionLifecycle,
    SessionLifecycleState,
    SessionTransition,
)
from tests.traceability import req

WS = UUID("018f0000-0000-7000-8000-000000000001")
SESSION = UUID("018f0000-0000-7000-8000-000000000002")
AGENT = UUID("018f0000-0000-7000-8000-000000000003")
NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)
DAY1 = datetime(2026, 9, 5, 10, tzinfo=UTC)
DAY2 = DAY1 + timedelta(days=1)


# ---------------------------------------------------------------------------
# Value-object helpers
# ---------------------------------------------------------------------------


def _artifact(artifact_id: UUID = SESSION) -> ReasoningArtifact:
    data: dict[str, object] = {
        "id": artifact_id,
        "workspace_id": WS,
        "session_id": SESSION,
        "logical_id": uuid4(),
        "kind": ArtifactKind.CLAIM,
        "schema_version": 1,
        "version": 1,
        "status": LifecycleStatus.ACTIVE,
        "supersedes_id": None,
        "owner_actor_class": ActorClass.HUMAN,
        "owner_actor_id": AGENT,
        "round": 0,
        "payload": ClaimPayload(
            statement="A claim",
            claim_type=ClaimType.FACTUAL,
            direction=Bearing.SUPPORTS,
            strength=Strength.MODERATE,
            supporting_evidence_ids=(),
            opposing_evidence_ids=(),
            review_status=ReviewStatus.PROPOSED,
        ),
        "provenance": Provenance(origin=ProvenanceOrigin.HUMAN, reference="unit-test"),
        "source_references": (),
        "parent_relationships": tuple[ParentRelationship, ...](),
        "confidence": None,
        "metadata": {},
        "created_at": NOW,
        "updated_at": NOW,
    }
    data["content_hash"] = artifact_content_hash(data)
    return validate_artifact(data)


def _event(
    *,
    event_id: UUID,
    seq: int,
    event_type: str,
    round: int = 0,
    recorded_at: datetime = NOW,
    causation_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> LedgerEvent:
    content: dict[str, Any] = payload if payload is not None else {}
    return LedgerEvent(
        id=event_id,
        workspace_id=WS,
        session_id=SESSION,
        event_type=event_type,
        payload_schema_version=1,
        causation_id=causation_id,
        correlation_id=uuid4(),
        actor_class=ActorClass.AGENT,
        actor_id=AGENT,
        round=round,
        payload=content,
        recorded_at=recorded_at,
        ledger_seq=seq,
        payload_hash="sha256:" + "1" * 64,
        prev_hash="sha256:" + "0" * 64,
        event_hash=content_hash(
            {"id": str(event_id), "seq": seq, "type": event_type, "payload": content}
        ),
    )


def _participant(name: str) -> SessionParticipant:
    return SessionParticipant(
        agent_definition_id=uuid4(),
        logical_id=uuid4(),
        name=name,
        domain="legal",
        role_kind=AgentRoleKind.DOMAIN_EXPERT,
    )


def _log_entry(*, recorded_at: datetime = NOW, resource_id: UUID | None = None) -> AccessLogEntry:
    return AccessLogEntry(
        workspace_id=WS,
        session_id=SESSION,
        principal_class=ActorClass.AGENT,
        principal_id=AGENT,
        resource_kind=AuditResourceKind.RECOMMENDATION,
        resource_id=resource_id or uuid4(),
        action=AuditAction.READ,
        result=AccessResult.ALLOWED,
        scope_ids=("scope-a",),
        trace_id="trace-1",
        recorded_at=recorded_at,
    )


def _consensus_record(*, round: int) -> ConsensusRunRecord:
    return ConsensusRunRecord(
        id=uuid4(),
        workspace_id=WS,
        session_id=SESSION,
        round=round,
        strategy="weighted",
        strategy_version="1.0.0",
        outcome=ConsensusOutcome.PARTIAL_CONSENSUS,
        selected_alternative_id=uuid4(),
        pareto_set=(uuid4(),),
        conditions=("condition-a",),
        input_hash=content_hash({"strategy": "weighted"}),
        created_at=NOW,
    )


# ---------------------------------------------------------------------------
# Port fakes
# ---------------------------------------------------------------------------


class FakeLedger:
    """In-memory `ReasoningLedger`; the event list is mutable for tamper tests."""

    def __init__(self, events: list[LedgerEvent] | None = None) -> None:
        self.events = list(events or [])
        self.verification = LedgerVerification(
            valid=True,
            event_count=len(self.events),
            head_hash="sha256:" + "2" * 64,
        )

    async def append(self, event: LedgerAppend) -> LedgerEvent:
        event_value = LedgerEvent(
            **event.model_dump(),
            ledger_seq=len(self.events) + 1,
            payload_hash="sha256:" + "1" * 64,
            prev_hash="sha256:" + "0" * 64,
            event_hash=f"sha256:{len(self.events) + 1:064x}",
        )
        self.events.append(event_value)
        return event_value

    async def read(
        self, workspace_id: UUID, session_id: UUID, *, from_seq: int = 1, limit: int = 1000
    ) -> tuple[LedgerEvent, ...]:
        return tuple(
            event
            for event in self.events
            if event.workspace_id == workspace_id
            and event.session_id == session_id
            and from_seq <= event.ledger_seq
        )[:limit]

    async def verify(self, workspace_id: UUID, session_id: UUID) -> LedgerVerification:
        return self.verification


class FakeAccessLog:
    """In-memory `AccessLogRepository` matching the adapter's filter semantics."""

    def __init__(self) -> None:
        self.entries: list[AccessLogEntry] = []
        self.creation_times: dict[UUID, datetime] = {}

    async def record(self, entry: AccessLogEntry) -> None:
        self.entries.append(entry)

    async def list_for_resource(
        self,
        workspace_id: UUID,
        *,
        resource_kind: AuditResourceKind,
        resource_id: UUID,
        session_id: UUID | None = None,
        before: datetime | None = None,
        result: AccessResult | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[tuple[AccessLogEntry, ...], str | None]:
        _ = cursor
        matching = [
            entry
            for entry in sorted(self.entries, key=lambda item: (item.recorded_at, item.id))
            if entry.workspace_id == workspace_id
            and entry.resource_kind == resource_kind
            and entry.resource_id == resource_id
            and (session_id is None or entry.session_id == session_id)
            and (before is None or entry.recorded_at < before)
            and (result is None or entry.result is result)
        ]
        page = matching[:limit]
        next_cursor = (
            access_cursor_encode(page[-1].recorded_at, page[-1].id)
            if len(matching) > limit
            else None
        )
        return tuple(page), next_cursor

    async def recommendation_created_at(
        self,
        workspace_id: UUID,
        recommendation_id: UUID,
        *,
        session_id: UUID | None = None,
    ) -> datetime | None:
        del workspace_id, session_id
        return self.creation_times.get(recommendation_id)


class FakeAnchors:
    """In-memory `AuditAnchorRepository` with same-day append-only semantics."""

    def __init__(self) -> None:
        self.anchors: dict[tuple[UUID, UUID], list[AuditAnchor]] = {}

    async def latest(self, workspace_id: UUID, session_id: UUID) -> AuditAnchor | None:
        values = self.anchors.get((workspace_id, session_id), [])
        return values[-1] if values else None

    async def all(self, workspace_id: UUID, session_id: UUID) -> tuple[AuditAnchor, ...]:
        return tuple(self.anchors.get((workspace_id, session_id), []))

    async def publish(self, anchor: AuditAnchor) -> AuditAnchor:
        values = self.anchors.setdefault((anchor.workspace_id, anchor.session_id), [])
        if any(existing.anchor_day == anchor.anchor_day for existing in values):
            raise AuditConflictError("anchor for the same session-day already exists")
        values.append(anchor)
        return anchor


class FakeParticipants:
    """In-memory `SessionParticipantReader`."""

    def __init__(self, *values: SessionParticipant) -> None:
        self.values = values

    async def participants(
        self, workspace_id: UUID, session_id: UUID
    ) -> tuple[SessionParticipant, ...]:
        return self.values


class FakeLifecycle:
    """In-memory `SessionLifecycleStore` for query service tests."""

    def __init__(self, value: SessionLifecycle | None = None) -> None:
        self.value = value

    async def add_draft(
        self, workspace_id: UUID, session_id: UUID, *, created_at: datetime
    ) -> SessionLifecycle:
        raise NotImplementedError

    async def get(self, workspace_id: UUID, session_id: UUID) -> SessionLifecycle | None:
        return self.value

    async def attach_workflow(
        self, workspace_id: UUID, session_id: UUID, *, workflow_id: str, run_id: str
    ) -> SessionLifecycle:
        raise NotImplementedError

    async def transition(self, command: SessionTransition) -> SessionLifecycle:
        raise NotImplementedError


class FakeConsensus:
    """In-memory `ConsensusResultStore` with round-indexed lookups."""

    def __init__(self) -> None:
        self.records: list[ConsensusRunRecord] = []
        self.explanations: dict[UUID, ConsensusExplanation] = {}

    async def add_result(self, record: ConsensusRunRecord) -> None:
        self.records.append(record)

    async def get_result(self, workspace_id: UUID, result_id: UUID) -> ConsensusRunRecord | None:
        for record in self.records:
            if record.id == result_id:
                return record
        return None

    async def list_results(
        self, workspace_id: UUID, session_id: UUID, *, strategy: str | None = None
    ) -> tuple[ConsensusRunRecord, ...]:
        return tuple(self.records)

    async def get_round_result(
        self,
        workspace_id: UUID,
        session_id: UUID,
        *,
        round: int,
    ) -> ConsensusRunRecord | None:
        for record in self.records:
            if record.session_id == session_id and record.round == round:
                return record
        return None

    async def add_explanation(
        self, workspace_id: UUID, result_id: UUID, explanation: ConsensusExplanation
    ) -> None:
        return None

    async def get_explanation(
        self, workspace_id: UUID, result_id: UUID
    ) -> ConsensusExplanation | None:
        return self.explanations.get(result_id)


class FakeArtifacts:
    """In-memory `Phase3ArtifactStore`."""

    def __init__(self, *values: ReasoningArtifact) -> None:
        self.values = {value.id: value for value in values}

    async def add(self, artifact: ReasoningArtifact) -> None:
        self.values[artifact.id] = artifact

    async def get_for_update(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> ReasoningArtifact | None:
        artifact = self.values.get(artifact_id)
        if artifact is None or artifact.workspace_id != workspace_id:
            return None
        return artifact

    async def set_lifecycle(
        self,
        workspace_id: UUID,
        session_id: UUID,
        artifact_id: UUID,
        status: LifecycleStatus,
        *,
        updated_at: datetime,
    ) -> None:
        return None

    async def lock_agent_turn(self, workspace_id: UUID, session_id: UUID, turn_id: UUID) -> None:
        return None

    async def get(
        self, workspace_id: UUID, artifact_id: UUID, *, session_id: UUID | None = None
    ) -> ReasoningArtifact | None:
        artifact = self.values.get(artifact_id)
        if artifact is None or artifact.workspace_id != workspace_id:
            return None
        return artifact


class MissingNodeGraph:
    """A graph whose every artifact has no provenance root (provenance None)."""

    async def node_for_artifact(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> GraphNode | None:
        return None


def _query_service(
    *,
    ledger: FakeLedger,
    artifacts: FakeArtifacts | None = None,
    consensus: FakeConsensus | None = None,
    lifecycle: FakeLifecycle | None = None,
    participants: tuple[SessionParticipant, ...] = (),
) -> AuditQueryService:
    artifacts = artifacts or FakeArtifacts()
    provenance = ProvenanceService(
        artifacts=artifacts,
        graph=cast(ReasoningGraphStore, MissingNodeGraph()),
        citations=cast(CitationRepository, object()),
    )
    return AuditQueryService(
        artifacts=artifacts,
        consensus=consensus or FakeConsensus(),
        lifecycle=lifecycle or FakeLifecycle(),
        participants=FakeParticipants(*participants),
        provenance=provenance,
        ledger=ledger,
    )


# ---------------------------------------------------------------------------
# Access log value objects and cursors
# ---------------------------------------------------------------------------


@req("FR-807", "NFR-006")
def test_access_log_entry_rejects_blank_scope_and_blank_trace() -> None:
    data = _log_entry().model_dump()
    data.pop("scope_ids")
    with pytest.raises(ValueError, match="scope_ids"):
        AccessLogEntry(**data, scope_ids=(" ",))
    data = _log_entry().model_dump()
    data.pop("trace_id")
    with pytest.raises(ValueError, match="trace_id"):
        AccessLogEntry(**data, trace_id="   ")


@req("FR-807", "NFR-006")
def test_access_cursor_round_trip_and_garbage() -> None:
    timestamp = datetime(2026, 9, 5, 12, 30, 45, 123456, tzinfo=UTC)
    entry_id = uuid4()
    cursor = access_cursor_encode(timestamp, entry_id)
    decoded_at, decoded_id = access_cursor_decode(cursor)
    assert decoded_at == timestamp.astimezone(UTC)
    assert decoded_id == entry_id
    with pytest.raises((ValueError, binascii.Error)):
        access_cursor_decode("not-base64!!")


# ---------------------------------------------------------------------------
# Audit anchors — Q8 backing
# ---------------------------------------------------------------------------


@req("FR-807", "NFR-006")
def test_anchor_hash_is_deterministic_and_precedes_with_genesis() -> None:
    first = AuditAnchor.publish(
        workspace_id=WS,
        session_id=SESSION,
        anchor_day=DAY1.date(),
        head_seq=3,
        head_hash="sha256:" + "a" * 64,
        anchored_at=NOW,
    )
    second = AuditAnchor.publish(
        workspace_id=WS,
        session_id=SESSION,
        anchor_day=DAY1.date(),
        head_seq=3,
        head_hash="sha256:" + "a" * 64,
        anchored_at=NOW,
    )
    assert second.anchor_hash == first.anchor_hash
    assert second.head_seq == first.head_seq
    assert first.anchor_hash == audit_anchor_hash(first)
    assert first.prev_head_hash == GENESIS_HASH

    different = AuditAnchor.publish(
        workspace_id=WS,
        session_id=SESSION,
        anchor_day=DAY1.date(),
        head_seq=3,
        head_hash="sha256:" + "b" * 64,
    )
    assert different.anchor_hash != first.anchor_hash


@req("FR-807", "NFR-006")
def test_anchor_rejects_mismatched_hash_on_construction() -> None:
    with pytest.raises(ValueError, match="anchor_hash does not match"):
        AuditAnchor(
            workspace_id=WS,
            session_id=SESSION,
            anchor_day=DAY1.date(),
            head_seq=3,
            head_hash="sha256:" + "a" * 64,
            prev_head_hash=GENESIS_HASH,
            anchor_hash="sha256:" + "c" * 64,
            anchored_at=NOW,
        )


@req("FR-807", "NFR-006")
async def test_daily_anchor_publishing_requires_events() -> None:
    service = ChainVerificationService(FakeAnchors(), FakeLedger())
    with pytest.raises(AuditVerificationError, match="no ledger events"):
        await service.publish_daily_anchor(WS, SESSION, anchor_day=DAY1.date())


@req("FR-807", "NFR-006")
async def test_chain_integrity_verifies_two_day_record() -> None:
    day1_a = _event(
        event_id=uuid4(),
        seq=1,
        event_type="AGENT_TURN_COMPLETED",
        recorded_at=DAY1,
        round=1,
    )
    day1_b = _event(
        event_id=uuid4(),
        seq=2,
        event_type="ARTIFACT_COMMITTED",
        recorded_at=DAY1 + timedelta(hours=1),
        round=1,
    )
    day2_c = _event(
        event_id=uuid4(),
        seq=3,
        event_type="ARTIFACT_COMMITTED",
        recorded_at=DAY2,
        round=2,
    )
    anchors = FakeAnchors()
    ledger = FakeLedger([day1_a, day1_b, day2_c])
    service = ChainVerificationService(anchors, ledger)

    anchor1 = await service.publish_daily_anchor(WS, SESSION, anchor_day=DAY1.date())
    anchor2 = await service.publish_daily_anchor(WS, SESSION, anchor_day=DAY2.date())
    assert anchor1.head_seq == 2
    assert anchor1.head_hash == day1_b.event_hash
    assert anchor1.prev_head_hash == GENESIS_HASH
    assert anchor2.prev_head_hash == anchor1.head_hash
    assert anchor2.head_seq == 3

    report = await service.chain_integrity(WS, SESSION)
    assert report.chain_valid is True
    assert report.first_invalid_day is None
    assert len(report.anchors) == 2
    assert all(item.valid for item in report.anchors)
    assert report.event_count == 3


@req("FR-807", "NFR-006")
async def test_chain_integrity_detects_altered_day_head() -> None:
    original = _event(
        event_id=uuid4(),
        seq=2,
        event_type="ARTIFACT_COMMITTED",
        recorded_at=DAY1 + timedelta(hours=1),
        payload={"artifact_id": str(uuid4()), "kind": "CLAIM", "version": 1},
    )
    day2_c = _event(event_id=uuid4(), seq=3, event_type="ARTIFACT_COMMITTED", recorded_at=DAY2)
    anchors = FakeAnchors()
    ledger = FakeLedger([original, day2_c])
    service = ChainVerificationService(anchors, ledger)
    await service.publish_daily_anchor(WS, SESSION, anchor_day=DAY1.date())

    forged = _event(
        event_id=original.id,
        seq=original.ledger_seq,
        event_type="ARTIFACT_COMMITTED",
        recorded_at=DAY1 + timedelta(hours=1),
        payload={"artifact_id": str(uuid4()), "kind": "CLAIM", "version": 1},
    )
    assert forged.event_hash != original.event_hash
    ledger.events[0] = forged

    report = await service.chain_integrity(WS, SESSION)
    assert report.chain_valid is False
    assert report.first_invalid_day == DAY1.date()
    assert report.anchors[0].valid is False
    assert report.anchors[0].reason is not None


@req("FR-807", "NFR-006")
async def test_chain_integrity_reports_invalid_ledger_verification() -> None:
    ledger = FakeLedger([_event(event_id=uuid4(), seq=1, event_type="AGENT_TURN_COMPLETED")])
    ledger.verification = LedgerVerification(
        valid=False,
        event_count=1,
        head_hash="sha256:" + "2" * 64,
        first_invalid_seq=1,
        reason="prev_hash does not continue the chain",
    )
    service = ChainVerificationService(FakeAnchors(), ledger)
    report = await service.chain_integrity(WS, SESSION)
    assert report.chain_valid is False
    assert report.ledger_verification.valid is False


# ---------------------------------------------------------------------------
# Q7 — recommendation access
# ---------------------------------------------------------------------------


@req("FR-807", "NFR-006")
async def test_recommendation_access_unknown_recommendation() -> None:
    access = FakeAccessLog()
    report = await AccessAuditService(access).recommendation_access(WS, uuid4())
    assert report.recommendation_known is False
    assert report.complete_timeline is False
    assert report.why_incomplete == "recommendation is not recorded for this session"
    assert report.entries == ()


@req("FR-807", "NFR-006")
async def test_recommendation_access_filters_reads_before_creation() -> None:
    recommendation_id = uuid4()
    created_at = NOW
    access = FakeAccessLog()
    access.creation_times[recommendation_id] = created_at
    expected = _log_entry(
        recorded_at=created_at - timedelta(hours=1), resource_id=recommendation_id
    )
    await access.record(expected)
    await access.record(
        _log_entry(recorded_at=created_at + timedelta(hours=1), resource_id=recommendation_id)
    )
    await access.record(_log_entry(recorded_at=created_at - timedelta(hours=1)))

    report = await AccessAuditService(access).recommendation_access(WS, recommendation_id)
    assert report.recommendation_known is True
    assert report.complete_timeline is True
    assert report.truncated is False
    assert [entry.id for entry in report.entries] == [expected.id]


@req("FR-807", "NFR-006")
async def test_recommendation_access_truncation_reports_cursor() -> None:
    recommendation_id = uuid4()
    created_at = NOW
    access = FakeAccessLog()
    access.creation_times[recommendation_id] = created_at
    for offset in range(3):
        await access.record(
            _log_entry(
                recorded_at=created_at - timedelta(hours=3 - offset),
                resource_id=recommendation_id,
            )
        )

    report = await AccessAuditService(access).recommendation_access(WS, recommendation_id, limit=2)
    assert report.truncated is True
    assert report.next_cursor is not None
    assert len(report.entries) == 2
    assert report.complete_timeline is False

    continued = await AccessAuditService(access).recommendation_access(
        WS, recommendation_id, limit=2, cursor=report.next_cursor
    )
    assert continued.complete_timeline is False


# ---------------------------------------------------------------------------
# Q1..Q6 — audit query service
# ---------------------------------------------------------------------------


@req("FR-807", "NFR-006")
async def test_artifact_rationale_finds_originating_turn() -> None:
    artifact = _artifact()
    turn = _event(
        event_id=uuid4(),
        seq=1,
        event_type="AGENT_TURN_COMPLETED",
        round=1,
        recorded_at=DAY1,
        payload={"turn_id": str(uuid4()), "artifact_ids": [str(artifact.id)], "proposal_count": 1},
    )
    committed = _event(
        event_id=uuid4(),
        seq=2,
        event_type="ARTIFACT_COMMITTED",
        round=1,
        recorded_at=DAY1 + timedelta(minutes=1),
        causation_id=turn.id,
        payload={"artifact_id": str(artifact.id), "kind": "CLAIM", "version": 1},
    )
    service = _query_service(
        ledger=FakeLedger([turn, committed]), artifacts=FakeArtifacts(artifact)
    )
    report = await service.artifact_rationale(WS, artifact.id)
    assert report is not None
    assert report.session_id == SESSION
    assert report.provenance is None
    assert report.committed_by_event == committed
    assert report.originating_turn_event == turn


@req("FR-807", "NFR-006")
async def test_artifact_rationale_handles_broken_causation_chain() -> None:
    artifact = _artifact()
    committed = _event(
        event_id=uuid4(),
        seq=1,
        event_type="ARTIFACT_COMMITTED",
        round=1,
        causation_id=uuid4(),
        payload={"artifact_id": str(artifact.id), "kind": "CLAIM", "version": 1},
    )
    service = _query_service(ledger=FakeLedger([committed]), artifacts=FakeArtifacts(artifact))
    report = await service.artifact_rationale(WS, artifact.id)
    assert report is not None
    assert report.committed_by_event == committed
    assert report.originating_turn_event is None


@req("FR-807", "NFR-006")
async def test_artifact_rationale_missing_artifact_is_none() -> None:
    service = _query_service(ledger=FakeLedger())
    assert await service.artifact_rationale(WS, uuid4()) is None


@req("FR-807", "NFR-006")
async def test_artifact_revision_history_orders_writes_and_keeps_warrants() -> None:
    artifact_id = uuid4()
    committed_id = uuid4()
    revised_id = uuid4()
    warrant_id = uuid4()
    events = [
        _event(
            event_id=committed_id,
            seq=1,
            event_type="ARTIFACT_COMMITTED",
            round=1,
            payload={
                "artifact_id": str(artifact_id),
                "kind": "CLAIM",
                "logical_id": str(uuid4()),
                "version": 1,
            },
        ),
        _event(
            event_id=revised_id,
            seq=2,
            event_type="ARTIFACT_REVISED",
            round=2,
            payload={
                "artifact_id": str(artifact_id),
                "kind": "CLAIM",
                "version": 2,
                "supersedes_id": str(committed_id),
                "warrant_artifact_ids": [str(warrant_id)],
            },
        ),
        _event(event_id=uuid4(), seq=3, event_type="AGENT_TURN_COMPLETED", round=2),
        _event(
            event_id=uuid4(),
            seq=4,
            event_type="ARTIFACT_WITHDRAWN",
            round=3,
            payload={
                "artifact_id": str(artifact_id),
                "kind": "CLAIM",
                "version": 3,
                "supersedes_id": str(revised_id),
            },
        ),
    ]
    service = _query_service(ledger=FakeLedger(events))
    history = await service.artifact_revision_history(WS, SESSION, artifact_id)
    assert [revision.version for revision in history.revisions] == [1, 2, 3]
    assert [revision.event_type for revision in history.revisions] == [
        "ARTIFACT_COMMITTED",
        "ARTIFACT_REVISED",
        "ARTIFACT_WITHDRAWN",
    ]
    assert history.revisions[1].warrant_artifact_ids == (warrant_id,)
    assert history.revisions[1].supersedes_id == committed_id
    assert all(revision.actor_class is ActorClass.AGENT for revision in history.revisions)


@req("FR-807", "NFR-006")
async def test_artifact_revision_history_defaults_version_when_absent() -> None:
    artifact_id = uuid4()
    event = _event(
        event_id=uuid4(),
        seq=1,
        event_type="ARTIFACT_COMMITTED",
        payload={"artifact_id": str(artifact_id), "kind": "CLAIM", "logical_id": str(uuid4())},
    )
    service = _query_service(ledger=FakeLedger([event]))
    history = await service.artifact_revision_history(WS, SESSION, artifact_id)
    assert len(history.revisions) == 1
    assert history.revisions[0].version == 1


@req("FR-807", "NFR-006")
async def test_round_participant_context_filters_turns_by_round() -> None:
    turn2 = _event(event_id=uuid4(), seq=1, event_type="AGENT_TURN_COMPLETED", round=2)
    turn3 = _event(event_id=uuid4(), seq=2, event_type="AGENT_TURN_COMPLETED", round=3)
    lifecycle = SessionLifecycle(
        workspace_id=WS,
        session_id=SESSION,
        state=SessionLifecycleState.RUNNING,
        round=3,
        initialized_at=NOW,
        started_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    participants = (_participant("a"), _participant("b"))
    service = _query_service(
        ledger=FakeLedger([turn2, turn3]),
        lifecycle=FakeLifecycle(lifecycle),
        participants=participants,
    )
    report = await service.round_participant_context(WS, SESSION, round=2)
    assert report is not None
    assert report.round == 2
    assert report.participants == participants
    assert [event.id for event in report.turn_events] == [turn2.id]

    with pytest.raises(ValueError, match="round must not be negative"):
        await service.round_participant_context(WS, SESSION, round=-1)


@req("FR-807", "NFR-006")
async def test_round_participant_context_missing_session_is_none() -> None:
    service = _query_service(ledger=FakeLedger())
    assert await service.round_participant_context(WS, SESSION, round=1) is None


@req("FR-807", "NFR-006")
async def test_round_consensus_record_lookup() -> None:
    consensus = FakeConsensus()
    await consensus.add_result(_consensus_record(round=3))
    service = _query_service(ledger=FakeLedger(), consensus=consensus)
    record = await service.round_consensus_record(WS, SESSION, round=3)
    assert record is not None
    assert record.session_id == SESSION
    assert record.round == 3
    assert await service.round_consensus_record(WS, SESSION, round=4) is None
    with pytest.raises(ValueError, match="round must be a positive"):
        await service.round_consensus_record(WS, SESSION, round=0)


@req("FR-807", "NFR-006")
async def test_round_consensus_explanation_returns_exact_persisted_pair() -> None:
    consensus = FakeConsensus()
    record = _consensus_record(round=2)
    explanation = ConsensusExplanation(
        consensus_id=record.id,
        outcome=record.outcome,
        strategy=record.strategy,
        strategy_version=record.strategy_version,
        formula="persisted",
        input_hash=record.input_hash,
    )
    await consensus.add_result(record)
    consensus.explanations = {record.id: explanation}
    service = _query_service(ledger=FakeLedger(), consensus=consensus)
    assert await service.round_consensus_explanation(WS, SESSION, round=2) == (
        record,
        explanation,
    )


@req("FR-807", "NFR-006")
async def test_session_termination_reports_final_state_and_last_event() -> None:
    last = _event(event_id=uuid4(), seq=1, event_type="AGENT_TURN_COMPLETED")
    lifecycle = SessionLifecycle(
        workspace_id=WS,
        session_id=SESSION,
        state=SessionLifecycleState.PARTIAL_CONSENSUS_STATE,
        round=2,
        initialized_at=NOW,
        started_at=NOW,
        ended_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    service = _query_service(ledger=FakeLedger([last]), lifecycle=FakeLifecycle(lifecycle))
    report = await service.session_termination(WS, SESSION)
    assert report is not None
    assert report.final_state is SessionLifecycleState.PARTIAL_CONSENSUS_STATE
    assert report.final_round == 2
    assert report.ended_at == NOW
    assert report.last_event == last

    missing = _query_service(ledger=FakeLedger())
    assert await missing.session_termination(WS, SESSION) is None


@req("FR-807", "NFR-006")
async def test_strategy_usage_maps_consensus_record() -> None:
    consensus = FakeConsensus()
    record = _consensus_record(round=1)
    await consensus.add_result(record)
    service = _query_service(ledger=FakeLedger(), consensus=consensus)
    report = await service.strategy_usage(WS, SESSION, round=1)
    assert report is not None
    assert report.strategy == "weighted"
    assert report.strategy_version == "1.0.0"
    assert report.outcome is ConsensusOutcome.PARTIAL_CONSENSUS
    assert report.pareto_set == record.pareto_set
    assert report.input_hash == record.input_hash
    assert await service.strategy_usage(WS, SESSION, round=2) is None
