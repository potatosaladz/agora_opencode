"""Authenticated public boundary for exact session replay controls."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from app.api.errors import not_found
from app.api.replay_contracts import (
    ManifestData,
    ManifestResponse,
    ReplayData,
    ReplayDifferenceContract,
    ReplayManifestRefContract,
    ReplayMeta,
    ReplayMismatchContract,
    ReplayRequestContract,
    ReplayResponse,
)
from app.application.replay import ReplayImplementationRegistry, SessionReplayService
from app.application.run_manifest import PersistedReplaySource
from app.common.errors import Forbidden, ValidationFailed
from app.common.ids import parse_id, public_id
from app.domain.replay import (
    ReplayManifestRef,
    ReplayMismatch,
    ReplayMode,
    ReplayRequest,
    ReplayResult,
)
from app.ports.auth import WorkspaceRole
from app.security import current_principal, require_roles

router = APIRouter(prefix="/api/v1/sessions", tags=["replay"])
_READ = tuple(WorkspaceRole)
_LIVE_WRITE = (WorkspaceRole.ADMIN, WorkspaceRole.RESEARCHER)


def _implementations(request: Request) -> ReplayImplementationRegistry:
    registry = getattr(request.app.state.container, "replay_implementations", None)
    return (
        registry
        if isinstance(registry, ReplayImplementationRegistry)
        else ReplayImplementationRegistry()
    )


def _session_id(value: str) -> UUID:
    try:
        return parse_id("session", value)
    except ValueError as exc:
        raise not_found("session") from exc


def _manifest_ref(value: ReplayManifestRefContract) -> ReplayManifestRef:
    try:
        return ReplayManifestRef(
            manifest_id=parse_id("manifest", value.manifest_id),
            manifest_version=value.manifest_version,
            manifest_hash=value.manifest_hash,
        )
    except ValueError as exc:
        raise ValidationFailed("manifest contains a malformed public identifier") from exc


def _ref(value: ReplayManifestRef) -> ReplayManifestRefContract:
    return ReplayManifestRefContract(
        manifest_id=public_id("manifest", value.manifest_id),
        manifest_version=value.manifest_version,
        manifest_hash=value.manifest_hash,
    )


def _mismatch(value: ReplayMismatch) -> ReplayMismatchContract:
    return ReplayMismatchContract(
        reason=value.reason.value,
        detail=value.detail,
        order=value.order,
        step_id=public_id("replay_step", value.step_id) if value.step_id else None,
        expected_hash=value.expected_hash,
        actual_hash=value.actual_hash,
    )


def _result(value: ReplayResult, request: Request) -> ReplayResponse:
    source_id = public_id("session", value.source_session_id)
    replay_id = public_id("session", value.replay_session_id) if value.replay_session_id else None
    data = ReplayData(
        mode=value.mode,
        outcome=value.outcome.value,
        source_session_id=source_id,
        source_manifest=_ref(value.source_manifest),
        integrity_valid=value.integrity_valid,
        byte_identical=value.byte_identical,
        checked_steps=value.checked_steps,
        differences=tuple(
            ReplayDifferenceContract(
                order=item.order,
                step_id=public_id("replay_step", item.step_id),
                kind=item.kind.value,
                difference=item.difference.value,
                field=item.field,
                expected=item.expected,
                actual=item.actual,
            )
            for item in value.differences
        ),
        first_mismatch=_mismatch(value.first_mismatch) if value.first_mismatch else None,
        replay_session_id=replay_id,
        replay_manifest_id=(
            public_id("manifest", value.replay_manifest_id) if value.replay_manifest_id else None
        ),
        replay_event_ids=tuple(public_id("event", item) for item in value.replay_event_ids),
        replay_result_ids=tuple(
            public_id("replay_result", item) for item in value.replay_result_ids
        ),
        links={
            "source_session": "#/explanation",
            "manifest": f"/api/v1/sessions/{source_id}/manifest",
            "explanation": "#/explanation",
            **({"replay_session": "#/"} if replay_id else {}),
        },
    )
    return ReplayResponse(
        data=data,
        meta=ReplayMeta(
            request_id=str(request.state.correlation_id),
            schema_version=1,
            workspace_id=public_id("workspace", current_principal(request).workspace_id),
        ),
    )


@router.get("/{session_id}/manifest")
@require_roles(*_READ)
# trace: FR-808, NFR-003, NFR-010, NFR-014, NFR-019
async def get_replay_manifest(request: Request, session_id: str) -> JSONResponse:
    principal = current_principal(request)
    internal_session_id = _session_id(session_id)
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:
        if await tx.sessions.get(principal.workspace_id, internal_session_id) is None:
            raise not_found("session")
        manifest = await tx.run_manifests.get_for_session(
            principal.workspace_id, internal_session_id
        )
        if manifest is None or manifest.status.value != "FINALIZED":
            raise not_found("manifest")
        response = ManifestResponse(
            data=ManifestData(
                session_id=public_id("session", manifest.session_id),
                manifest_id=public_id("manifest", manifest.id),
                manifest_version=manifest.manifest_version,
                manifest_hash=manifest.manifest_hash or "",
                status=manifest.status.value,
                source_session_id=(
                    public_id("session", manifest.source_session_id)
                    if manifest.source_session_id
                    else None
                ),
                finalized_at=manifest.finalized_at.isoformat() if manifest.finalized_at else None,
                git_sha=manifest.git_sha,
                image_digests=manifest.image_digests,
            ),
            meta=ReplayMeta(
                request_id=str(request.state.correlation_id),
                schema_version=1,
                workspace_id=public_id("workspace", principal.workspace_id),
            ),
        )
    return JSONResponse(response.model_dump(mode="json"))


@router.post("/{session_id}/replay")
@require_roles(*_READ)
# trace: FR-808, NFR-003, NFR-010, NFR-014, NFR-019
async def replay_session(
    request: Request, session_id: str, body: ReplayRequestContract
) -> JSONResponse:
    principal = current_principal(request)
    if body.mode is ReplayMode.LIVE and principal.role not in _LIVE_WRITE:
        raise Forbidden("live replay requires an authorized execution role")
    if body.mode is ReplayMode.LIVE and not body.confirm_live:
        raise ValidationFailed("LIVE replay requires explicit confirmation")
    internal_session_id = _session_id(session_id)
    manifest = _manifest_ref(body.manifest)
    replay_request = ReplayRequest(
        workspace_id=principal.workspace_id,
        source_session_id=internal_session_id,
        manifest=manifest,
        mode=body.mode,
    )
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:
        if await tx.sessions.get(principal.workspace_id, internal_session_id) is None:
            raise not_found("session")
        service = SessionReplayService(
            PersistedReplaySource(
                tx.run_manifests, request.app.state.container.object_store, tx.ledger
            ),
            tx.ledger,
            _implementations(request),
            live_launcher=getattr(request.app.state.container, "live_replay_launcher", None),
        )
        result = await service.replay(replay_request)
    return JSONResponse(_result(result, request).model_dump(mode="json"))
