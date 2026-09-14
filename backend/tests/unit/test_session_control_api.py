"""HTTP authorization, idempotency, directive, and legacy control regressions."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from app.adapters.inmemory.session_lifecycle import InMemorySessionLifecycleStore
from app.adapters.inmemory.workflow import InMemoryWorkflowEngine
from app.api import create_app
from app.common.ids import public_id
from app.config import Settings
from app.domain.session_lifecycle import SessionLifecycleState
from app.ports.auth import VerifiedPrincipal, WorkspaceRole
from app.ports.workflow import WorkflowInput
from tests.traceability import req
from tests.unit.test_session_lifecycle import NOW, RecordingLedger, U, transition
from tests.unit.test_session_start_api import Idempotency, Sessions, binding, settings


class Verifier:
    def __init__(self, role: WorkspaceRole) -> None:
        self._role = role

    async def verify(self, token: str) -> VerifiedPrincipal:
        assert token == "valid"
        return VerifiedPrincipal("oidc|user", U[2], U[0], self._role)


class Artifacts:
    def __init__(self, artifact: Any = None) -> None:
        self._artifact = artifact

    async def get(
        self, workspace_id: UUID, artifact_id: UUID, *, session_id: UUID | None = None
    ) -> Any:
        artifact = self._artifact
        if (
            artifact is not None
            and artifact.workspace_id == workspace_id
            and artifact.id == artifact_id
            and (session_id is None or artifact.session_id == session_id)
        ):
            return artifact
        return None


class Transaction:
    def __init__(self, lifecycle: InMemorySessionLifecycleStore, artifact: Any = None) -> None:
        self.sessions = Sessions(binding())
        self.lifecycle = lifecycle
        self.idempotency = Idempotency()
        self.artifacts = Artifacts(artifact)


class Container:
    def __init__(
        self,
        base: Any,
        tx: Transaction,
        workflow_engine: InMemoryWorkflowEngine,
        role: WorkspaceRole,
    ) -> None:
        self.database = base.database
        self.readiness_checks = base.readiness_checks
        self.access_token_verifier = Verifier(role)
        self.workflow_engine = workflow_engine
        self._base = base
        self._tx = tx

    @asynccontextmanager
    async def reasoning_transaction(self, workspace_id: UUID) -> AsyncIterator[Transaction]:
        assert workspace_id == U[0]
        yield self._tx

    async def close(self) -> None:
        await self.workflow_engine.close()
        await self._base.close()


def client_for(
    *, role: WorkspaceRole = WorkspaceRole.RESEARCHER, artifact: Any = None
) -> tuple[TestClient, InMemoryWorkflowEngine]:
    lifecycle = InMemorySessionLifecycleStore(RecordingLedger())
    engine = InMemoryWorkflowEngine()
    tx = Transaction(lifecycle, artifact)

    async def builder(config: Settings) -> Any:
        from app.composition import build_container

        base = await build_container(config)
        await lifecycle.add_draft(U[0], U[1], created_at=NOW)
        await lifecycle.attach_workflow(U[0], U[1], workflow_id=f"session-{U[1]}", run_id="run")
        await lifecycle.transition(
            transition(U[4], SessionLifecycleState.DRAFT, SessionLifecycleState.INITIALIZING)
        )
        await lifecycle.transition(
            transition(
                U[5],
                SessionLifecycleState.INITIALIZING,
                SessionLifecycleState.RUNNING,
                round_=1,
            )
        )
        await engine.start(
            f"session-{U[1]}", "Workflow", WorkflowInput(), task_queue="queue", timeout_s=1
        )
        return Container(base, tx, engine, role)

    return TestClient(create_app(settings(), container_builder=builder)), engine


@req("FR-104", "NFR-010")
def test_controls_require_write_role_and_replay_only_identical_requests() -> None:
    path = f"/api/v1/sessions/{public_id('session', U[1])}/pause"
    viewer_client, viewer_engine = client_for(role=WorkspaceRole.VIEWER)
    with viewer_client:
        forbidden = viewer_client.post(
            path,
            headers={"Authorization": "Bearer valid", "Idempotency-Key": "pause"},
            json={"reason": "Pause"},
        )
    assert forbidden.status_code == 403
    assert viewer_engine.signals == {}

    client, engine = client_for()
    headers = {"Authorization": "Bearer valid", "Idempotency-Key": "pause"}
    with client:
        accepted = client.post(path, headers=headers, json={"reason": "Pause"})
        replay = client.post(path, headers=headers, json={"reason": "Pause"})
        conflict = client.post(path, headers=headers, json={"reason": "Different"})
    assert accepted.status_code == replay.status_code == 202
    assert accepted.json()["data"]["status"] == "RUNNING"
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert conflict.status_code == 409
    assert len(engine.signals[f"session-{U[1]}"]) == 1


@req("FR-104", "NFR-010")
def test_human_input_rejects_malformed_and_missing_or_cross_session_artifacts() -> None:
    path = f"/api/v1/sessions/{public_id('session', U[1])}/human-input"
    headers = {"Authorization": "Bearer valid", "Idempotency-Key": "directive"}
    cross_session = SimpleNamespace(id=U[7], workspace_id=U[0], session_id=U[6])
    client, engine = client_for(artifact=cross_session)
    with client:
        malformed = client.post(
            path,
            headers=headers,
            json={"reason": "Help", "kind": "UNKNOWN", "instruction": "Proceed"},
        )
        missing = client.post(
            path,
            headers=headers,
            json={
                "reason": "Help",
                "kind": "INJECT_EVIDENCE",
                "instruction": "Use this",
                "artifact_ids": [public_id("artifact", U[7])],
            },
        )
    assert malformed.status_code == 400
    assert missing.status_code == 404
    assert engine.signals == {}


@req("FR-104", "NFR-010")
def test_legacy_terminate_enqueues_typed_cancel_without_deleting_history() -> None:
    client, engine = client_for()
    with client:
        response = client.post(
            f"/api/v1/sessions/{public_id('session', U[1])}/terminate",
            headers={"Authorization": "Bearer valid", "Idempotency-Key": "terminate"},
            json={"reason": "Stop safely"},
        )
    assert response.status_code == 202
    signal = engine.signals[f"session-{U[1]}"][0]
    assert signal.payload["kind"] == "CANCEL"
    assert signal.payload["reason"] == "Stop safely"
