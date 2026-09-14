"""Phase 13 audit domain contracts (T13-02): access log, daily anchors, eight queries.

Implements the persistent half of `docs/AUDITABILITY.md` §4 and §5 for FR-807/NFR-006:

- ``AccessLogEntry`` is the audited-read record that answers Q7 (who saw what).
- ``AuditAnchor`` binds a session-day's reasoning-ledger head to a self-authenticating
  hash so the nightly chain job can answer Q8 (has anything been altered).
- The eight query result models are immutable value objects (``FrozenModel``),
  never persistence entities, and always scoped to workspace and session.
"""

from __future__ import annotations

import base64
import ipaddress
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from app.domain.agent_registry import AgentRoleKind
from app.domain.consensus import ConsensusOutcome
from app.domain.provenance import ProvenanceResult
from app.domain.reasoning import ActorClass, FrozenModel, content_hash
from app.domain.reasoning_ledger import GENESIS_HASH, LedgerEvent, LedgerVerification
from app.domain.session_lifecycle import SessionLifecycleState

__all__ = [
    "AccessAuditError",
    "AccessLogEntry",
    "AccessLogRepository",
    "AccessResult",
    "AnchorVerification",
    "ArtifactRationaleTrace",
    "ArtifactRevision",
    "ArtifactRevisionHistory",
    "AuditAction",
    "AuditAnchor",
    "AuditAnchorRepository",
    "AuditConflictError",
    "AuditResourceKind",
    "AuditVerificationError",
    "ChainVerificationReport",
    "RecommendationAccessReport",
    "RoundContextReport",
    "SessionParticipant",
    "SessionParticipantReader",
    "SessionTerminationReport",
    "StrategyUsageReport",
    "access_cursor_decode",
    "access_cursor_encode",
    "audit_anchor_hash",
]

_SHA256 = r"^sha256:[0-9a-f]{64}$"


class AccessResult(StrEnum):
    """Outcome of an audited read attempt (matches the stored CHECK)."""

    ALLOWED = "ALLOWED"
    DENIED = "DENIED"
    FAILED = "FAILED"


class AuditAction(StrEnum):
    """Audited actions. Phase 13 only records reads on general ``access_log``."""

    READ = "READ"


class AuditResourceKind(StrEnum):
    """Resource categories a read can touch (AUDITABILITY.md §4)."""

    ARTIFACT = "ARTIFACT"
    KNOWLEDGE_CHUNK = "KNOWLEDGE_CHUNK"
    AUDIT_EXPORT = "AUDIT_EXPORT"
    AGENT_DEFINITION = "AGENT_DEFINITION"
    RETRIEVAL_CHUNK = "RETRIEVAL_CHUNK"
    CONSENSUS_RESULT = "CONSENSUS_RESULT"
    RECOMMENDATION = "RECOMMENDATION"
    SESSION = "SESSION"


# trace: FR-807, NFR-006
class AccessAuditError(ValueError):
    """An access-log command broke a stated invariant."""


class AuditConflictError(ValueError):
    """An anchor for the same session-day already exists (append-only semantics)."""


class AuditVerificationError(ValueError):
    """An audit chain cannot be published or verified from the given facts."""


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an RFC 3339 offset")
    return value.astimezone(UTC)


class AccessLogEntry(FrozenModel):
    """One audited read of a resource inside a session (AUDITABILITY.md §4)."""

    id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    session_id: UUID
    principal_class: ActorClass
    principal_id: UUID
    resource_kind: AuditResourceKind
    resource_id: UUID
    action: AuditAction = AuditAction.READ
    result: AccessResult
    scope_ids: tuple[str, ...] = ()
    source_ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    trace_id: str = Field(min_length=1)
    recorded_at: datetime

    _timestamps = field_validator("recorded_at")(_aware_utc)

    @field_validator("trace_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("trace_id must not be blank")
        return value

    @field_validator("scope_ids")
    @classmethod
    def _scope_ids_clean(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("scope_ids entries must not be blank")
        return value

    @model_validator(mode="after")
    def shape(self) -> AccessLogEntry:
        if self.action is not AuditAction.READ:
            raise ValueError("Phase 13 access_log records only READ actions")
        return self


def access_cursor_encode(recorded_at: datetime, entry_id: UUID) -> str:
    """Opaque, orderable pagination key derived from the index tuple."""
    raw = f"{_zulu(recorded_at)}|{entry_id}"
    return base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii")


def access_cursor_decode(cursor: str) -> tuple[datetime, UUID]:
    """Decode a cursor produced by :func:`access_cursor_encode`."""
    decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii")
    timestamp, entry_id = decoded.rsplit("|", 1)
    value = _aware_utc(datetime.fromisoformat(timestamp))
    assert value is not None
    return value.astimezone(UTC), UUID(entry_id)


def _zulu(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _anchor_facts(
    *,
    workspace_id: UUID,
    session_id: UUID,
    anchor_day: date,
    head_seq: int,
    head_hash: str,
    prev_head_hash: str,
    anchored_at: datetime,
) -> dict[str, str | int]:
    return {
        "workspace_id": str(workspace_id),
        "session_id": str(session_id),
        "anchor_day": anchor_day.isoformat(),
        "head_seq": head_seq,
        "head_hash": head_hash,
        "prev_head_hash": prev_head_hash,
        "anchored_at": _zulu(anchored_at),
    }


def audit_anchor_hash(anchor: AuditAnchor) -> str:
    """Self-authenticating anchor digest over the fixed anchor facts."""
    return content_hash(
        _anchor_facts(
            workspace_id=anchor.workspace_id,
            session_id=anchor.session_id,
            anchor_day=anchor.anchor_day,
            head_seq=anchor.head_seq,
            head_hash=anchor.head_hash,
            prev_head_hash=anchor.prev_head_hash,
            anchored_at=anchor.anchored_at,
        )
    )


class AuditAnchor(FrozenModel):
    """A published session-day head anchor over the reasoning ledger (Q8)."""

    id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    session_id: UUID
    anchor_day: date
    head_seq: int = Field(gt=0)
    head_hash: str = Field(pattern=_SHA256)
    prev_head_hash: str = Field(pattern=_SHA256)
    anchor_hash: str = Field(pattern=_SHA256)
    anchored_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    _timestamps = field_validator("anchored_at")(_aware_utc)

    @classmethod
    def publish(
        cls,
        *,
        workspace_id: UUID,
        session_id: UUID,
        anchor_day: date,
        head_seq: int,
        head_hash: str,
        prev_head_hash: str = GENESIS_HASH,
        anchored_at: datetime | None = None,
    ) -> AuditAnchor:
        """Build a validated anchor with its ``anchor_hash`` computed from the facts."""
        normalized = _aware_utc(anchored_at or datetime.now(UTC))
        assert normalized is not None
        return cls(
            workspace_id=workspace_id,
            session_id=session_id,
            anchor_day=anchor_day,
            head_seq=head_seq,
            head_hash=head_hash,
            prev_head_hash=prev_head_hash,
            anchor_hash=content_hash(
                _anchor_facts(
                    workspace_id=workspace_id,
                    session_id=session_id,
                    anchor_day=anchor_day,
                    head_seq=head_seq,
                    head_hash=head_hash,
                    prev_head_hash=prev_head_hash,
                    anchored_at=normalized,
                )
            ),
            anchored_at=normalized,
        )

    @model_validator(mode="after")
    def self_authenticating(self) -> AuditAnchor:
        if self.anchor_hash != audit_anchor_hash(self):
            raise ValueError("anchor_hash does not match the anchor facts")
        return self


class SessionParticipant(FrozenModel):
    """The bound agent-version a session saw as a participant."""

    agent_definition_id: UUID
    logical_id: UUID
    name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    role_kind: AgentRoleKind


class ArtifactRevision(FrozenModel):
    """One ledger-observed write of an artifact in an epistemic-status chain (Q2)."""

    version: int = Field(ge=1)
    event_id: UUID
    ledger_seq: int = Field(gt=0)
    round: int = Field(ge=0)
    event_type: str = Field(min_length=1)
    actor_class: ActorClass
    actor_id: UUID
    recorded_at: datetime
    supersedes_id: UUID | None = None
    warrant_artifact_ids: tuple[UUID, ...] = ()

    _timestamps = field_validator("recorded_at")(_aware_utc)


class ArtifactRevisionHistory(FrozenModel):
    """Every ledger write of one artifact, in ledger order (Q2)."""

    artifact_id: UUID
    session_id: UUID
    revisions: tuple[ArtifactRevision, ...] = ()


class RoundContextReport(FrozenModel):
    """What a session's agents saw during round *n* (Q3)."""

    round: int = Field(ge=0)
    session_id: UUID
    participants: tuple[SessionParticipant, ...] = ()
    turn_events: tuple[LedgerEvent, ...] = ()


class StrategyUsageReport(FrozenModel):
    """Strategy, inputs and outcome that produced a round ranking (Q6)."""

    workspace_id: UUID
    session_id: UUID
    round: int = Field(ge=1)
    strategy: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    input_hash: str = Field(pattern=_SHA256)
    outcome: ConsensusOutcome
    conditions: tuple[str, ...] = ()
    pareto_set: tuple[UUID, ...] = ()
    created_at: datetime

    _timestamps = field_validator("created_at")(_aware_utc)


class SessionTerminationReport(FrozenModel):
    """Why a session stopped, from the lifecycle projection and ledger tail (Q5)."""

    workspace_id: UUID
    session_id: UUID
    final_state: SessionLifecycleState | None = None
    final_round: int | None = None
    ended_at: datetime | None = None
    last_event: LedgerEvent | None = None


class ArtifactRationaleTrace(FrozenModel):
    """Full evidence-to-record rationale for one artifact (Q1)."""

    workspace_id: UUID
    artifact_id: UUID
    session_id: UUID
    provenance: ProvenanceResult | None = None
    committed_by_event: LedgerEvent | None = None
    originating_turn_event: LedgerEvent | None = None


class RecommendationAccessReport(FrozenModel):
    """Q7: who accessed this recommendation, bounded strictly before acceptance."""

    workspace_id: UUID
    recommendation_id: UUID
    recommendation_known: bool
    recommendation_created_at: datetime | None = None
    session_id: UUID | None = None
    entries: tuple[AccessLogEntry, ...] = ()
    complete_timeline: bool
    why_incomplete: str | None = None
    truncated: bool = False
    next_cursor: str | None = None


class AnchorVerification(FrozenModel):
    """Per-anchor verdict after recomputing its hash and chain link."""

    anchor: AuditAnchor
    valid: bool
    reason: str | None = None


class ChainVerificationReport(FrozenModel):
    """Q8: full ledger + anchor chain verdict for one session."""

    workspace_id: UUID
    session_id: UUID
    event_count: int
    ledger_verification: LedgerVerification
    anchors: tuple[AnchorVerification, ...] = ()
    first_invalid_day: date | None = None
    chain_valid: bool


@runtime_checkable
class AccessLogRepository(Protocol):
    """Caller-transaction-scoped read-log persistence (Q7 backing)."""

    async def record(self, entry: AccessLogEntry) -> None: ...

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
    ) -> tuple[tuple[AccessLogEntry, ...], str | None]: ...

    async def recommendation_created_at(
        self, workspace_id: UUID, recommendation_id: UUID
    ) -> datetime | None: ...


@runtime_checkable
class AuditAnchorRepository(Protocol):
    """Caller-transaction-scoped daily-anchor persistence (Q8 backing)."""

    async def latest(self, workspace_id: UUID, session_id: UUID) -> AuditAnchor | None: ...

    async def all(self, workspace_id: UUID, session_id: UUID) -> tuple[AuditAnchor, ...]: ...

    async def publish(self, anchor: AuditAnchor) -> AuditAnchor: ...


@runtime_checkable
class SessionParticipantReader(Protocol):
    """Names and roles of the agent versions bound to a session (Q3)."""

    async def participants(
        self, workspace_id: UUID, session_id: UUID
    ) -> tuple[SessionParticipant, ...]: ...
