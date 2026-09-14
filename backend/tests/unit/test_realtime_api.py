"""Authenticated SSE route and Last-Event-ID contract tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from app.api import create_app
from app.common.ids import public_id
from app.composition import build_container
from app.config import Settings
from app.ports.auth import VerifiedPrincipal, WorkspaceRole
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 5))


@dataclass(slots=True)
class Verifier:
    principal: VerifiedPrincipal

    async def verify(self, _token: str) -> VerifiedPrincipal:
        return self.principal


class Sessions:
    async def get(self, workspace_id: UUID, session_id: UUID) -> object | None:
        return object() if (workspace_id, session_id) == (U[0], U[1]) else None


@dataclass(slots=True)
class Transaction:
    sessions: Sessions


class Gateway:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, int]] = []

    async def stream(
        self, workspace_id: UUID, session_id: UUID, *, after: int
    ) -> AsyncIterator[bytes]:
        self.calls.append((workspace_id, session_id, after))
        yield b'id: 8\nevent: SESSION_COMPLETED\ndata: {"ledger_seq":8}\n\n'


class Container:
    def __init__(self, base: Any, gateway: Gateway) -> None:
        self._base = base
        self.access_token_verifier = Verifier(
            VerifiedPrincipal("oidc|viewer", U[2], U[0], WorkspaceRole.VIEWER)
        )
        self.database = base.database
        self.readiness_checks = base.readiness_checks
        self.realtime_gateway = gateway

    @asynccontextmanager
    async def reasoning_transaction(self, workspace_id: UUID) -> AsyncIterator[Transaction]:
        assert workspace_id == U[0]
        yield Transaction(Sessions())

    async def close(self) -> None:
        await self._base.close()


def settings() -> Settings:
    return Settings(
        environment="test",
        event_bus="inmemory",
        cache="inmemory",
        object_store="inmemory",
        secret_provider="env_file",
    )


@req("FR-106", "NFR-010")
def test_stream_is_authenticated_and_last_event_id_overrides_query_cursor() -> None:
    gateway = Gateway()

    async def builder(config: Settings) -> Any:
        return Container(await build_container(config), gateway)

    app = create_app(settings(), container_builder=builder)
    path = f"/api/v1/sessions/{public_id('session', U[1])}/events/stream?since=2"
    with TestClient(app) as client:
        unauthorized = client.get(path)
        response = client.get(
            path,
            headers={"Authorization": "Bearer valid", "Last-Event-ID": "7"},
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.text.startswith("id: 8\nevent: SESSION_COMPLETED")
    assert gateway.calls == [(U[0], U[1], 7)]
