"""Run-manifest creation, finalization, and replay resolution (T13-04)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid5

from app.domain.reasoning_ledger import LedgerEvent, ReasoningLedger
from app.domain.replay import HistoricalReplay, ReplayManifestRef
from app.domain.run_manifest import (
    RunManifest,
    RunManifestConflict,
    RunManifestDocument,
    RunManifestRepository,
    RunManifestStatus,
    run_manifest_bytes,
    run_manifest_hash,
)
from app.ports.storage import ObjectStore

__all__ = ["PersistedReplaySource", "RunManifestService"]

_ROW_NAMESPACE = UUID("7626d3dc-bd31-48ca-b0a5-95d61655a66f")


# trace: NFR-003, NFR-014
class RunManifestService:
    """Persist creation pins and finalize one canonical manifest exactly once."""

    def __init__(
        self, repository: RunManifestRepository, objects: ObjectStore, *, bucket: str
    ) -> None:
        self._repository = repository
        self._objects = objects
        self._bucket = bucket

    async def create(
        self,
        *,
        workspace_id: UUID,
        session_id: UUID,
        source_session_id: UUID | None,
        git_sha: str,
        image_digests: dict[str, str],
        model_pins: dict[str, object],
        prompt_hashes: dict[str, str],
        seed: int | None,
        created_at: datetime,
    ) -> RunManifest:
        manifest = RunManifest(
            id=uuid5(_ROW_NAMESPACE, f"{workspace_id}:{session_id}"),
            workspace_id=workspace_id,
            session_id=session_id,
            source_session_id=source_session_id,
            manifest_version=1,
            status=RunManifestStatus.CREATED,
            git_sha=git_sha,
            image_digests=image_digests,
            model_pins=model_pins,
            prompt_hashes=prompt_hashes,
            seed=seed,
            created_at=created_at,
        )
        return await self._repository.create(manifest)

    async def finalize(
        self,
        workspace_id: UUID,
        session_id: UUID,
        document: RunManifestDocument,
        *,
        finalized_at: datetime,
    ) -> RunManifest:
        current = await self._repository.get_for_session(workspace_id, session_id, for_update=True)
        if current is None:
            raise RunManifestConflict("run manifest was not created with the session")
        self._validate_document(current, document)
        digest = run_manifest_hash(document)
        body = run_manifest_bytes(document)
        key = f"workspaces/{workspace_id}/manifests/{digest.removeprefix('sha256:')}.json"
        reference = await self._objects.put(
            self._bucket,
            key,
            body,
            content_type="application/json",
            metadata={
                "workspace_id": str(workspace_id),
                "session_id": str(session_id),
                "manifest_id": str(current.id),
                "manifest_version": str(current.manifest_version),
            },
        )
        if reference.digest != digest:
            raise RunManifestConflict("object store returned a different manifest digest")
        finalized = current.model_copy(
            update={
                "status": RunManifestStatus.FINALIZED,
                "manifest_ref": reference,
                "manifest_hash": digest,
                "finalized_at": finalized_at,
            }
        )
        return await self._repository.finalize(RunManifest.model_validate(finalized))

    @staticmethod
    def _validate_document(current: RunManifest, document: RunManifestDocument) -> None:
        if (
            document.workspace_id != current.workspace_id
            or document.session_id != current.session_id
            or document.source_session_id != current.source_session_id
            or document.manifest_version != current.manifest_version
            or document.code.git_sha != current.git_sha
            or document.code.image_digests != current.image_digests
        ):
            raise RunManifestConflict("final manifest differs from immutable creation pins")
        expected_models = {
            str(item.definition_id): item.inference.model
            for item in document.agents
            if item.inference is not None
        }
        expected_prompts = {str(item.definition_id): item.prompt_hash for item in document.agents}
        if expected_models != current.model_pins or expected_prompts != current.prompt_hashes:
            raise RunManifestConflict("final manifest agent pins differ from creation pins")


class PersistedReplaySource:
    """Resolve only finalized, digest-verified manifests for T13-03 replay."""

    def __init__(
        self, repository: RunManifestRepository, objects: ObjectStore, ledger: ReasoningLedger
    ) -> None:
        self._repository = repository
        self._objects = objects
        self._ledger = ledger

    async def load(
        self,
        workspace_id: UUID,
        source_session_id: UUID,
        manifest: ReplayManifestRef,
    ) -> HistoricalReplay | None:
        record = await self._repository.get_finalized(workspace_id, source_session_id, manifest)
        if record is None or record.manifest_ref is None or record.manifest_hash is None:
            return None
        body = await self._objects.get(record.manifest_ref)
        document = RunManifestDocument.model_validate_json(body, by_alias=True, by_name=True)
        if (
            run_manifest_bytes(document) != body
            or run_manifest_hash(document) != record.manifest_hash
        ):
            raise RunManifestConflict("stored manifest bytes are not canonical or hash-valid")
        events: list[LedgerEvent] = []
        next_seq = 1
        while True:
            batch = tuple(
                await self._ledger.read(
                    workspace_id, source_session_id, from_seq=next_seq, limit=1000
                )
            )
            events.extend(batch)
            if len(batch) < 1000:
                break
            next_seq = batch[-1].ledger_seq + 1
        return HistoricalReplay(
            workspace_id=workspace_id,
            source_session_id=source_session_id,
            manifest=record.ref(),
            ledger_events=tuple(events),
            steps=document.replay_steps,
            marl_bundles=document.marl_bundles,
        )
