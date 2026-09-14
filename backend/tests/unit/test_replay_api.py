"""T14-05 API exposure tests for exact replay controls."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.application.replay import SessionReplayService
from app.common.ids import public_id
from app.config import Settings
from app.domain.replay import (
    ReplayDifference,
    ReplayDifferenceKind,
    ReplayFailureReason,
    ReplayManifestRef,
    ReplayMismatch,
    ReplayMode,
    ReplayOutcome,
    ReplayResult,
    ReplayStepKind,
)
from app.domain.run_manifest import RunManifest, RunManifestStatus
from app.ports.auth import VerifiedPrincipal, WorkspaceRole
from app.ports.storage import ObjectRef
from tests.traceability import req

WS = UUID("018f0000-0000-7000-8000-000000000001")
OTHER_WS = UUID("018f0000-0000-7000-8000-000000000002")
SESSION = UUID("018f0000-0000-7000-8000-000000000003")
USER = UUID("018f0000-0000-7000-8000-000000000004")
MANIFEST_ID = uuid5(UUID("28ba96d9-cdea-4e80-b7fe-9cbdf8907344"), "manifest")
MANIFEST_HASH = "sha256:" + "a" * 64
NOW = datetime(2026, 9, 14, tzinfo=UTC)


def settings() -> Settings:
    return Settings(
        environment="test",
        event_bus="inmemory",
        cache="inmemory",
        object_store="inmemory",
        secret_provider="env_file",
    )


@dataclass(slots=True)
class Verifier:
    principal: VerifiedPrincipal

    async def verify(self, token: str) -> VerifiedPrincipal:
        assert token == "valid"
        return self.principal


class Sessions:
    async def get(self, workspace_id: UUID, session_id: UUID) -> object | None:
        return object() if (workspace_id, session_id) == (WS, SESSION) else None


class Manifests:
    def __init__(self) -> None:
        self.manifest = RunManifest(
            id=MANIFEST_ID,
            workspace_id=WS,
            session_id=SESSION,
            manifest_version=1,
            status=RunManifestStatus.FINALIZED,
            manifest_ref=ObjectRef(
                bucket="manifests",
                key="manifest.json",
                digest=MANIFEST_HASH,
                content_type="application/json",
                size=1,
            ),
            manifest_hash=MANIFEST_HASH,
            git_sha="1cad09a",
            image_digests={"backend": MANIFEST_HASH},
            model_pins={},
            prompt_hashes={},
            created_at=NOW,
            finalized_at=NOW,
        )

    async def get_for_session(
        self, workspace_id: UUID, session_id: UUID, *, for_update: bool = False
    ) -> RunManifest | None:
        del for_update
        if (workspace_id, session_id) == (WS, SESSION):
            return self.manifest
        return None

    async def get_finalized(
        self, workspace_id: UUID, session_id: UUID, reference: ReplayManifestRef
    ) -> RunManifest | None:
        if (
            workspace_id == self.manifest.workspace_id
            and session_id == self.manifest.session_id
            and reference.manifest_id == self.manifest.id
            and reference.manifest_version == self.manifest.manifest_version
            and reference.manifest_hash == self.manifest.manifest_hash
        ):
            return self.manifest
        return None


@dataclass(slots=True)
class Tx:
    sessions: Sessions
    run_manifests: Manifests
    ledger: Any = None


class Container:
    def __init__(self, base: Any, principal: VerifiedPrincipal, tx: Tx) -> None:
        self.database = base.database
        self.readiness_checks = base.readiness_checks
        self.object_store = base.object_store
        self.access_token_verifier = Verifier(principal)
        self._base = base
        self._tx = tx

    @asynccontextmanager
    async def reasoning_transaction(self, workspace_id: UUID) -> AsyncIterator[Tx]:
        assert workspace_id == self.access_token_verifier.principal.workspace_id
        yield self._tx

    async def close(self) -> None:
        await self._base.close()


def client_for(role: WorkspaceRole, *, workspace_id: UUID = WS) -> TestClient:
    principal = VerifiedPrincipal("oidc|reviewer", USER, workspace_id, role)
    tx = Tx(Sessions(), Manifests())

    async def builder(config: Settings) -> Any:
        from app.composition import build_container

        return Container(await build_container(config), principal, tx)

    return TestClient(create_app(settings(), container_builder=builder))


def replay_body(mode: ReplayMode, *, confirm_live: bool = False) -> dict[str, Any]:
    return {
        "mode": mode.value,
        "manifest": {
            "manifest_id": public_id("manifest", MANIFEST_ID),
            "manifest_version": 1,
            "manifest_hash": MANIFEST_HASH,
        },
        "confirm_live": confirm_live,
    }


def result(mode: ReplayMode, outcome: ReplayOutcome) -> ReplayResult:
    common: dict[str, Any] = {
        "mode": mode,
        "outcome": outcome,
        "workspace_id": WS,
        "source_session_id": SESSION,
        "source_manifest": ReplayManifestRef(
            manifest_id=MANIFEST_ID,
            manifest_version=1,
            manifest_hash=MANIFEST_HASH,
        ),
        "integrity_valid": True,
        "byte_identical": outcome is ReplayOutcome.VERIFIED,
        "checked_steps": 1,
    }
    if outcome is ReplayOutcome.FAILED:
        common["first_mismatch"] = ReplayMismatch(
            reason=ReplayFailureReason.UNKNOWN_IMPLEMENTATION,
            detail="the exact pinned implementation is unavailable",
            order=1,
            step_id=uuid4(),
        )
    if outcome is ReplayOutcome.DIFFERENT:
        common["differences"] = (
            ReplayDifference(
                order=1,
                step_id=uuid4(),
                kind=ReplayStepKind.SYMBOLIC,
                difference=ReplayDifferenceKind.STATUS,
                field="status",
                expected="UNKNOWN",
                actual="SAT",
            ),
        )
    if outcome is ReplayOutcome.LIVE_STARTED:
        common.update(
            {
                "checked_steps": 0,
                "replay_session_id": uuid4(),
                "replay_manifest_id": uuid4(),
                "replay_event_ids": (uuid4(),),
                "replay_result_ids": (uuid4(),),
            }
        )
    return ReplayResult.model_validate(common)


@req("FR-808", "NFR-003", "NFR-010", "NFR-014", "NFR-019")
@pytest.mark.parametrize("role", list(WorkspaceRole))
def test_manifest_read_is_authenticated_tenant_scoped_and_public(role: WorkspaceRole) -> None:
    client = client_for(role)
    path = f"/api/v1/sessions/{public_id('session', SESSION)}/manifest"
    with client:
        denied = client.get(path)
        response = client.get(path, headers={"Authorization": "Bearer valid"})
    assert denied.status_code == 401
    assert denied.headers["content-type"].startswith("application/problem+json")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["session_id"] == public_id("session", SESSION)
    assert data["manifest_id"] == public_id("manifest", MANIFEST_ID)
    assert data["manifest_version"] == 1
    assert data["manifest_hash"] == MANIFEST_HASH
    assert str(SESSION) not in response.text
    assert str(MANIFEST_ID) not in response.text


@req("FR-808", "NFR-010")
def test_replay_hides_cross_workspace_and_malformed_sessions() -> None:
    headers = {"Authorization": "Bearer valid"}
    hidden = client_for(WorkspaceRole.VIEWER, workspace_id=OTHER_WS)
    malformed = client_for(WorkspaceRole.VIEWER)
    with hidden:
        hidden_response = hidden.post(
            f"/api/v1/sessions/{public_id('session', SESSION)}/replay",
            headers=headers,
            json=replay_body(ReplayMode.STRICT),
        )
    with malformed:
        malformed_response = malformed.post(
            "/api/v1/sessions/ses_bad/replay",
            headers=headers,
            json=replay_body(ReplayMode.STRICT),
        )
    assert hidden_response.status_code == 404
    assert hidden_response.headers["content-type"].startswith("application/problem+json")
    assert malformed_response.status_code == 404
    assert malformed_response.headers["content-type"].startswith("application/problem+json")


@req("FR-808", "NFR-003", "NFR-014")
@pytest.mark.parametrize(
    ("mode", "outcome"),
    [
        (ReplayMode.STRICT, ReplayOutcome.VERIFIED),
        (ReplayMode.STRICT, ReplayOutcome.FAILED),
        (ReplayMode.TOLERANT, ReplayOutcome.MATCHED),
        (ReplayMode.TOLERANT, ReplayOutcome.DIFFERENT),
    ],
)
def test_replay_delegates_exact_manifest_and_exposes_mode_result(
    monkeypatch: pytest.MonkeyPatch, mode: ReplayMode, outcome: ReplayOutcome
) -> None:
    captured: list[Any] = []

    async def replay(_service: Any, replay_request: Any) -> ReplayResult:
        captured.append(replay_request)
        return result(mode, outcome)

    monkeypatch.setattr(SessionReplayService, "replay", replay)
    client = client_for(WorkspaceRole.VIEWER)
    with client:
        response = client.post(
            f"/api/v1/sessions/{public_id('session', SESSION)}/replay",
            headers={"Authorization": "Bearer valid"},
            json=replay_body(mode),
        )
    assert response.status_code == 200, response.text
    assert captured[0].workspace_id == WS
    assert captured[0].source_session_id == SESSION
    assert captured[0].manifest.manifest_id == MANIFEST_ID
    assert captured[0].manifest.manifest_hash == MANIFEST_HASH
    assert response.json()["data"]["mode"] == mode.value
    assert response.json()["data"]["outcome"] == outcome.value
    if outcome is ReplayOutcome.FAILED:
        assert response.json()["data"]["first_mismatch"]["reason"] == "UNKNOWN_IMPLEMENTATION"
    if outcome is ReplayOutcome.DIFFERENT:
        assert response.json()["data"]["differences"][0]["difference"] == "STATUS"


@req("FR-808", "NFR-003", "NFR-010")
@pytest.mark.parametrize("role", [WorkspaceRole.VIEWER, WorkspaceRole.OPERATOR])
def test_live_replay_denies_read_only_roles(role: WorkspaceRole) -> None:
    client = client_for(role)
    with client:
        response = client.post(
            f"/api/v1/sessions/{public_id('session', SESSION)}/replay",
            headers={"Authorization": "Bearer valid"},
            json=replay_body(ReplayMode.LIVE, confirm_live=True),
        )
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


@req("FR-808", "NFR-003", "NFR-010")
@pytest.mark.parametrize("role", [WorkspaceRole.ADMIN, WorkspaceRole.RESEARCHER])
def test_live_replay_requires_confirmation_then_exposes_fresh_lineage(
    monkeypatch: pytest.MonkeyPatch, role: WorkspaceRole
) -> None:
    launched = result(ReplayMode.LIVE, ReplayOutcome.LIVE_STARTED)

    async def replay(_service: Any, _request: Any) -> ReplayResult:
        return launched

    monkeypatch.setattr(SessionReplayService, "replay", replay)
    client = client_for(role)
    path = f"/api/v1/sessions/{public_id('session', SESSION)}/replay"
    with client:
        unconfirmed = client.post(
            path,
            headers={"Authorization": "Bearer valid"},
            json=replay_body(ReplayMode.LIVE),
        )
        confirmed = client.post(
            path,
            headers={"Authorization": "Bearer valid"},
            json=replay_body(ReplayMode.LIVE, confirm_live=True),
        )
    assert unconfirmed.status_code == 400
    assert confirmed.status_code == 200
    data = confirmed.json()["data"]
    assert data["outcome"] == "LIVE_STARTED"
    assert data["replay_session_id"] != data["source_session_id"]
    assert data["links"]["replay_session"] == "#/"


@req("FR-808", "NFR-010")
@pytest.mark.parametrize(
    "change",
    [
        {"mode": "REPLAY_UNKNOWN"},
        {
            "manifest": {
                "manifest_id": "man_bad",
                "manifest_version": 1,
                "manifest_hash": MANIFEST_HASH,
            }
        },
    ],
)
def test_replay_rejects_invalid_mode_and_manifest_with_problem_details(
    change: dict[str, Any],
) -> None:
    body = replay_body(ReplayMode.STRICT)
    body.update(change)
    client = client_for(WorkspaceRole.VIEWER)
    with client:
        response = client.post(
            f"/api/v1/sessions/{public_id('session', SESSION)}/replay",
            headers={"Authorization": "Bearer valid"},
            json=body,
        )
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] in {"VALIDATION_FAILED", "UNKNOWN_FIELD"}
