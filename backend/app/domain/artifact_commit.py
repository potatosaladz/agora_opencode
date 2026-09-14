"""Ports and values for atomic Phase 3 artifact lifecycle writes."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.domain.reasoning import LifecycleStatus, ReasoningArtifact

__all__ = ["AgentProposalStore", "ArtifactCommitError", "ReasoningArtifactStore"]


class ArtifactCommitError(Exception):
    """Artifact lifecycle request conflicts with persisted state."""


@runtime_checkable
class ReasoningArtifactStore(Protocol):
    """Caller-transaction-scoped typed artifact persistence boundary."""

    async def add(self, artifact: ReasoningArtifact) -> None: ...

    async def get_for_update(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> ReasoningArtifact | None: ...

    async def set_lifecycle(
        self,
        workspace_id: UUID,
        session_id: UUID,
        artifact_id: UUID,
        status: LifecycleStatus,
        *,
        updated_at: datetime,
    ) -> None: ...


@runtime_checkable
class AgentProposalStore(ReasoningArtifactStore, Protocol):
    """Artifact store able to serialize idempotent commits for one logical turn."""

    async def lock_agent_turn(
        self, workspace_id: UUID, session_id: UUID, turn_id: UUID
    ) -> None: ...
