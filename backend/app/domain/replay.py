"""Typed full-session replay contracts for Phase 13 T13-03.

Manifest creation and persistence remain T13-04. These contracts consume one exact
manifest identity and its immutable historical inputs without redefining Phase 12 MARL replay.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.domain.reasoning import FrozenModel, content_hash
from app.domain.reasoning_ledger import LedgerEvent

__all__ = [
    "HistoricalReplay",
    "LiveReplayLaunch",
    "LiveReplayLauncher",
    "MarlReplayBundle",
    "ReplayDifference",
    "ReplayDifferenceKind",
    "ReplayExecution",
    "ReplayFailureReason",
    "ReplayImplementationIdentity",
    "ReplayImplementationSelection",
    "ReplayManifestRef",
    "ReplayMismatch",
    "ReplayMode",
    "ReplayOutcome",
    "ReplayRequest",
    "ReplayResult",
    "ReplaySource",
    "ReplayStep",
    "ReplayStepKind",
    "ReplayStepPolicy",
]


class ReplayMode(StrEnum):
    STRICT = "REPLAY_STRICT"
    TOLERANT = "REPLAY_TOLERANT"
    LIVE = "REPLAY_LIVE"


class ReplayOutcome(StrEnum):
    VERIFIED = "VERIFIED"
    MATCHED = "MATCHED"
    DIFFERENT = "DIFFERENT"
    LIVE_STARTED = "LIVE_STARTED"
    FAILED = "FAILED"


class ReplayStepKind(StrEnum):
    ARTIFACT = "ARTIFACT"
    EVENT = "EVENT"
    METRIC = "METRIC"
    CONSENSUS = "CONSENSUS"
    SYMBOLIC = "SYMBOLIC"
    SIMULATION = "SIMULATION"
    RETRIEVAL = "RETRIEVAL"
    LLM = "LLM"


class ReplayStepPolicy(StrEnum):
    RECORDED = "RECORDED"
    DETERMINISTIC = "DETERMINISTIC"
    EXTERNAL = "EXTERNAL"


class ReplayDifferenceKind(StrEnum):
    IMPLEMENTATION = "IMPLEMENTATION"
    PROVIDER = "PROVIDER"
    MODEL = "MODEL"
    CONFIGURATION = "CONFIGURATION"
    OUTPUT = "OUTPUT"
    STATUS = "STATUS"
    TIMING_SENSITIVE = "TIMING_SENSITIVE"


class ReplayFailureReason(StrEnum):
    HISTORICAL_REPLAY_UNAVAILABLE = "HISTORICAL_REPLAY_UNAVAILABLE"
    MANIFEST_MISMATCH = "MANIFEST_MISMATCH"
    LEDGER_INTEGRITY = "LEDGER_INTEGRITY"
    LEDGER_MISMATCH = "LEDGER_MISMATCH"
    UNKNOWN_IMPLEMENTATION = "UNKNOWN_IMPLEMENTATION"
    NONDETERMINISTIC_IMPLEMENTATION = "NONDETERMINISTIC_IMPLEMENTATION"
    OUTPUT_MISMATCH = "OUTPUT_MISMATCH"
    MARL_REPLAY_FAILED = "MARL_REPLAY_FAILED"
    LIVE_LAUNCH_UNAVAILABLE = "LIVE_LAUNCH_UNAVAILABLE"
    INVALID_LIVE_IDENTITY = "INVALID_LIVE_IDENTITY"


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


class ReplayManifestRef(FrozenModel):
    manifest_id: UUID
    manifest_version: int = Field(gt=0)
    manifest_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ReplayImplementationIdentity(FrozenModel):
    implementation_id: str
    implementation_version: str
    provider: str | None = None
    model: str | None = None
    configuration_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    _id = field_validator("implementation_id")(_not_blank)
    _version = field_validator("implementation_version")(_not_blank)

    @field_validator("provider", "model")
    @classmethod
    def optional_not_blank(cls, value: str | None) -> str | None:
        return _not_blank(value) if value is not None else None


class ReplayStep(FrozenModel):
    step_id: UUID
    order: int = Field(gt=0)
    kind: ReplayStepKind
    policy: ReplayStepPolicy
    implementation: ReplayImplementationIdentity | None = None
    input: dict[str, Any]
    input_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_output: dict[str, Any]
    expected_output_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_status: str | None = None
    tolerant_reexecution_allowed: bool = False
    timing_sensitive: bool = False

    @field_validator("expected_status")
    @classmethod
    def status_not_blank(cls, value: str | None) -> str | None:
        return _not_blank(value) if value is not None else None

    @model_validator(mode="after")
    def coherent(self) -> ReplayStep:
        if self.input_hash != content_hash(self.input):
            raise ValueError("input_hash does not match replay input")
        if self.expected_output_hash != content_hash(self.expected_output):
            raise ValueError("expected_output_hash does not match replay output")
        if self.policy is not ReplayStepPolicy.RECORDED and self.implementation is None:
            raise ValueError("executable replay steps require an implementation identity")
        if self.policy is ReplayStepPolicy.RECORDED and self.tolerant_reexecution_allowed:
            raise ValueError("recorded-only steps cannot permit re-execution")
        if self.policy is ReplayStepPolicy.EXTERNAL and not self.tolerant_reexecution_allowed:
            raise ValueError("external steps must explicitly permit tolerant re-execution")
        return self


class MarlReplayBundle(FrozenModel):
    manifest: bytes
    trajectory: bytes


class HistoricalReplay(FrozenModel):
    workspace_id: UUID
    source_session_id: UUID
    manifest: ReplayManifestRef
    ledger_events: tuple[LedgerEvent, ...]
    steps: tuple[ReplayStep, ...]
    marl_bundles: tuple[MarlReplayBundle, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> HistoricalReplay:
        if any(
            event.workspace_id != self.workspace_id or event.session_id != self.source_session_id
            for event in self.ledger_events
        ):
            raise ValueError("ledger events must belong to the replay source session")
        if tuple(event.ledger_seq for event in self.ledger_events) != tuple(
            range(1, len(self.ledger_events) + 1)
        ):
            raise ValueError("historical ledger events must be gapless and ordered")
        orders = tuple(step.order for step in self.steps)
        if orders != tuple(sorted(orders)) or len(set(orders)) != len(orders):
            raise ValueError("replay steps must have unique deterministic order")
        if len({step.step_id for step in self.steps}) != len(self.steps):
            raise ValueError("replay step ids must be unique")
        return self


@runtime_checkable
class ReplaySource(Protocol):
    async def load(
        self,
        workspace_id: UUID,
        source_session_id: UUID,
        manifest: ReplayManifestRef,
    ) -> HistoricalReplay | None: ...


class ReplayImplementationSelection(FrozenModel):
    step_id: UUID
    implementation: ReplayImplementationIdentity


class ReplayRequest(FrozenModel):
    workspace_id: UUID
    source_session_id: UUID
    manifest: ReplayManifestRef
    mode: ReplayMode
    implementation_selections: tuple[ReplayImplementationSelection, ...] = ()

    @model_validator(mode="after")
    def selection_shape(self) -> ReplayRequest:
        step_ids = tuple(item.step_id for item in self.implementation_selections)
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("implementation selection step ids must be unique")
        if self.mode is ReplayMode.STRICT and self.implementation_selections:
            raise ValueError("strict replay cannot override pinned implementations")
        return self


class ReplayExecution(FrozenModel):
    implementation: ReplayImplementationIdentity
    output: dict[str, Any]
    output_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    status: str | None = None

    @field_validator("status")
    @classmethod
    def status_not_blank(cls, value: str | None) -> str | None:
        return _not_blank(value) if value is not None else None

    @model_validator(mode="after")
    def coherent_hash(self) -> ReplayExecution:
        if self.output_hash != content_hash(self.output):
            raise ValueError("output_hash does not match replay execution output")
        return self


class ReplayDifference(FrozenModel):
    order: int = Field(gt=0)
    step_id: UUID
    kind: ReplayStepKind
    difference: ReplayDifferenceKind
    field: str
    expected: str | None
    actual: str | None

    _field = field_validator("field")(_not_blank)


class ReplayMismatch(FrozenModel):
    reason: ReplayFailureReason
    detail: str
    order: int | None = Field(default=None, gt=0)
    step_id: UUID | None = None
    expected_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    actual_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    _detail = field_validator("detail")(_not_blank)


class LiveReplayLaunch(FrozenModel):
    mode: ReplayMode
    source_session_id: UUID
    session_id: UUID
    manifest_id: UUID
    event_ids: tuple[UUID, ...]
    result_ids: tuple[UUID, ...]

    @model_validator(mode="after")
    def live_identity(self) -> LiveReplayLaunch:
        if self.mode is not ReplayMode.LIVE:
            raise ValueError("live replay launch must be marked REPLAY_LIVE")
        if self.session_id == self.source_session_id:
            raise ValueError("live replay must allocate a new session id")
        if not self.event_ids or not self.result_ids:
            raise ValueError("live replay must allocate new event and result identities")
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("live replay event ids must be unique")
        if len(set(self.result_ids)) != len(self.result_ids):
            raise ValueError("live replay result ids must be unique")
        return self


@runtime_checkable
class LiveReplayLauncher(Protocol):
    async def launch(
        self,
        request: ReplayRequest,
        historical: HistoricalReplay,
        selections: Mapping[UUID, ReplayImplementationIdentity],
    ) -> LiveReplayLaunch: ...


class ReplayResult(FrozenModel):
    mode: ReplayMode
    outcome: ReplayOutcome
    workspace_id: UUID
    source_session_id: UUID
    source_manifest: ReplayManifestRef
    integrity_valid: bool
    byte_identical: bool
    checked_steps: int = Field(ge=0)
    differences: tuple[ReplayDifference, ...] = ()
    first_mismatch: ReplayMismatch | None = None
    replay_session_id: UUID | None = None
    replay_manifest_id: UUID | None = None
    replay_event_ids: tuple[UUID, ...] = ()
    replay_result_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def result_shape(self) -> ReplayResult:
        if self.mode is ReplayMode.STRICT:
            if self.outcome is ReplayOutcome.VERIFIED:
                if not self.integrity_valid or not self.byte_identical or self.first_mismatch:
                    raise ValueError("verified strict replay has an invalid result shape")
            elif self.outcome is not ReplayOutcome.FAILED or self.first_mismatch is None:
                raise ValueError("strict replay must be VERIFIED or FAILED with a mismatch")
            if self.differences or self.replay_session_id is not None:
                raise ValueError("strict replay cannot contain diffs or a new session")
        elif self.mode is ReplayMode.TOLERANT:
            if self.outcome not in (
                ReplayOutcome.MATCHED,
                ReplayOutcome.DIFFERENT,
                ReplayOutcome.FAILED,
            ):
                raise ValueError("tolerant replay has an invalid outcome")
            if self.outcome is ReplayOutcome.FAILED and self.first_mismatch is None:
                raise ValueError("failed tolerant replay requires a reason")
            if self.outcome is not ReplayOutcome.FAILED and self.first_mismatch is not None:
                raise ValueError("completed tolerant replay cannot contain a strict failure")
            if self.replay_session_id is not None:
                raise ValueError("tolerant replay cannot create a session")
            if self.outcome is ReplayOutcome.MATCHED and self.differences:
                raise ValueError("matched tolerant replay cannot contain differences")
            if self.outcome is ReplayOutcome.DIFFERENT and not self.differences:
                raise ValueError("different tolerant replay requires a structured diff")
        else:
            if self.outcome is ReplayOutcome.FAILED:
                if self.first_mismatch is None:
                    raise ValueError("failed live replay requires a reason")
                if self.replay_session_id is not None:
                    raise ValueError("failed live replay cannot expose a new session")
                return self
            if self.outcome is not ReplayOutcome.LIVE_STARTED:
                raise ValueError("live replay must report LIVE_STARTED")
            if (
                self.replay_session_id is None
                or self.replay_manifest_id is None
                or not self.replay_event_ids
                or not self.replay_result_ids
                or self.replay_session_id == self.source_session_id
            ):
                raise ValueError(
                    "live replay requires fresh session, manifest, event and result ids"
                )
            if self.byte_identical or self.first_mismatch is not None or self.differences:
                raise ValueError("live replay is a new execution, not a verification or diff")
        return self
