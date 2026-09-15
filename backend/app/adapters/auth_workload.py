"""Minimal signed workload JWT verifier for the T15-01 fixture boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import jwt

from app.ports.mcp import InvalidWorkloadTokenError, WorkloadPrincipal, WorkloadTokenVerifier

__all__ = ["JWTWorkloadTokenIssuer", "JWTWorkloadTokenVerifier"]


class JWTWorkloadTokenIssuer:
    def __init__(self, *, secret: str, issuer: str, audience: str = "mcp-gateway") -> None:
        if not secret or not issuer or not audience:
            raise ValueError("workload JWT issuer configuration must not be blank")
        self._secret = secret
        self._issuer = issuer
        self._audience = audience

    def issue(
        self,
        *,
        subject: str = "reasoning-worker",
        service_role: str = "reasoning-worker",
        ttl_s: int = 60,
    ) -> str:
        if ttl_s <= 0 or ttl_s > 300:
            raise ValueError("workload token lifetime must be between 1 and 300 seconds")
        now = int(datetime.now(UTC).timestamp())
        token = jwt.encode(
            {
                "iss": self._issuer,
                "aud": self._audience,
                "sub": subject,
                "service_role": service_role,
                "iat": now,
                "exp": now + ttl_s,
            },
            self._secret,
            algorithm="HS256",
        )
        return str(token)


class JWTWorkloadTokenVerifier(WorkloadTokenVerifier):
    def __init__(
        self,
        *,
        secret: str,
        issuer: str,
        audience: str = "mcp-gateway",
        algorithm: str = "HS256",
        allowed_subject: str = "reasoning-worker",
        allowed_service_role: str = "reasoning-worker",
    ) -> None:
        if not secret or not issuer or not audience:
            raise ValueError("workload JWT verifier configuration must not be blank")
        self._secret = secret
        self._issuer = issuer
        self._audience = audience
        self._algorithm = algorithm
        self._allowed_subject = allowed_subject
        self._allowed_service_role = allowed_service_role

    async def verify(self, token: str) -> WorkloadPrincipal:
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["sub", "aud", "iss", "exp"]},
            )
        except (jwt.InvalidTokenError, TypeError, ValueError) as exc:
            raise InvalidWorkloadTokenError("invalid workload token") from exc
        subject = payload.get("sub")
        audience = payload.get("aud")
        expires_at = payload.get("exp")
        service_role = payload.get("service_role")
        if subject != self._allowed_subject or audience != self._audience:
            raise InvalidWorkloadTokenError("workload token subject or audience is not authorized")
        if not isinstance(expires_at, int) or expires_at <= int(datetime.now(UTC).timestamp()):
            raise InvalidWorkloadTokenError("workload token is expired")
        if service_role != self._allowed_service_role:
            raise InvalidWorkloadTokenError("workload token service role is not authorized")
        return WorkloadPrincipal(
            subject=subject,
            audience=audience,
            service_role=service_role,
            expires_at=expires_at,
        )
