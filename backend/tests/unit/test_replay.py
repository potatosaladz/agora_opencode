"""T13-03 full-session replay mode tests.

trace: NFR-003, NFR-014
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.application.replay import (
    ReplayImplementation,
    ReplayImplementationRegistry,
    SessionReplayService,
)
from app.domain.reasoning import ActorClass, content_hash
from app.domain.reasoning_ledger import (
    GENESIS_HASH,
    LedgerEvent,
    LedgerVerification,
    ledger_event_hash,
    ledger_payload_hash,
)
from app.domain.replay import (
    HistoricalReplay,
    LiveReplayLaunch,
    ReplayDifferenceKind,
    ReplayExecution,
    ReplayFailureReason,
    ReplayImplementationIdentity,
    ReplayImplementationSelection,
    ReplayManifestRef,
    ReplayMode,
    ReplayOutcome,
    ReplayRequest,
    ReplayStep,
    ReplayStepKind,
    ReplayStepPolicy,
)
from tests.traceability import req

WS = UUID("00000000-0000-0000-0000-000000000101")
SESSION = UUID("00000000-0000-0000-0000-000000000102")
MANIFEST = ReplayManifestRef(
    manifest_id=UUID("00000000-0000-0000-0000-000000000103"),
    manifest_version=1,
    manifest_hash="sha256:" + "a" * 64,
)
NOW = datetime(2026, 9, 14, tzinfo=UTC)


def _identity(
    implementation_id: str = "agora.consensus.weighted",
    version: str = "1.0.0",
    *,
    provider: str | None = None,
    model: str | None = None,
    configuration_hash: str | None = None,
) -> ReplayImplementationIdentity:
    return ReplayImplementationIdentity(
        implementation_id=implementation_id,
        implementation_version=version,
        provider=provider,
        model=model,
        configuration_hash=configuration_hash,
    )


def _event(*, payload: dict[str, Any] | None = None) -> LedgerEvent:
    body = payload or {"session_id": str(SESSION)}
    event = LedgerEvent(
        id=UUID("00000000-0000-0000-0000-000000000104"),
        workspace_id=WS,
        session_id=SESSION,
        event_type="SESSION_CREATED",
        payload_schema_version=1,
        correlation_id=UUID("00000000-0000-0000-0000-000000000105"),
        actor_class=ActorClass.SERVICE,
        actor_id=UUID("00000000-0000-0000-0000-000000000106"),
        payload=body,
        recorded_at=NOW,
        ledger_seq=1,
        payload_hash=ledger_payload_hash(body),
        prev_hash=GENESIS_HASH,
        event_hash="sha256:" + "0" * 64,
    )
    return event.model_copy(update={"event_hash": ledger_event_hash(event)})


def _step(
    *,
    order: int = 1,
    kind: ReplayStepKind = ReplayStepKind.CONSENSUS,
    policy: ReplayStepPolicy = ReplayStepPolicy.DETERMINISTIC,
    implementation: ReplayImplementationIdentity | None = None,
    output: dict[str, Any] | None = None,
    expected_status: str | None = None,
    tolerant_reexecution_allowed: bool = False,
    timing_sensitive: bool = False,
) -> ReplayStep:
    input_value = {"scores": [1, 2]}
    output_value = output or {"winner": "a"}
    return ReplayStep(
        step_id=UUID(int=200 + order),
        order=order,
        kind=kind,
        policy=policy,
        implementation=implementation or _identity(),
        input=input_value,
        input_hash=content_hash(input_value),
        expected_output=output_value,
        expected_output_hash=content_hash(output_value),
        expected_status=expected_status,
        tolerant_reexecution_allowed=tolerant_reexecution_allowed,
        timing_sensitive=timing_sensitive,
    )


def _historical(*steps: ReplayStep, event: LedgerEvent | None = None) -> HistoricalReplay:
    return HistoricalReplay(
        workspace_id=WS,
        source_session_id=SESSION,
        manifest=MANIFEST,
        ledger_events=(event or _event(),),
        steps=steps or (_step(),),
    )


class FakeSource:
    def __init__(self, historical: HistoricalReplay) -> None:
        self.historical = historical

    async def load(
        self,
        workspace_id: UUID,
        source_session_id: UUID,
        manifest: ReplayManifestRef,
    ) -> HistoricalReplay | None:
        if (
            workspace_id == self.historical.workspace_id
            and source_session_id == self.historical.source_session_id
            and manifest == self.historical.manifest
        ):
            return self.historical
        return None


class FakeLedger:
    def __init__(self, events: Sequence[LedgerEvent], *, valid: bool = True) -> None:
        self.events = tuple(events)
        self.valid = valid

    async def append(self, event: Any) -> LedgerEvent:
        raise AssertionError("replay must not append to the historical ledger")

    async def read(
        self,
        workspace_id: UUID,
        session_id: UUID,
        *,
        from_seq: int = 1,
        limit: int = 1000,
    ) -> Sequence[LedgerEvent]:
        assert workspace_id == WS
        assert session_id == SESSION
        return tuple(event for event in self.events if event.ledger_seq >= from_seq)[:limit]

    async def verify(self, workspace_id: UUID, session_id: UUID) -> LedgerVerification:
        assert workspace_id == WS
        assert session_id == SESSION
        return LedgerVerification(
            valid=self.valid,
            event_count=len(self.events),
            head_hash=self.events[-1].event_hash if self.events else GENESIS_HASH,
            first_invalid_seq=None if self.valid else 1,
            reason=None if self.valid else "event hash mismatch",
        )


class FakeLiveLauncher:
    def __init__(self) -> None:
        self.calls = 0
        self.launch = LiveReplayLaunch(
            mode=ReplayMode.LIVE,
            source_session_id=SESSION,
            session_id=UUID("00000000-0000-0000-0000-000000000301"),
            manifest_id=UUID("00000000-0000-0000-0000-000000000302"),
            event_ids=(UUID("00000000-0000-0000-0000-000000000303"),),
            result_ids=(UUID("00000000-0000-0000-0000-000000000304"),),
        )

    async def __call__(
        self,
        request: ReplayRequest,
        historical: HistoricalReplay,
        selections: Mapping[UUID, ReplayImplementationIdentity],
    ) -> LiveReplayLaunch:
        self.calls += 1
        assert request.mode is ReplayMode.LIVE
        assert historical.source_session_id == SESSION
        return self.launch


class LiveLauncherAdapter:
    def __init__(self, fake: FakeLiveLauncher) -> None:
        self.fake = fake

    async def launch(
        self,
        request: ReplayRequest,
        historical: HistoricalReplay,
        selections: Mapping[UUID, ReplayImplementationIdentity],
    ) -> LiveReplayLaunch:
        return await self.fake(request, historical, selections)


def _request(
    mode: ReplayMode,
    *,
    selections: tuple[ReplayImplementationSelection, ...] = (),
    workspace_id: UUID = WS,
) -> ReplayRequest:
    return ReplayRequest(
        workspace_id=workspace_id,
        source_session_id=SESSION,
        manifest=MANIFEST,
        mode=mode,
        implementation_selections=selections,
    )


def _implementation(
    identity: ReplayImplementationIdentity,
    *,
    output: dict[str, Any] | None = None,
    status: str | None = None,
    deterministic: bool = True,
    external: bool = False,
    calls: list[dict[str, Any]] | None = None,
) -> ReplayImplementation:
    result = output or {"winner": "a"}

    async def execute(input_value: Mapping[str, Any]) -> ReplayExecution:
        if calls is not None:
            calls.append(dict(input_value))
        return ReplayExecution(
            implementation=identity,
            output=result,
            output_hash=content_hash(result),
            status=status,
        )

    return ReplayImplementation(
        identity=identity,
        execute=execute,
        deterministic=deterministic,
        external=external,
    )


def _service(
    historical: HistoricalReplay,
    *implementations: ReplayImplementation,
    ledger: FakeLedger | None = None,
    live_launcher: LiveLauncherAdapter | None = None,
) -> SessionReplayService:
    return SessionReplayService(
        FakeSource(historical),
        ledger or FakeLedger(historical.ledger_events),
        ReplayImplementationRegistry(tuple(implementations)),
        live_launcher=live_launcher,
    )


@req("NFR-003", "NFR-014")
def test_replay_modes_are_closed_and_distinct() -> None:
    assert tuple(ReplayMode) == (
        ReplayMode.STRICT,
        ReplayMode.TOLERANT,
        ReplayMode.LIVE,
    )


@req("NFR-003", "NFR-014")
async def test_strict_replay_verifies_exact_deterministic_output_without_mutation() -> None:
    step = _step()
    historical = _historical(step)
    before = historical.model_dump(mode="json")
    result = await _service(historical, _implementation(_identity())).replay(
        _request(ReplayMode.STRICT)
    )
    assert result.outcome is ReplayOutcome.VERIFIED
    assert result.byte_identical is True
    assert result.checked_steps == 1
    assert historical.model_dump(mode="json") == before


@req("NFR-003", "NFR-014")
async def test_strict_replay_reports_ledger_integrity_failure_before_execution() -> None:
    calls: list[dict[str, Any]] = []
    historical = _historical()
    result = await _service(
        historical,
        _implementation(_identity(), calls=calls),
        ledger=FakeLedger(historical.ledger_events, valid=False),
    ).replay(_request(ReplayMode.STRICT))
    assert result.outcome is ReplayOutcome.FAILED
    assert result.first_mismatch is not None
    assert result.first_mismatch.reason is ReplayFailureReason.LEDGER_INTEGRITY
    assert calls == []


@req("NFR-003", "NFR-014")
async def test_strict_replay_fails_closed_when_pinned_implementation_is_unavailable() -> None:
    result = await _service(_historical()).replay(_request(ReplayMode.STRICT))
    assert result.first_mismatch is not None
    assert result.first_mismatch.reason is ReplayFailureReason.UNKNOWN_IMPLEMENTATION


@req("NFR-003", "NFR-014")
async def test_strict_replay_reports_only_the_first_deterministic_mismatch() -> None:
    first = _step(order=1)
    second = _step(order=2)
    first_calls: list[dict[str, Any]] = []
    second_calls: list[dict[str, Any]] = []
    historical = _historical(first, second)
    result = await _service(
        historical,
        _implementation(_identity(), output={"winner": "changed"}, calls=first_calls),
        _implementation(_identity("agora.second"), calls=second_calls),
    ).replay(_request(ReplayMode.STRICT))
    assert result.first_mismatch is not None
    assert result.first_mismatch.reason is ReplayFailureReason.OUTPUT_MISMATCH
    assert result.first_mismatch.order == 1
    assert first_calls
    assert second_calls == []


@req("NFR-003", "NFR-014")
async def test_strict_replay_never_invokes_external_dependency() -> None:
    calls: list[dict[str, Any]] = []
    identity = _identity("provider.openai", provider="openai", model="gpt")
    step = _step(
        kind=ReplayStepKind.LLM,
        policy=ReplayStepPolicy.EXTERNAL,
        implementation=identity,
        tolerant_reexecution_allowed=True,
    )
    result = await _service(
        _historical(step),
        _implementation(identity, deterministic=False, external=True, calls=calls),
    ).replay(_request(ReplayMode.STRICT))
    assert result.first_mismatch is not None
    assert result.first_mismatch.reason is ReplayFailureReason.NONDETERMINISTIC_IMPLEMENTATION
    assert calls == []


@req("NFR-003", "NFR-014")
async def test_tolerant_replay_reports_identity_output_and_timing_sensitive_differences() -> None:
    old = _identity(
        "solver.z3", "4.13", provider="z3", model="solver", configuration_hash="sha256:" + "b" * 64
    )
    new = _identity(
        "solver.z3",
        "4.14",
        provider="z3-next",
        model="solver2",
        configuration_hash="sha256:" + "c" * 64,
    )
    step = _step(
        kind=ReplayStepKind.SYMBOLIC,
        implementation=old,
        output={"status": "UNKNOWN"},
        expected_status="UNKNOWN",
        tolerant_reexecution_allowed=True,
        timing_sensitive=True,
    )
    historical = _historical(step)
    result = await _service(
        historical,
        _implementation(new, output={"status": "SAT"}, status="SAT"),
    ).replay(
        _request(
            ReplayMode.TOLERANT,
            selections=(ReplayImplementationSelection(step_id=step.step_id, implementation=new),),
        )
    )
    assert result.outcome is ReplayOutcome.DIFFERENT
    assert result.byte_identical is False
    assert {item.difference for item in result.differences} == {
        ReplayDifferenceKind.IMPLEMENTATION,
        ReplayDifferenceKind.PROVIDER,
        ReplayDifferenceKind.MODEL,
        ReplayDifferenceKind.CONFIGURATION,
        ReplayDifferenceKind.OUTPUT,
        ReplayDifferenceKind.TIMING_SENSITIVE,
    }


@req("NFR-003", "NFR-014")
async def test_tolerant_replay_matches_without_claiming_strict_verification() -> None:
    historical = _historical()
    result = await _service(historical, _implementation(_identity())).replay(
        _request(ReplayMode.TOLERANT)
    )
    assert result.outcome is ReplayOutcome.MATCHED
    assert result.mode is ReplayMode.TOLERANT


@req("NFR-003", "NFR-014")
async def test_live_replay_has_fresh_linked_identities_and_preserves_source() -> None:
    historical = _historical()
    before = historical.model_dump(mode="json")
    fake = FakeLiveLauncher()
    result = await _service(
        historical,
        live_launcher=LiveLauncherAdapter(fake),
    ).replay(_request(ReplayMode.LIVE))
    assert result.outcome is ReplayOutcome.LIVE_STARTED
    assert result.replay_session_id == fake.launch.session_id
    assert result.replay_session_id != SESSION
    assert result.replay_manifest_id != MANIFEST.manifest_id
    assert set(result.replay_event_ids).isdisjoint(event.id for event in historical.ledger_events)
    assert set(result.replay_result_ids).isdisjoint(step.step_id for step in historical.steps)
    assert result.byte_identical is False
    assert historical.model_dump(mode="json") == before


@req("NFR-003", "NFR-014")
async def test_cross_workspace_replay_fails_before_ledger_or_execution() -> None:
    result = await _service(_historical()).replay(_request(ReplayMode.STRICT, workspace_id=uuid4()))
    assert result.outcome is ReplayOutcome.FAILED
    assert result.first_mismatch is not None
    assert result.first_mismatch.reason is ReplayFailureReason.HISTORICAL_REPLAY_UNAVAILABLE


@req("NFR-003", "NFR-014")
async def test_recorded_steps_are_reconstructed_without_any_execution() -> None:
    recorded = _step(
        policy=ReplayStepPolicy.RECORDED,
        implementation=None,
        output={"provider_response": "historical bytes"},
    )
    result = await _service(_historical(recorded)).replay(_request(ReplayMode.STRICT))
    assert result.outcome is ReplayOutcome.VERIFIED
    assert result.checked_steps == 1
