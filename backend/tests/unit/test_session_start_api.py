"""HTTP contract tests for idempotent T4-02 session start."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from app.adapters.inmemory.session_lifecycle import InMemorySessionLifecycleStore
from app.adapters.inmemory.workflow import InMemoryWorkflowEngine
from app.api import create_app
from app.common.ids import public_id
from app.config import Settings
from app.domain.phase3_api import IdempotencyRecord
from app.domain.session_binding import (
    AgentDefinitionBinding,
    DraftSessionBinding,
    ObjectiveBinding,
    SessionBudget,
)
from app.ports.auth import VerifiedPrincipal, WorkspaceRole
from tests.traceability import req
from tests.unit.test_session_lifecycle import RecordingLedger

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 9))
NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)


class Verifier:
    async def verify(self, token: str) -> VerifiedPrincipal:
        assert token == "valid"
        return VerifiedPrincipal("oidc|user", U[2], U[0], WorkspaceRole.RESEARCHER)


class Sessions:
    def __init__(self, binding: DraftSessionBinding) -> None:
        self.binding = binding

    async def get(self, workspace_id: UUID, session_id: UUID) -> DraftSessionBinding | None:
        if (workspace_id, session_id) == (self.binding.workspace_id, self.binding.id):
            return self.binding
        return None


class Idempotency:
    def __init__(self) -> None:
        self.values: dict[tuple[UUID, str, str], IdempotencyRecord] = {}

    async def load_after_lock(
        self, workspace_id: UUID, operation: str, key: str
    ) -> IdempotencyRecord | None:
        return self.values.get((workspace_id, operation, key))

    async def save(
        self, workspace_id: UUID, operation: str, key: str, record: IdempotencyRecord
    ) -> None:
        self.values[(workspace_id, operation, key)] = record


class Transaction:
    def __init__(self, binding: DraftSessionBinding, lifecycle: Any) -> None:
        self.sessions = Sessions(binding)
        self.lifecycle = lifecycle
        self.idempotency = Idempotency()


class AppContainer:
    def __init__(self, base: Any, tx: Transaction) -> None:
        self.database = base.database
        self.readiness_checks = base.readiness_checks
        self.access_token_verifier = Verifier()
        self.workflow_engine = InMemoryWorkflowEngine()
        self._base = base
        self._tx = tx

    @asynccontextmanager
    async def reasoning_transaction(self, workspace_id: UUID) -> AsyncIterator[Transaction]:
        assert workspace_id == U[0]
        yield self._tx

    async def close(self) -> None:
        await self.workflow_engine.close()
        await self._base.close()


def binding() -> DraftSessionBinding:
    return DraftSessionBinding(
        id=U[1],
        workspace_id=U[0],
        problem_statement="How should the city reduce transport emissions?",
        agents=(
            AgentDefinitionBinding(
                workspace_id=U[0],
                session_id=U[1],
                agent_definition_id=U[3],
                logical_id=U[4],
                version=1,
            ),
        ),
        objectives=(ObjectiveBinding(workspace_id=U[0], session_id=U[1], artifact_id=U[5]),),
        constraints=(),
        budget=SessionBudget(max_rounds=4, max_tokens=10_000, max_usd="25"),
        created_by=U[2],
        created_at=NOW,
        updated_at=NOW,
    )


def settings() -> Settings:
    return Settings(
        environment="test",
        event_bus="inmemory",
        cache="inmemory",
        object_store="inmemory",
        secret_provider="env_file",
    )


@req("FR-105")
def test_start_returns_202_and_replays_stable_execution_identity() -> None:
    session = binding()
    lifecycle = InMemorySessionLifecycleStore(RecordingLedger())
    tx = Transaction(session, lifecycle)

    async def builder(config: Settings) -> Any:
        from app.composition import build_container

        base = await build_container(config)
        await lifecycle.add_draft(U[0], U[1], created_at=NOW)
        return AppContainer(base, tx)

    app = create_app(settings(), container_builder=builder)
    headers = {"Authorization": "Bearer valid", "Idempotency-Key": "start-once"}
    path = f"/api/v1/sessions/{public_id('session', U[1])}/start"

    with TestClient(app) as client:
        first = client.post(path, headers=headers)
        replay = client.post(path, headers=headers)
        read = client.get(
            f"/api/v1/sessions/{public_id('session', U[1])}",
            headers={"Authorization": "Bearer valid"},
        )

    assert first.status_code == replay.status_code == 202
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert first.json() == replay.json()
    assert first.json()["data"]["workflow_id"] == f"session-{U[1]}"
    assert first.json()["data"]["run_id"]
    assert read.json()["data"]["workflow_id"] == first.json()["data"]["workflow_id"]
