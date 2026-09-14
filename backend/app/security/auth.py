"""Fail-closed bearer authentication and deny-by-default route RBAC."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar, cast

from fastapi import Request

from app.common.errors import Forbidden, NotAuthenticated
from app.ports.auth import (
    AccessTokenVerificationError,
    VerifiedPrincipal,
    WorkspaceRole,
)

__all__ = [
    "UnconfiguredAccessTokenVerifier",
    "authorize_request",
    "current_principal",
    "public_route",
    "require_roles",
    "require_scopes",
]

_PUBLIC_ROUTES = frozenset({("GET", "/health"), ("GET", "/ready")})
_PUBLIC_ATTRIBUTE = "__agora_public_route__"
_POLICY_ATTRIBUTE = "__agora_workspace_roles__"
_SCOPES_ATTRIBUTE = "__agora_required_scopes__"
_Endpoint = TypeVar("_Endpoint", bound=Callable[..., object])


class UnconfiguredAccessTokenVerifier:
    """Safe production placeholder: no token is accepted until an IdP adapter is wired."""

    async def verify(self, token: str) -> VerifiedPrincipal:
        del token
        raise AccessTokenVerificationError("no access-token verifier is configured")


def public_route[Endpoint: Callable[..., object]](endpoint: Endpoint) -> Endpoint:
    """Mark one of the two allow-listed probe handlers as intentionally public."""
    setattr(endpoint, _PUBLIC_ATTRIBUTE, True)
    return endpoint


def require_roles(*roles: WorkspaceRole) -> Callable[[_Endpoint], _Endpoint]:
    """Attach the explicit workspace-role policy consumed by ``authorize_request``."""
    if not roles or any(not isinstance(role, WorkspaceRole) for role in roles):
        raise ValueError("a route authorization policy requires canonical workspace roles")
    allowed = frozenset(roles)

    def decorate(endpoint: _Endpoint) -> _Endpoint:
        setattr(endpoint, _POLICY_ATTRIBUTE, allowed)
        return endpoint

    return decorate


def require_scopes(*scopes: str) -> Callable[[_Endpoint], _Endpoint]:
    """Attach required trusted bearer scopes to one route."""
    if not scopes or any(not scope.strip() for scope in scopes):
        raise ValueError("a route scope policy requires nonblank scopes")
    required = frozenset(scopes)

    def decorate(endpoint: _Endpoint) -> _Endpoint:
        setattr(endpoint, _SCOPES_ATTRIBUTE, required)
        return endpoint

    return decorate


async def authorize_request(request: Request) -> None:
    """Authenticate every non-probe route, then enforce its explicit role policy."""
    route = request.scope.get("route")
    endpoint = getattr(route, "endpoint", None)
    route_key = (request.method, request.url.path)
    if route_key in _PUBLIC_ROUTES and getattr(endpoint, _PUBLIC_ATTRIBUTE, False) is True:
        return

    authorization = request.headers.get("Authorization", "")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise NotAuthenticated("a valid bearer token is required")

    verifier = request.app.state.container.access_token_verifier
    try:
        principal = await verifier.verify(parts[1])
    except AccessTokenVerificationError:
        raise NotAuthenticated("a valid bearer token is required") from None

    request.state.principal = principal
    allowed = getattr(endpoint, _POLICY_ATTRIBUTE, None)
    if not isinstance(allowed, frozenset):
        raise Forbidden("access denied")
    if principal.role not in cast(frozenset[WorkspaceRole], allowed):
        raise Forbidden("access denied")
    required_scopes: object = getattr(endpoint, _SCOPES_ATTRIBUTE, frozenset())
    if not isinstance(required_scopes, frozenset) or not required_scopes.issubset(principal.scopes):
        raise Forbidden("access denied")


def current_principal(request: Request) -> VerifiedPrincipal:
    """Return the principal established by the global authorization dependency."""
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, VerifiedPrincipal):
        raise NotAuthenticated("a valid bearer token is required")
    return principal
