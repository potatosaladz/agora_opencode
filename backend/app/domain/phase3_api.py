"""Ports used by the tenant-scoped Phase 3 HTTP application boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from app.domain.artifact_commit import AgentProposalStore
from app.domain.reasoning import ReasoningArtifact
from app.domain.session_binding import (
    AgentDefinitionBinding,
    DraftSessionBinding,
)

__all__ = [
    "IdempotencyRecord",
    "IdempotencyStore",
    "Phase3ArtifactStore",
    "Phase3SessionStore",
]


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """The exact successful HTTP result retained for deterministic replay."""

    request_hash: str
    status_code: int
    response_body: dict[str, Any]


@runtime_checkable
class IdempotencyStore(Protocol):
    """Serialize and persist one tenant/operation/key result in the caller transaction."""

    async def load_after_lock(
        self, workspace_id: UUID, operation: str, key: str
    ) -> IdempotencyRecord | None: ...

    async def save(
        self,
        workspace_id: UUID,
        operation: str,
        key: str,
        record: IdempotencyRecord,
    ) -> None: ...


@runtime_checkable
class Phase3ArtifactStore(AgentProposalStore, Protocol):
    """Artifact writer plus the tenant-scoped API read operation."""

    async def get(
        self, workspace_id: UUID, artifact_id: UUID, *, session_id: UUID | None = None
    ) -> ReasoningArtifact | None: ...


@runtime_checkable
class Phase3SessionStore(Protocol):
    """Caller-transaction-scoped persistence for the immutable Phase 3 binding."""

    async def resolve_agents(
        self, workspace_id: UUID, session_id: UUID, agent_definition_ids: tuple[UUID, ...]
    ) -> tuple[AgentDefinitionBinding, ...]: ...

    async def add(self, binding: DraftSessionBinding) -> None: ...

    async def bind_artifacts(self, binding: DraftSessionBinding) -> None: ...

    async def get(self, workspace_id: UUID, session_id: UUID) -> DraftSessionBinding | None: ...
