"""Read-only persisted consensus explanation boundary for the Dissent View."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from app.ports.consensus import ConsensusExplanation

__all__ = ["DissentConsensusExplanationReader"]


@runtime_checkable
class DissentConsensusExplanationReader(Protocol):
    """Resolve one exact persisted explanation without recomputing consensus."""

    async def get(
        self, workspace_id: UUID, consensus_result_id: UUID
    ) -> ConsensusExplanation | None: ...
