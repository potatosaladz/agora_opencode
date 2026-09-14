"""Application services implementing AUDITABILITY.md §5 for Phase 13 (T13-02).

Three callers compose the eight-question surface:

- :class:`AccessAuditService` — records audited reads and answers Q7.
- :class:`ChainVerificationService` — publishes daily anchors and verifies the
  ledger + anchor chain, answering Q8.
- :class:`AuditQueryService` — Q1..Q6 from existing durable stores (provenance,
  ledger, lifecycle, consensus results, session participants).

No new events are emitted; every answer is derived from runtime facts.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import UUID

from app.application.provenance import ProvenanceService
from app.domain.audit import (
    AccessLogEntry,
    AccessLogRepository,
    AccessResult,
    AnchorVerification,
    ArtifactRationaleTrace,
    ArtifactRevision,
    ArtifactRevisionHistory,
    AuditAnchor,
    AuditAnchorRepository,
    AuditResourceKind,
    AuditVerificationError,
    ChainVerificationReport,
    RecommendationAccessReport,
    RoundContextReport,
    SessionParticipantReader,
    SessionTerminationReport,
    StrategyUsageReport,
    audit_anchor_hash,
)
from app.domain.consensus import ConsensusResultStore, ConsensusRunRecord
from app.domain.dissent import DissentConsensusExplanationReader
from app.domain.phase3_api import Phase3ArtifactStore
from app.domain.reasoning_ledger import GENESIS_HASH, LedgerEvent, ReasoningLedger
from app.domain.session_lifecycle import SessionLifecycleStore
from app.ports.consensus import ConsensusExplanation

__all__ = [
    "AccessAuditService",
    "AuditQueryService",
    "ChainVerificationService",
]

_MAX_EVENT_SCAN = 100_000
_MAX_CAUSATION_HOPS = 32
_ARTIFACT_EVENT_TYPES = frozenset({"ARTIFACT_COMMITTED", "ARTIFACT_REVISED", "ARTIFACT_WITHDRAWN"})


# trace: FR-807, NFR-006
class AccessAuditService:
    """Q7 backing: append audited reads and answer who saw a recommendation."""

    def __init__(self, access: AccessLogRepository) -> None:
        self._access = access

    async def record(self, entry: AccessLogEntry) -> AccessLogEntry:
        """Append one audited read inside the caller's transaction (FR-807/NFR-006)."""
        await self._access.record(entry)
        return entry

    async def recommendation_access(
        self,
        workspace_id: UUID,
        recommendation_id: UUID,
        *,
        session_id: UUID | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> RecommendationAccessReport:
        """Q7: every read of the recommendation strictly before it was accepted."""
        created_at = await self._access.recommendation_created_at(
            workspace_id, recommendation_id, session_id=session_id
        )
        before = created_at if created_at is not None else None
        entries, next_cursor = await self._access.list_for_resource(
            workspace_id,
            resource_kind=AuditResourceKind.RECOMMENDATION,
            resource_id=recommendation_id,
            before=before,
            result=AccessResult.ALLOWED,
            limit=limit,
            cursor=cursor,
        )
        known = created_at is not None
        truncated = next_cursor is not None
        return RecommendationAccessReport(
            workspace_id=workspace_id,
            recommendation_id=recommendation_id,
            recommendation_known=known,
            recommendation_created_at=created_at,
            session_id=session_id if known else None,
            entries=entries,
            complete_timeline=known and not truncated and cursor is None,
            why_incomplete=None if known else "recommendation is not recorded for this session",
            truncated=truncated,
            next_cursor=next_cursor,
        )


class ChainVerificationService:
    """Q8 backing: publish a session-day anchor and verify the full chain."""

    def __init__(self, anchors: AuditAnchorRepository, ledger: ReasoningLedger) -> None:
        self._anchors = anchors
        self._ledger = ledger

    async def publish_daily_anchor(
        self,
        workspace_id: UUID,
        session_id: UUID,
        *,
        anchor_day: date | None = None,
    ) -> AuditAnchor:
        """Anchor the last event on or before *anchor_day* (default: today, UTC).

        Append-only: a second anchor for the same session-day is a conflict.
        """
        day = anchor_day or datetime.now(UTC).date()
        events = await self._ledger.read(workspace_id, session_id, limit=_MAX_EVENT_SCAN)
        day_head = _last_event_at_or_before(events, day)
        if day_head is None:
            raise AuditVerificationError(
                f"session {session_id} has no ledger events on or before {day.isoformat()}"
            )
        previous = await self._anchors.latest(workspace_id, session_id)
        prev_head_hash = previous.head_hash if previous is not None else GENESIS_HASH
        anchor = AuditAnchor.publish(
            workspace_id=workspace_id,
            session_id=session_id,
            anchor_day=day,
            head_seq=day_head.ledger_seq,
            head_hash=day_head.event_hash,
            prev_head_hash=prev_head_hash,
        )
        return await self._anchors.publish(anchor)

    async def chain_integrity(
        self, workspace_id: UUID, session_id: UUID
    ) -> ChainVerificationReport:
        """Q8: verify the event chain and every published anchor for a session."""
        events = await self._ledger.read(workspace_id, session_id, limit=_MAX_EVENT_SCAN)
        ledger_verification = await self._ledger.verify(workspace_id, session_id)
        anchors = await self._anchors.all(workspace_id, session_id)

        expected_prev = GENESIS_HASH
        previous_day: date | None = None
        previous_seq = 0
        first_invalid_day: date | None = None
        chain_valid = ledger_verification.valid
        verified: list[AnchorVerification] = []
        for anchor in anchors:
            valid, reason = _verify_anchor(
                anchor,
                events,
                expected_prev=expected_prev,
                previous_day=previous_day,
                previous_seq=previous_seq,
            )
            if not valid:
                first_invalid_day = anchor.anchor_day
                chain_valid = False
            verified.append(AnchorVerification(anchor=anchor, valid=valid, reason=reason))
            expected_prev = anchor.head_hash
            previous_day = anchor.anchor_day
            previous_seq = anchor.head_seq

        return ChainVerificationReport(
            workspace_id=workspace_id,
            session_id=session_id,
            event_count=len(events),
            ledger_verification=ledger_verification,
            anchors=tuple(verified),
            first_invalid_day=first_invalid_day,
            chain_valid=chain_valid,
        )


class AuditQueryService:
    """Q1..Q6: one typed query each, assembled from existing durable stores."""

    def __init__(
        self,
        artifacts: Phase3ArtifactStore,
        consensus: ConsensusResultStore,
        lifecycle: SessionLifecycleStore,
        participants: SessionParticipantReader,
        provenance: ProvenanceService,
        ledger: ReasoningLedger,
        explanations: DissentConsensusExplanationReader | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._consensus = consensus
        self._lifecycle = lifecycle
        self._participants = participants
        self._provenance = provenance
        self._ledger = ledger
        self._explanations = explanations

    async def artifact_rationale(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
        *,
        max_depth: int = 8,
        page_size: int = 50,
        cursor: str | None = None,
    ) -> ArtifactRationaleTrace | None:
        """Q1: why is this claim in the record, and which turn produced it?"""
        artifact = await self._artifacts.get(workspace_id, artifact_id)
        if artifact is None:
            return None
        provenance = await self._provenance.provenance_of(
            workspace_id,
            artifact_id,
            max_depth=max_depth,
            page_size=page_size,
            cursor=cursor,
        )
        events = await self._ledger.read(workspace_id, artifact.session_id, limit=_MAX_EVENT_SCAN)
        committed = _first_write_event(events, artifact_id)
        turn = _originating_turn(events, committed)
        return ArtifactRationaleTrace(
            workspace_id=workspace_id,
            artifact_id=artifact_id,
            session_id=artifact.session_id,
            provenance=provenance,
            committed_by_event=committed,
            originating_turn_event=turn,
        )

    async def artifact_revision_history(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> ArtifactRevisionHistory:
        """Q2: every ledger write of this artifact, with actor and warrant."""
        events = await self._ledger.read(workspace_id, session_id, limit=_MAX_EVENT_SCAN)
        revisions = tuple(
            ArtifactRevision(
                version=int(event.payload["version"]) if "version" in event.payload else 1,
                event_id=event.id,
                ledger_seq=event.ledger_seq,
                round=event.round,
                event_type=event.event_type,
                actor_class=event.actor_class,
                actor_id=event.actor_id,
                recorded_at=event.recorded_at,
                supersedes_id=_payload_uuid(event, "supersedes_id"),
                warrant_artifact_ids=_payload_uuids(event, "warrant_artifact_ids"),
            )
            for event in _artifact_write_events(events, artifact_id)
        )
        return ArtifactRevisionHistory(
            artifact_id=artifact_id, session_id=session_id, revisions=revisions
        )

    async def round_participant_context(
        self, workspace_id: UUID, session_id: UUID, *, round: int
    ) -> RoundContextReport | None:
        """Q3: which agents were bound and which turns completed at round *n*."""
        if round < 0:
            raise ValueError("round must not be negative")
        lifecycle = await self._lifecycle.get(workspace_id, session_id)
        if lifecycle is None:
            return None
        participants = await self._participants.participants(workspace_id, session_id)
        events = await self._ledger.read(workspace_id, session_id, limit=_MAX_EVENT_SCAN)
        turns = tuple(
            event
            for event in events
            if event.event_type == "AGENT_TURN_COMPLETED" and event.round == round
        )
        return RoundContextReport(
            round=round, session_id=session_id, participants=participants, turn_events=turns
        )

    async def round_consensus_record(
        self, workspace_id: UUID, session_id: UUID, *, round: int
    ) -> ConsensusRunRecord | None:
        """Q4: the round's consensus result, whose record carries all positions."""
        if round < 1:
            raise ValueError("round must be a positive number")
        return await self._consensus.get_round_result(workspace_id, session_id, round=round)

    async def round_consensus_explanation(
        self, workspace_id: UUID, session_id: UUID, *, round: int
    ) -> tuple[ConsensusRunRecord, ConsensusExplanation | None] | None:
        """Q4/Q6 support: exact persisted round result plus its explanation."""
        record = await self.round_consensus_record(workspace_id, session_id, round=round)
        if record is None:
            return None
        explanation = (
            await self._explanations.get(workspace_id, record.id)
            if self._explanations is not None
            else await self._consensus.get_explanation(workspace_id, record.id)
        )
        return record, explanation

    async def session_termination(
        self, workspace_id: UUID, session_id: UUID
    ) -> SessionTerminationReport | None:
        """Q5: why the session ended, from the lifecycle projection and the ledger tail."""
        lifecycle = await self._lifecycle.get(workspace_id, session_id)
        if lifecycle is None:
            return None
        events = await self._ledger.read(workspace_id, session_id, limit=_MAX_EVENT_SCAN)
        last_event = events[-1] if events else None
        return SessionTerminationReport(
            workspace_id=workspace_id,
            session_id=session_id,
            final_state=lifecycle.state,
            final_round=lifecycle.round,
            ended_at=lifecycle.ended_at,
            last_event=last_event,
        )

    async def strategy_usage(
        self, workspace_id: UUID, session_id: UUID, *, round: int
    ) -> StrategyUsageReport | None:
        """Q6: which strategy and inputs produced the round's ranking."""
        record = await self.round_consensus_record(workspace_id, session_id, round=round)
        if record is None:
            return None
        return StrategyUsageReport(
            workspace_id=record.workspace_id,
            session_id=record.session_id,
            round=record.round,
            strategy=record.strategy,
            strategy_version=record.strategy_version,
            input_hash=record.input_hash,
            outcome=record.outcome,
            conditions=record.conditions,
            pareto_set=record.pareto_set,
            created_at=record.created_at,
        )


def _originating_turn(
    events: Sequence[LedgerEvent], event: LedgerEvent | None
) -> LedgerEvent | None:
    """Walk the causation chain from an event to its originating agent turn."""
    if event is None:
        return None
    by_id = {candidate.id: candidate for candidate in events}
    current: LedgerEvent | None = event
    seen: set[UUID] = set()
    hops = 0
    while current is not None and current.causation_id is not None:
        if current.id in seen or hops >= _MAX_CAUSATION_HOPS:
            return None
        seen.add(current.id)
        hops += 1
        current = by_id.get(current.causation_id)
        if current is None:
            return None
        if current.event_type == "AGENT_TURN_COMPLETED":
            return current
    return None


def _last_event_at_or_before(events: Sequence[LedgerEvent], day: date) -> LedgerEvent | None:
    day_events = [event for event in events if event.recorded_at.date() <= day]
    return day_events[-1] if day_events else None


def _first_write_event(events: Sequence[LedgerEvent], artifact_id: UUID) -> LedgerEvent | None:
    target = str(artifact_id)
    for event in events:
        if event.event_type == "ARTIFACT_COMMITTED" and event.payload.get("artifact_id") == target:
            return event
    return None


def _artifact_write_events(
    events: Sequence[LedgerEvent], artifact_id: UUID
) -> tuple[LedgerEvent, ...]:
    target = str(artifact_id)
    return tuple(
        event
        for event in events
        if event.event_type in _ARTIFACT_EVENT_TYPES and event.payload.get("artifact_id") == target
    )


def _payload_uuid(event: LedgerEvent, key: str) -> UUID | None:
    value = event.payload.get(key)
    return UUID(str(value)) if value is not None else None


def _payload_uuids(event: LedgerEvent, key: str) -> tuple[UUID, ...]:
    values = event.payload.get(key)
    return tuple(UUID(str(value)) for value in values) if values else ()


def _verify_anchor(
    anchor: AuditAnchor,
    events: Sequence[LedgerEvent],
    *,
    expected_prev: str,
    previous_day: date | None,
    previous_seq: int,
) -> tuple[bool, str | None]:
    if anchor.anchor_hash != audit_anchor_hash(anchor):
        return False, "anchor_hash does not match the anchor facts"
    if anchor.prev_head_hash != expected_prev:
        return False, "prev_head_hash does not continue the anchor chain"
    if previous_day is not None and anchor.anchor_day <= previous_day:
        return False, "anchor_day is not strictly increasing"
    if previous_seq and anchor.head_seq <= previous_seq:
        return False, "anchor head_seq is not strictly increasing"
    day_events = [event for event in events if event.recorded_at.date() <= anchor.anchor_day]
    day_head = day_events[-1] if day_events else None
    if day_head is None:
        return False, "no ledger events on or before the anchor day"
    if day_head.ledger_seq != anchor.head_seq or day_head.event_hash != anchor.head_hash:
        return False, "anchor head does not match the stored day-head"
    return True, None
