"""Full-session STRICT, TOLERANT and LIVE replay orchestration (T13-03)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.application.marl import ImplementationRegistry as MarlImplementationRegistry
from app.application.marl import verify_bundle
from app.domain.marl import ReplayOutcome as MarlReplayOutcome
from app.domain.reasoning_ledger import LedgerEvent, ReasoningLedger
from app.domain.replay import (
    HistoricalReplay,
    LiveReplayLauncher,
    ReplayDifference,
    ReplayDifferenceKind,
    ReplayExecution,
    ReplayFailureReason,
    ReplayImplementationIdentity,
    ReplayMismatch,
    ReplayMode,
    ReplayOutcome,
    ReplayRequest,
    ReplayResult,
    ReplaySource,
    ReplayStep,
    ReplayStepPolicy,
)

__all__ = ["ReplayImplementation", "ReplayImplementationRegistry", "SessionReplayService"]

ReplayFunction = Callable[[Mapping[str, Any]], Awaitable[ReplayExecution]]
_LEDGER_READ_LIMIT = 1000


@dataclass(frozen=True, slots=True)
class ReplayImplementation:
    identity: ReplayImplementationIdentity
    execute: ReplayFunction
    deterministic: bool
    external: bool


class ReplayImplementationRegistry:
    """Exact-version registry with no latest-version or provider fallback."""

    def __init__(self, implementations: tuple[ReplayImplementation, ...] = ()) -> None:
        self._implementations: dict[tuple[str, str], ReplayImplementation] = {}
        for implementation in implementations:
            key = self._key(implementation.identity)
            if key in self._implementations:
                raise ValueError("duplicate replay implementation identity")
            self._implementations[key] = implementation

    @staticmethod
    def _key(identity: ReplayImplementationIdentity) -> tuple[str, str]:
        return identity.implementation_id, identity.implementation_version

    def resolve(self, identity: ReplayImplementationIdentity) -> ReplayImplementation | None:
        return self._implementations.get(self._key(identity))


# trace: NFR-003, NFR-014
class SessionReplayService:
    """Read-only verification; only LIVE delegates creation to an explicit launcher."""

    def __init__(
        self,
        source: ReplaySource,
        ledger: ReasoningLedger,
        implementations: ReplayImplementationRegistry,
        *,
        live_launcher: LiveReplayLauncher | None = None,
        marl_implementations: MarlImplementationRegistry | None = None,
    ) -> None:
        self._source = source
        self._ledger = ledger
        self._implementations = implementations
        self._live_launcher = live_launcher
        self._marl_implementations = marl_implementations

    async def replay(self, request: ReplayRequest) -> ReplayResult:
        historical = await self._source.load(
            request.workspace_id, request.source_session_id, request.manifest
        )
        if historical is None:
            return self._failed(
                request,
                ReplayMismatch(
                    reason=ReplayFailureReason.HISTORICAL_REPLAY_UNAVAILABLE,
                    detail="the exact historical session and manifest are unavailable",
                ),
            )

        mismatch = self._validate_source(request, historical)
        if mismatch is None:
            mismatch = await self._verify_ledger(historical)
        if mismatch is None:
            mismatch = self._verify_marl(historical)
        if mismatch is not None:
            return self._failed(request, mismatch)

        if request.mode is ReplayMode.STRICT:
            return await self._strict(request, historical)
        if request.mode is ReplayMode.TOLERANT:
            return await self._tolerant(request, historical)
        if request.mode is ReplayMode.LIVE:
            return await self._live(request, historical)
        raise AssertionError(f"unhandled replay mode: {request.mode}")

    @staticmethod
    def _validate_source(
        request: ReplayRequest, historical: HistoricalReplay
    ) -> ReplayMismatch | None:
        if (
            request.workspace_id != historical.workspace_id
            or request.source_session_id != historical.source_session_id
            or request.manifest != historical.manifest
        ):
            return ReplayMismatch(
                reason=ReplayFailureReason.MANIFEST_MISMATCH,
                detail="request does not identify the supplied historical session and manifest",
            )
        selected = {item.step_id for item in request.implementation_selections}
        available = {step.step_id for step in historical.steps}
        if not selected.issubset(available):
            return ReplayMismatch(
                reason=ReplayFailureReason.MANIFEST_MISMATCH,
                detail="implementation selection references an unknown historical step",
            )
        return None

    async def _verify_ledger(self, historical: HistoricalReplay) -> ReplayMismatch | None:
        verification = await self._ledger.verify(
            historical.workspace_id, historical.source_session_id
        )
        if not verification.valid:
            return ReplayMismatch(
                reason=ReplayFailureReason.LEDGER_INTEGRITY,
                detail=verification.reason or "reasoning ledger verification failed",
                order=verification.first_invalid_seq,
            )

        actual: list[LedgerEvent] = []
        next_seq = 1
        while True:
            batch = tuple(
                await self._ledger.read(
                    historical.workspace_id,
                    historical.source_session_id,
                    from_seq=next_seq,
                    limit=_LEDGER_READ_LIMIT,
                )
            )
            actual.extend(batch)
            if len(batch) < _LEDGER_READ_LIMIT:
                break
            next_seq = batch[-1].ledger_seq + 1

        for recorded, replayed in zip(historical.ledger_events, actual, strict=False):
            if recorded.event_hash != replayed.event_hash:
                return ReplayMismatch(
                    reason=ReplayFailureReason.LEDGER_MISMATCH,
                    detail="historical ledger differs at the first recorded event hash",
                    order=recorded.ledger_seq,
                    expected_hash=recorded.event_hash,
                    actual_hash=replayed.event_hash,
                )
        if len(historical.ledger_events) != len(actual):
            return ReplayMismatch(
                reason=ReplayFailureReason.LEDGER_MISMATCH,
                detail="historical ledger event count differs from the replay source",
                order=min(len(historical.ledger_events), len(actual)) + 1,
            )
        return None

    def _verify_marl(self, historical: HistoricalReplay) -> ReplayMismatch | None:
        if not historical.marl_bundles:
            return None
        if self._marl_implementations is None:
            return ReplayMismatch(
                reason=ReplayFailureReason.UNKNOWN_IMPLEMENTATION,
                detail="Phase 12 MARL implementation registry is unavailable",
            )
        for bundle in historical.marl_bundles:
            verification = verify_bundle(
                bundle.manifest, bundle.trajectory, self._marl_implementations
            )
            if verification.outcome is MarlReplayOutcome.VERIFIED:
                continue
            failure = verification.first_failure
            return ReplayMismatch(
                reason=ReplayFailureReason.MARL_REPLAY_FAILED,
                detail=failure.detail if failure is not None else "MARL replay failed",
                order=(
                    failure.decision_index + 1
                    if failure is not None and failure.decision_index is not None
                    else None
                ),
                expected_hash=failure.expected_hash if failure is not None else None,
                actual_hash=failure.actual_hash if failure is not None else None,
            )
        return None

    async def _strict(self, request: ReplayRequest, historical: HistoricalReplay) -> ReplayResult:
        checked = 0
        for step in historical.steps:
            if step.policy is ReplayStepPolicy.RECORDED:
                checked += 1
                continue
            assert step.implementation is not None
            implementation = self._implementations.resolve(step.implementation)
            if implementation is None:
                return self._failed(
                    request,
                    ReplayMismatch(
                        reason=ReplayFailureReason.UNKNOWN_IMPLEMENTATION,
                        detail="the exact pinned implementation is unavailable",
                        order=step.order,
                        step_id=step.step_id,
                    ),
                    checked=checked,
                )
            if implementation.external or not implementation.deterministic:
                return self._failed(
                    request,
                    ReplayMismatch(
                        reason=ReplayFailureReason.NONDETERMINISTIC_IMPLEMENTATION,
                        detail="strict replay prohibits external or nondeterministic execution",
                        order=step.order,
                        step_id=step.step_id,
                    ),
                    checked=checked,
                )
            execution = await implementation.execute(step.input)
            checked += 1
            mismatch = _strict_mismatch(step, execution)
            if mismatch is not None:
                return self._failed(request, mismatch, checked=checked)
        return ReplayResult(
            mode=request.mode,
            outcome=ReplayOutcome.VERIFIED,
            workspace_id=request.workspace_id,
            source_session_id=request.source_session_id,
            source_manifest=request.manifest,
            integrity_valid=True,
            byte_identical=True,
            checked_steps=checked,
        )

    async def _tolerant(self, request: ReplayRequest, historical: HistoricalReplay) -> ReplayResult:
        selected = {item.step_id: item.implementation for item in request.implementation_selections}
        differences: list[ReplayDifference] = []
        checked = 0
        for step in historical.steps:
            if step.policy is ReplayStepPolicy.RECORDED:
                checked += 1
                continue
            if step.policy is ReplayStepPolicy.EXTERNAL and not step.tolerant_reexecution_allowed:
                continue
            assert step.implementation is not None
            identity = selected.get(step.step_id, step.implementation)
            implementation = self._implementations.resolve(identity)
            if implementation is None:
                return self._failed(
                    request,
                    ReplayMismatch(
                        reason=ReplayFailureReason.UNKNOWN_IMPLEMENTATION,
                        detail="the selected tolerant replay implementation is unavailable",
                        order=step.order,
                        step_id=step.step_id,
                    ),
                    checked=checked,
                )
            execution = await implementation.execute(step.input)
            checked += 1
            differences.extend(_differences(step, execution))
        return ReplayResult(
            mode=request.mode,
            outcome=ReplayOutcome.DIFFERENT if differences else ReplayOutcome.MATCHED,
            workspace_id=request.workspace_id,
            source_session_id=request.source_session_id,
            source_manifest=request.manifest,
            integrity_valid=True,
            byte_identical=not differences,
            checked_steps=checked,
            differences=tuple(differences),
        )

    async def _live(self, request: ReplayRequest, historical: HistoricalReplay) -> ReplayResult:
        if self._live_launcher is None:
            return self._failed(
                request,
                ReplayMismatch(
                    reason=ReplayFailureReason.LIVE_LAUNCH_UNAVAILABLE,
                    detail="live replay launcher is unavailable",
                ),
            )
        selections = {
            item.step_id: item.implementation for item in request.implementation_selections
        }
        launch = await self._live_launcher.launch(request, historical, selections)
        if launch.source_session_id != historical.source_session_id:
            return self._failed(
                request,
                ReplayMismatch(
                    reason=ReplayFailureReason.INVALID_LIVE_IDENTITY,
                    detail="live replay did not link to the historical source session",
                ),
            )
        historical_ids = {
            *(event.id for event in historical.ledger_events),
            *(step.step_id for step in historical.steps),
            historical.manifest.manifest_id,
            historical.source_session_id,
        }
        new_ids = {
            launch.session_id,
            launch.manifest_id,
            *launch.event_ids,
            *launch.result_ids,
        }
        if historical_ids & new_ids:
            return self._failed(
                request,
                ReplayMismatch(
                    reason=ReplayFailureReason.INVALID_LIVE_IDENTITY,
                    detail="live replay reused a historical identity",
                ),
            )
        return ReplayResult(
            mode=request.mode,
            outcome=ReplayOutcome.LIVE_STARTED,
            workspace_id=request.workspace_id,
            source_session_id=request.source_session_id,
            source_manifest=request.manifest,
            integrity_valid=True,
            byte_identical=False,
            checked_steps=0,
            replay_session_id=launch.session_id,
            replay_manifest_id=launch.manifest_id,
            replay_event_ids=launch.event_ids,
            replay_result_ids=launch.result_ids,
        )

    @staticmethod
    def _failed(
        request: ReplayRequest, mismatch: ReplayMismatch, *, checked: int = 0
    ) -> ReplayResult:
        return ReplayResult(
            mode=request.mode,
            outcome=ReplayOutcome.FAILED,
            workspace_id=request.workspace_id,
            source_session_id=request.source_session_id,
            source_manifest=request.manifest,
            integrity_valid=mismatch.reason
            not in (ReplayFailureReason.LEDGER_INTEGRITY, ReplayFailureReason.LEDGER_MISMATCH),
            byte_identical=False,
            checked_steps=checked,
            first_mismatch=mismatch,
        )


def _strict_mismatch(step: ReplayStep, execution: ReplayExecution) -> ReplayMismatch | None:
    if execution.implementation != step.implementation:
        return ReplayMismatch(
            reason=ReplayFailureReason.UNKNOWN_IMPLEMENTATION,
            detail="executor did not use the exact pinned implementation identity",
            order=step.order,
            step_id=step.step_id,
        )
    if execution.output_hash != step.expected_output_hash:
        return ReplayMismatch(
            reason=ReplayFailureReason.OUTPUT_MISMATCH,
            detail="deterministic output differs from the historical output",
            order=step.order,
            step_id=step.step_id,
            expected_hash=step.expected_output_hash,
            actual_hash=execution.output_hash,
        )
    if execution.status != step.expected_status:
        return ReplayMismatch(
            reason=ReplayFailureReason.OUTPUT_MISMATCH,
            detail="deterministic status differs from the historical status",
            order=step.order,
            step_id=step.step_id,
        )
    return None


def _differences(step: ReplayStep, execution: ReplayExecution) -> tuple[ReplayDifference, ...]:
    assert step.implementation is not None
    differences: list[ReplayDifference] = []
    fields = (
        ("implementation_id", ReplayDifferenceKind.IMPLEMENTATION),
        ("implementation_version", ReplayDifferenceKind.IMPLEMENTATION),
        ("provider", ReplayDifferenceKind.PROVIDER),
        ("model", ReplayDifferenceKind.MODEL),
        ("configuration_hash", ReplayDifferenceKind.CONFIGURATION),
    )
    for field, kind in fields:
        expected = getattr(step.implementation, field)
        actual = getattr(execution.implementation, field)
        if expected != actual:
            differences.append(
                ReplayDifference(
                    order=step.order,
                    step_id=step.step_id,
                    kind=step.kind,
                    difference=kind,
                    field=field,
                    expected=expected,
                    actual=actual,
                )
            )
    if execution.output_hash != step.expected_output_hash:
        differences.append(
            ReplayDifference(
                order=step.order,
                step_id=step.step_id,
                kind=step.kind,
                difference=ReplayDifferenceKind.OUTPUT,
                field="output_hash",
                expected=step.expected_output_hash,
                actual=execution.output_hash,
            )
        )
    if execution.status != step.expected_status:
        differences.append(
            ReplayDifference(
                order=step.order,
                step_id=step.step_id,
                kind=step.kind,
                difference=(
                    ReplayDifferenceKind.TIMING_SENSITIVE
                    if step.timing_sensitive
                    else ReplayDifferenceKind.STATUS
                ),
                field="status",
                expected=step.expected_status,
                actual=execution.status,
            )
        )
    return tuple(differences)
