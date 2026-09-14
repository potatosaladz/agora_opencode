"""Acceptance tests for fail-closed bearer authentication and workspace RBAC."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import Response

from app.api import create_app
from app.config import Settings
from app.ports.auth import (
    AccessTokenVerificationError,
    VerifiedPrincipal,
    WorkspaceRole,
)
from app.security import current_principal, public_route, require_roles, require_scopes
from tests.traceability import req


@dataclass(slots=True)
class StubVerifier:
    principals: dict[str, VerifiedPrincipal]

    async def verify(self, token: str) -> VerifiedPrincipal:
        try:
            return self.principals[token]
        except KeyError as exc:
            raise AccessTokenVerificationError("invalid token") from exc


def _settings() -> Settings:
    return Settings(
        environment="test",
        event_bus="inmemory",
        cache="inmemory",
        object_store="inmemory",
        secret_provider="env_file",
    )


def _principal(role: WorkspaceRole, *, workspace_id: UUID | None = None) -> VerifiedPrincipal:
    return VerifiedPrincipal(
        subject=f"oidc|{role.lower()}",
        user_id=uuid4(),
        workspace_id=workspace_id or uuid4(),
        role=role,
    )


def _install_verifier(app: FastAPI, principals: dict[str, VerifiedPrincipal]) -> None:
    app.state.container.access_token_verifier = StubVerifier(principals)


def _assert_problem(response: Response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == code


@req("NFR-010")
def test_health_and_readiness_are_the_only_public_registered_routes() -> None:
    app = create_app(_settings())

    @app.get("/test/protected")
    @require_roles(WorkspaceRole.VIEWER)
    async def protected() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/health")
    @public_route
    async def same_path_without_public_method() -> dict[str, bool]:
        return {"must_not_run": True}

    @app.get("/test/not-allow-listed")
    @public_route
    async def public_metadata_on_wrong_path() -> dict[str, bool]:
        return {"must_not_run": True}

    with TestClient(app) as client:
        app.state.readiness_checks = {}
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        _assert_problem(client.get("/test/protected"), 401, "AUTH_REQUIRED")
        _assert_problem(client.post("/health"), 401, "AUTH_REQUIRED")
        _assert_problem(client.get("/test/not-allow-listed"), 401, "AUTH_REQUIRED")
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404


@req("NFR-010")
def test_missing_malformed_and_invalid_bearer_tokens_return_401() -> None:
    app = create_app(_settings())

    @app.get("/test/protected")
    @require_roles(WorkspaceRole.VIEWER)
    async def protected() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        _install_verifier(app, {})
        for headers in (
            {},
            {"Authorization": "Basic value"},
            {"Authorization": "Bearer"},
            {"Authorization": "Bearer invalid"},
        ):
            response = client.get("/test/protected", headers=headers)
            _assert_problem(response, 401, "AUTH_REQUIRED")
            assert response.headers["WWW-Authenticate"] == "Bearer"


@req("NFR-010")
def test_route_policy_rejects_empty_or_noncanonical_roles() -> None:
    with pytest.raises(ValueError, match="canonical workspace roles"):
        require_roles()
    with pytest.raises(ValueError, match="canonical workspace roles"):
        require_roles("ADMIN")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="nonblank scopes"):
        require_scopes("")


@req("NFR-010")
def test_route_scope_policy_is_enforced_after_role_policy() -> None:
    app = create_app(_settings())
    workspace_id = uuid4()
    denied = _principal(WorkspaceRole.VIEWER, workspace_id=workspace_id)
    allowed = VerifiedPrincipal(
        denied.subject,
        denied.user_id,
        denied.workspace_id,
        denied.role,
        frozenset({"audit:read"}),
    )

    @app.get("/test/audit")
    @require_roles(WorkspaceRole.VIEWER)
    @require_scopes("audit:read")
    async def audit() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        _install_verifier(app, {"denied": denied, "allowed": allowed})
        _assert_problem(
            client.get("/test/audit", headers={"Authorization": "Bearer denied"}),
            403,
            "FORBIDDEN",
        )
        assert (
            client.get("/test/audit", headers={"Authorization": "Bearer allowed"}).status_code
            == 200
        )


@req("NFR-010")
def test_default_verifier_rejects_every_bearer_token() -> None:
    app = create_app(_settings())

    @app.get("/test/protected")
    @require_roles(WorkspaceRole.ADMIN)
    async def protected() -> dict[str, bool]:
        return {"must_not_run": True}

    with TestClient(app) as client:
        response = client.get("/test/protected", headers={"Authorization": "Bearer opaque"})

    _assert_problem(response, 401, "AUTH_REQUIRED")


@req("NFR-010")
def test_valid_token_without_route_policy_returns_403() -> None:
    app = create_app(_settings())
    viewer = _principal(WorkspaceRole.VIEWER)

    @app.get("/test/unmapped")
    async def unmapped() -> dict[str, bool]:
        return {"must_not_run": True}

    with TestClient(app) as client:
        _install_verifier(app, {"valid": viewer})
        response = client.get("/test/unmapped", headers={"Authorization": "Bearer valid"})

    _assert_problem(response, 403, "FORBIDDEN")


@req("NFR-010")
@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        (WorkspaceRole.ADMIN, 200),
        (WorkspaceRole.RESEARCHER, 403),
        (WorkspaceRole.OPERATOR, 200),
        (WorkspaceRole.VIEWER, 403),
    ],
)
def test_route_policy_is_enforced_for_every_canonical_role(
    role: WorkspaceRole, expected_status: int
) -> None:
    app = create_app(_settings())
    principal = _principal(role)

    @app.post("/test/operate")
    @require_roles(WorkspaceRole.ADMIN, WorkspaceRole.OPERATOR)
    async def operate() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        _install_verifier(app, {"valid": principal})
        response = client.post("/test/operate", headers={"Authorization": "bearer valid"})

    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.json() == {"ok": True}
    else:
        _assert_problem(response, 403, "FORBIDDEN")


@req("NFR-010")
def test_allowed_route_receives_verified_workspace_principal() -> None:
    app = create_app(_settings())
    workspace_id = uuid4()
    principal = _principal(WorkspaceRole.RESEARCHER, workspace_id=workspace_id)

    @app.get("/test/context")
    @require_roles(WorkspaceRole.RESEARCHER)
    async def context(request: Request) -> dict[str, str]:
        verified = current_principal(request)
        return {
            "subject": verified.subject,
            "user_id": str(verified.user_id),
            "workspace_id": str(verified.workspace_id),
            "role": verified.role.value,
        }

    with TestClient(app) as client:
        _install_verifier(app, {"valid": principal})
        response = client.get("/test/context", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 200
    assert response.json() == {
        "subject": principal.subject,
        "user_id": str(principal.user_id),
        "workspace_id": str(workspace_id),
        "role": "RESEARCHER",
    }
