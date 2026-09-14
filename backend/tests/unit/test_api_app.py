"""Endpoint-level acceptance tests for the FastAPI application factory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import Body
from fastapi.testclient import TestClient

from app.api import create_app
from app.common.errors import VersionConflict
from app.composition import build_container
from app.config import Settings
from app.ports.auth import AccessTokenVerificationError, VerifiedPrincipal, WorkspaceRole
from app.ports.health import ComponentHealth, HealthStatus
from app.security import require_roles
from tests.traceability import req


@dataclass(slots=True)
class _TestVerifier:
    principal: VerifiedPrincipal

    async def verify(self, token: str) -> VerifiedPrincipal:
        if token != "valid":
            raise AccessTokenVerificationError("invalid token")
        return self.principal


def _authorize(app: Any) -> dict[str, str]:
    app.state.container.access_token_verifier = _TestVerifier(
        VerifiedPrincipal(
            subject="oidc|admin",
            user_id=uuid4(),
            workspace_id=uuid4(),
            role=WorkspaceRole.ADMIN,
        )
    )
    return {"Authorization": "Bearer valid"}


def _settings() -> Settings:
    return Settings(
        environment="test",
        service_name="api-test",
        code_version="test-sha",
        event_bus="inmemory",
        cache="inmemory",
        object_store="inmemory",
        secret_provider="env_file",
    )


def _assert_problem(response: Any, *, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = response.json()
    assert body["status"] == status
    assert body["code"] == code
    assert body["trace_id"] == response.headers["X-Request-Id"]
    assert body["type"].endswith(code.lower())
    return body


@req("NFR-016")
def test_health_is_live_without_consulting_dependencies() -> None:
    app = create_app(_settings())

    with TestClient(app) as client:

        async def down() -> ComponentHealth:
            raise RuntimeError("must not be called by liveness")

        app.state.readiness_checks = {"database": down}
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "api-test",
        "version": "test-sha",
    }


@req("NFR-016")
def test_ready_reports_dependency_failure_without_changing_liveness() -> None:
    app = create_app(_settings())

    with TestClient(app) as client:

        async def down() -> ComponentHealth:
            return ComponentHealth("database", HealthStatus.DOWN, {"reason": "unreachable"})

        app.state.readiness_checks = {"database": down}
        readiness = client.get("/ready")
        liveness = client.get("/health")

    assert readiness.status_code == 503
    assert readiness.json() == {
        "status": "down",
        "service": "api-test",
        "version": "test-sha",
        "components": {"database": {"status": "down", "details": {"reason": "unreachable"}}},
    }
    assert liveness.status_code == 200
    assert liveness.json()["status"] == "ok"


@req("NFR-016")
def test_lifespan_closes_the_composition_container() -> None:
    app = create_app(_settings(), container_builder=build_container)

    with TestClient(app):
        container = app.state.container
        assert container._closed is False

    assert container._closed is True


@req("NFR-016")
def test_domain_error_uses_problem_envelope() -> None:
    app = create_app(_settings())

    @app.get("/test/domain-error")
    @require_roles(WorkspaceRole.ADMIN)
    async def domain_error() -> None:
        raise VersionConflict("resource changed", current_version=7)

    with TestClient(app) as client:
        headers = _authorize(app) | {"X-Request-Id": "req-domain"}
        response = client.get("/test/domain-error", headers=headers)

    body = _assert_problem(response, status=409, code="VERSION_CONFLICT")
    assert body["current_version"] == 7
    assert body["trace_id"] == "req-domain"


@req("NFR-016")
def test_request_validation_error_uses_problem_envelope() -> None:
    app = create_app(_settings())

    @app.post("/test/validate")
    @require_roles(WorkspaceRole.ADMIN)
    async def validate(value: int = Body(embed=True)) -> dict[str, int]:
        return {"value": value}

    with TestClient(app) as client:
        response = client.post(
            "/test/validate", json={"value": "not-an-int"}, headers=_authorize(app)
        )

    body = _assert_problem(response, status=400, code="VALIDATION_FAILED")
    assert body["errors"][0]["pointer"] == "/body/value"


@req("NFR-016")
def test_unhandled_error_uses_safe_problem_envelope() -> None:
    app = create_app(_settings())

    @app.get("/test/crash")
    @require_roles(WorkspaceRole.ADMIN)
    async def crash() -> None:
        raise RuntimeError("sensitive internal detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test/crash", headers=_authorize(app))

    body = _assert_problem(response, status=500, code="INTERNAL")
    assert body["detail"] == "an unexpected error occurred"
    assert "sensitive" not in response.text


@req("NFR-016")
def test_router_404_uses_problem_envelope() -> None:
    app = create_app(_settings())

    with TestClient(app) as client:
        response = client.get("/does-not-exist")

    _assert_problem(response, status=404, code="NOT_FOUND")
