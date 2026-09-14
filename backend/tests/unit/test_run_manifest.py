"""T13-04 canonical run-manifest and persisted replay-source tests.

trace: NFR-003, NFR-014
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from app.adapters.inmemory.object_store import InMemoryObjectStore
from app.application.replay import (
    ReplayImplementation,
    ReplayImplementationRegistry,
    SessionReplayService,
)
from app.application.run_manifest import PersistedReplaySource, RunManifestService
from app.domain.reasoning import ActorClass, content_hash
from app.domain.reasoning_ledger import (
    GENESIS_HASH,
    LedgerEvent,
    LedgerVerification,
    ledger_event_hash,
    ledger_payload_hash,
)
from app.domain.replay import (
    ReplayExecution,
    ReplayImplementationIdentity,
    ReplayMode,
    ReplayOutcome,
    ReplayRequest,
    ReplayStep,
    ReplayStepKind,
    ReplayStepPolicy,
)
from app.domain.run_manifest import (
    AgentPin,
    CodePin,
    ConsensusPin,
    ContentPin,
    MetricPin,
    RunManifest,
    RunManifestConflict,
    RunManifestDocument,
    RunManifestRepository,
    RunManifestStatus,
    SchemaPin,
    run_manifest_bytes,
    run_manifest_hash,
    run_manifest_id,
)
from tests.traceability import req

WS = UUID("00000000-0000-0000-0000-000000001001")
SESSION = UUID("00000000-0000-0000-0000-000000001002")
AGENT = UUID("00000000-0000-0000-0000-000000001003")
CONTENT = UUID("00000000-0000-0000-0000-000000001004")
EVENT_ID = UUID("00000000-0000-0000-0000-000000001005")
NOW = datetime(2026, 9, 14, tzinfo=UTC)
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def _event() -> LedgerEvent:
    payload = {"session_id": str(SESSION)}
    event = LedgerEvent(
        id=EVENT_ID,
        workspace_id=WS,
        session_id=SESSION,
        event_type="SESSION_CREATED",
        payload_schema_version=1,
        correlation_id=UUID("00000000-0000-0000-0000-000000001006"),
        actor_class=ActorClass.SERVICE,
        actor_id=UUID("00000000-0000-0000-0000-000000001007"),
        payload=payload,
        recorded_at=NOW,
        ledger_seq=1,
        payload_hash=ledger_payload_hash(payload),
        prev_hash=GENESIS_HASH,
        event_hash=DIGEST_A,
    )
    return event.model_copy(update={"event_hash": ledger_event_hash(event)})


def _identity() -> ReplayImplementationIdentity:
    return ReplayImplementationIdentity(
        implementation_id="agora.consensus.weighted",
        implementation_version="1.0.0",
        configuration_hash=DIGEST_B,
    )


def _step() -> ReplayStep:
    input_value = {"scores": [1, 2]}
    output = {"winner": "a"}
    return ReplayStep(
        step_id=UUID("00000000-0000-0000-0000-000000001008"),
        order=1,
        kind=ReplayStepKind.CONSENSUS,
        policy=ReplayStepPolicy.DETERMINISTIC,
        implementation=_identity(),
        input=input_value,
        input_hash=content_hash(input_value),
        expected_output=output,
        expected_output_hash=content_hash(output),
    )


def _document(
    *, prompt_hash: str = DIGEST_A, source_session_id: UUID | None = None
) -> RunManifestDocument:
    return RunManifestDocument(
        workspace_id=WS,
        session_id=SESSION,
        source_session_id=source_session_id,
        code=CodePin(git_sha="1cad09a", image_digests={"backend": DIGEST_A}),
        schema_pin=SchemaPin(migration_head="20260914_0026", artifact_schema_version=1),
        configuration_hash=DIGEST_B,
        protocol="deliberative",
        rounds=6,
        budget={"max_rounds": 6, "max_tokens": 1000, "max_usd": "10.00"},
        consensus=ConsensusPin(
            strategy_id="weighted", strategy_version="1.0.0", parameters={"threshold": "0.6"}
        ),
        agents=(
            AgentPin(
                definition_id=AGENT,
                definition_version=4,
                prompt_ref="prompts/critic-v4.txt",
                prompt_hash=prompt_hash,
                strategy_id="evidence-first",
                strategy_version="1.0.0",
            ),
        ),
        metrics=(MetricPin(metric_id="ep-01", metric_version="1"),),
        contents=(
            ContentPin(content_id=CONTENT, kind="ARTIFACT", version=1, content_hash=DIGEST_B),
        ),
        replay_steps=(_step(),),
        started_at=NOW,
    )


class FakeRepository(RunManifestRepository):
    def __init__(self) -> None:
        self.value: RunManifest | None = None

    async def create(self, manifest: RunManifest) -> RunManifest:
        if self.value is None:
            self.value = manifest
            return manifest
        if self.value == manifest:
            return self.value
        raise RunManifestConflict("different manifest")

    async def get_for_session(
        self, workspace_id: UUID, session_id: UUID, *, for_update: bool = False
    ) -> RunManifest | None:
        if (
            self.value
            and self.value.workspace_id == workspace_id
            and self.value.session_id == session_id
        ):
            return self.value
        return None

    async def get_finalized(
        self, workspace_id: UUID, session_id: UUID, reference: Any
    ) -> RunManifest | None:
        value = await self.get_for_session(workspace_id, session_id)
        return (
            value
            if value and value.status is RunManifestStatus.FINALIZED and value.ref() == reference
            else None
        )

    async def finalize(self, manifest: RunManifest) -> RunManifest:
        if self.value is None:
            raise RunManifestConflict("missing")
        if self.value.status is RunManifestStatus.FINALIZED and self.value != manifest:
            raise RunManifestConflict("immutable")
        self.value = manifest
        return manifest


class FakeLedger:
    def __init__(self, event: LedgerEvent) -> None:
        self.event = event

    async def append(self, event: Any) -> LedgerEvent:
        raise AssertionError("manifest replay never appends")

    async def read(
        self,
        workspace_id: UUID,
        session_id: UUID,
        *,
        from_seq: int = 1,
        limit: int = 1000,
    ) -> Sequence[LedgerEvent]:
        return (
            (self.event,) if workspace_id == WS and session_id == SESSION and from_seq <= 1 else ()
        )

    async def verify(self, workspace_id: UUID, session_id: UUID) -> LedgerVerification:
        return LedgerVerification(valid=True, event_count=1, head_hash=self.event.event_hash)


async def _finalized() -> tuple[
    RunManifest, FakeRepository, InMemoryObjectStore, RunManifestDocument
]:
    repository = FakeRepository()
    objects = InMemoryObjectStore()
    service = RunManifestService(repository, objects, bucket="manifests")
    document = _document()
    await service.create(
        workspace_id=WS,
        session_id=SESSION,
        source_session_id=None,
        git_sha=document.code.git_sha,
        image_digests=document.code.image_digests,
        model_pins={},
        prompt_hashes={str(AGENT): DIGEST_A},
        seed=None,
        created_at=NOW,
    )
    manifest = await service.finalize(
        WS, SESSION, document, finalized_at=NOW + timedelta(seconds=1)
    )
    return manifest, repository, objects, document


@req("NFR-003", "NFR-014")
def test_manifest_serialization_hash_and_identity_are_canonical_and_deterministic() -> None:
    left = _document()
    right = _document()
    assert run_manifest_bytes(left) == run_manifest_bytes(right)
    assert run_manifest_hash(left) == run_manifest_hash(right)
    assert run_manifest_id(left) == run_manifest_id(right)
    changed = _document(prompt_hash=DIGEST_B)
    assert run_manifest_hash(changed) != run_manifest_hash(left)
    assert run_manifest_id(changed) != run_manifest_id(left)


@req("NFR-003", "NFR-014")
def test_manifest_requires_exact_replay_pins() -> None:
    data = _document().model_dump()
    data["metrics"] = ()
    with pytest.raises(ValueError, match="required"):
        RunManifestDocument.model_validate(data)


@req("NFR-003", "NFR-014")
async def test_manifest_create_is_idempotent_and_finalization_is_immutable() -> None:
    manifest, repository, _, document = await _finalized()
    assert manifest.status is RunManifestStatus.FINALIZED
    assert manifest.manifest_hash == run_manifest_hash(document)
    with pytest.raises(RunManifestConflict, match="immutable"):
        await repository.finalize(
            manifest.model_copy(update={"manifest_hash": "sha256:" + "c" * 64})
        )


@req("NFR-003", "NFR-014")
async def test_live_derived_run_gets_a_new_manifest_identity_and_source_lineage() -> None:
    source_repository = FakeRepository()
    derived_repository = FakeRepository()
    objects = InMemoryObjectStore()
    source = RunManifestService(source_repository, objects, bucket="manifests")
    derived = RunManifestService(derived_repository, objects, bucket="manifests")
    original = await source.create(
        workspace_id=WS,
        session_id=SESSION,
        source_session_id=None,
        git_sha="1cad09a",
        image_digests={"backend": DIGEST_A},
        model_pins={},
        prompt_hashes={str(AGENT): DIGEST_A},
        seed=None,
        created_at=NOW,
    )
    replay_session = UUID("00000000-0000-0000-0000-000000001099")
    replay_manifest = await derived.create(
        workspace_id=WS,
        session_id=replay_session,
        source_session_id=SESSION,
        git_sha="1cad09a",
        image_digests={"backend": DIGEST_A},
        model_pins={},
        prompt_hashes={str(AGENT): DIGEST_A},
        seed=None,
        created_at=NOW,
    )
    assert replay_manifest.id != original.id
    assert replay_manifest.session_id != original.session_id
    assert replay_manifest.source_session_id == original.session_id


@req("NFR-003", "NFR-014")
async def test_strict_replay_resolves_only_the_exact_finalized_manifest() -> None:
    manifest, repository, objects, _ = await _finalized()
    ledger = FakeLedger(_event())
    source = PersistedReplaySource(repository, objects, ledger)
    calls = 0

    async def execute(input_value: Mapping[str, Any]) -> ReplayExecution:
        nonlocal calls
        calls += 1
        output = {"winner": "a"}
        return ReplayExecution(
            implementation=_identity(), output=output, output_hash=content_hash(output)
        )

    replay = SessionReplayService(
        source,
        ledger,
        ReplayImplementationRegistry(
            (ReplayImplementation(_identity(), execute, deterministic=True, external=False),)
        ),
    )
    result = await replay.replay(
        ReplayRequest(
            workspace_id=WS,
            source_session_id=SESSION,
            manifest=manifest.ref(),
            mode=ReplayMode.STRICT,
        )
    )
    assert result.outcome is ReplayOutcome.VERIFIED
    assert calls == 1

    unavailable = manifest.ref().model_copy(update={"manifest_hash": "sha256:" + "c" * 64})
    result = await replay.replay(
        ReplayRequest(
            workspace_id=WS,
            source_session_id=SESSION,
            manifest=unavailable,
            mode=ReplayMode.STRICT,
        )
    )
    assert result.outcome is ReplayOutcome.FAILED
    assert calls == 1
