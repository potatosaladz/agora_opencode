"""PostgreSQL persistence for immutable finalized run manifests."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.run_manifest import RunManifestRow
from app.domain.replay import ReplayManifestRef
from app.domain.run_manifest import (
    RunManifest,
    RunManifestConflict,
    RunManifestStatus,
)
from app.ports.storage import ObjectRef

__all__ = ["SqlAlchemyRunManifestRepository"]


def _manifest(row: RunManifestRow) -> RunManifest:
    reference = None
    if (
        row.manifest_ref is not None
        and row.manifest_bucket is not None
        and row.manifest_hash is not None
    ):
        reference = ObjectRef(
            bucket=row.manifest_bucket,
            key=row.manifest_ref,
            digest=row.manifest_hash,
            content_type="application/json",
            size=row.manifest_size,
        )
    return RunManifest(
        id=row.id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        source_session_id=row.source_session_id,
        manifest_version=row.manifest_version,
        status=RunManifestStatus(row.status),
        manifest_ref=reference,
        manifest_hash=row.manifest_hash,
        git_sha=row.git_sha,
        image_digests=dict(row.image_digests),
        model_pins=dict(row.model_pins),
        prompt_hashes=dict(row.prompt_hashes),
        seed=row.seed,
        created_at=row.created_at,
        finalized_at=row.finalized_at,
    )


class SqlAlchemyRunManifestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, manifest: RunManifest) -> RunManifest:
        existing = await self.get_for_session(
            manifest.workspace_id, manifest.session_id, for_update=True
        )
        if existing is not None:
            if existing == manifest:
                return existing
            raise RunManifestConflict("session already has a different run manifest")
        self._session.add(
            RunManifestRow(
                id=manifest.id,
                workspace_id=manifest.workspace_id,
                session_id=manifest.session_id,
                source_session_id=manifest.source_session_id,
                manifest_version=manifest.manifest_version,
                status=manifest.status.value,
                git_sha=manifest.git_sha,
                image_digests=manifest.image_digests,
                model_pins=manifest.model_pins,
                prompt_hashes=manifest.prompt_hashes,
                seed=manifest.seed,
                created_at=manifest.created_at,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise RunManifestConflict("run manifest identity already exists") from exc
        return manifest

    async def get_for_session(
        self, workspace_id: UUID, session_id: UUID, *, for_update: bool = False
    ) -> RunManifest | None:
        statement = select(RunManifestRow).where(
            RunManifestRow.workspace_id == workspace_id,
            RunManifestRow.session_id == session_id,
        )
        if for_update:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        return _manifest(row) if row is not None else None

    async def get_finalized(
        self, workspace_id: UUID, session_id: UUID, reference: ReplayManifestRef
    ) -> RunManifest | None:
        row = await self._session.scalar(
            select(RunManifestRow).where(
                RunManifestRow.workspace_id == workspace_id,
                RunManifestRow.session_id == session_id,
                RunManifestRow.id == reference.manifest_id,
                RunManifestRow.manifest_version == reference.manifest_version,
                RunManifestRow.manifest_hash == reference.manifest_hash,
                RunManifestRow.status == RunManifestStatus.FINALIZED.value,
            )
        )
        return _manifest(row) if row is not None else None

    async def finalize(self, manifest: RunManifest) -> RunManifest:
        if manifest.status is not RunManifestStatus.FINALIZED or manifest.manifest_ref is None:
            raise ValueError("finalize requires a finalized manifest")
        current = await self.get_for_session(
            manifest.workspace_id, manifest.session_id, for_update=True
        )
        if current is None:
            raise RunManifestConflict("run manifest does not exist")
        if current.status is RunManifestStatus.FINALIZED:
            if current == manifest:
                return current
            raise RunManifestConflict("finalized run manifest is immutable")
        row = await self._session.get(RunManifestRow, manifest.id)
        if row is None:
            raise RunManifestConflict("run manifest does not exist")
        row.status = manifest.status.value
        row.manifest_bucket = manifest.manifest_ref.bucket
        row.manifest_ref = manifest.manifest_ref.key
        row.manifest_hash = manifest.manifest_hash
        row.manifest_size = manifest.manifest_ref.size
        row.finalized_at = manifest.finalized_at
        await self._session.flush()
        return manifest
