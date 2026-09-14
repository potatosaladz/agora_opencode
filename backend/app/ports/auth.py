"""Authentication and workspace-role contracts.

Token parsing belongs to the HTTP security layer; cryptographic verification and identity
resolution are replaceable through ``AccessTokenVerifier``. A verifier must return membership
authority from trusted state, never an unverified role supplied by a client.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

__all__ = [
    "AccessTokenVerificationError",
    "AccessTokenVerifier",
    "VerifiedPrincipal",
    "WorkspaceRole",
]


class WorkspaceRole(StrEnum):
    """The complete Phase 1 workspace RBAC vocabulary."""

    ADMIN = "ADMIN"
    RESEARCHER = "RESEARCHER"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


@dataclass(frozen=True, slots=True)
class VerifiedPrincipal:
    """Identity and membership established by a trusted access-token verifier."""

    subject: str
    user_id: UUID
    workspace_id: UUID
    role: WorkspaceRole
    scopes: frozenset[str] = frozenset()


class AccessTokenVerificationError(ValueError):
    """A bearer token cannot establish a current workspace principal."""


@runtime_checkable
class AccessTokenVerifier(Protocol):
    """Verify a bearer token and resolve its active workspace membership."""

    async def verify(self, token: str) -> VerifiedPrincipal:
        """Return trusted identity context or raise ``AccessTokenVerificationError``."""
        ...
