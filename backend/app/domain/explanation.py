"""Read boundary for persisted decision-explanation inputs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from app.domain.consensus import ConsensusRunRecord
from app.domain.reasoning import ReasoningArtifact
from app.domain.reasoning_graph import GraphNode

__all__ = [
    "DecisionExplanationReader",
    "DecisionExplanationSnapshot",
    "ExplanationEmptyReason",
    "PersistedRecommendation",
]


class ExplanationEmptyReason(StrEnum):
    NO_CONSENSUS_RESULT = "NO_CONSENSUS_RESULT"
    EXPLANATION_UNAVAILABLE = "EXPLANATION_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class PersistedRecommendation:
    id: UUID
    alternative_id: UUID | None
    rank: int
    title: str
    statement: str
    conditions: tuple[Any, ...]
    risk_ids: tuple[UUID, ...]
    open_questions: tuple[Any, ...]
    is_override: bool
    override_by: UUID | None
    override_reason: str | None


@dataclass(frozen=True, slots=True)
class DecisionExplanationSnapshot:
    latest_consensus: ConsensusRunRecord | None
    recommendations: tuple[PersistedRecommendation, ...]
    artifacts: tuple[ReasoningArtifact, ...]
    graph_nodes: tuple[GraphNode, ...]


@runtime_checkable
class DecisionExplanationReader(Protocol):
    """Read all persisted inputs needed for one session explanation."""

    async def read(self, workspace_id: UUID, session_id: UUID) -> DecisionExplanationSnapshot: ...
