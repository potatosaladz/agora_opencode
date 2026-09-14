"""Authoritative read boundary for the session assumption register."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.domain.formalization import (
    FormalizationDecision,
    FormalizationRevision,
    FormalizationValidation,
)
from app.domain.reasoning import ReasoningArtifact
from app.domain.reasoning_graph import GraphNode
from app.domain.symbolic_evaluation import SymbolicEvaluation

__all__ = [
    "AssumptionRegisterReader",
    "AssumptionRegisterSnapshot",
    "ConstraintAnalysis",
    "RegisterRecommendation",
]


@dataclass(frozen=True, slots=True)
class ConstraintAnalysis:
    formalization: FormalizationRevision
    validation: FormalizationValidation | None
    decision: FormalizationDecision | None
    symbolic_evaluation: SymbolicEvaluation | None


@dataclass(frozen=True, slots=True)
class RegisterRecommendation:
    id: UUID
    alternative_id: UUID | None
    title: str


@dataclass(frozen=True, slots=True)
class AssumptionRegisterSnapshot:
    """Complete session facts needed before existing graph/Critique composition."""

    artifacts: tuple[ReasoningArtifact, ...]
    graph_nodes: tuple[GraphNode, ...]
    constraint_analyses: tuple[tuple[UUID, ConstraintAnalysis], ...]
    recommendations: tuple[RegisterRecommendation, ...]


@runtime_checkable
class AssumptionRegisterReader(Protocol):
    async def read(self, workspace_id: UUID, session_id: UUID) -> AssumptionRegisterSnapshot: ...
