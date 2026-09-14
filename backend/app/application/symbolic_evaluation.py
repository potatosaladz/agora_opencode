"""Caller-transaction-owned symbolic evaluation and evidence persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.formalization import FormalizationRevision
from app.domain.symbolic_evaluation import (
    SymbolicEvaluation,
    SymbolicEvaluationRepository,
    symbolic_evaluation_hash,
)
from app.domain.symbolic_unknown_policy import (
    SymbolicUnknownPolicy,
    SymbolicUnknownPolicyDecision,
)
from app.ports.symbolic import SymbolicReasoner

__all__ = ["SymbolicEvaluationContext", "SymbolicEvaluationOutcome", "SymbolicEvaluationService"]


@dataclass(frozen=True, slots=True)
class SymbolicEvaluationContext:
    evaluation_id: UUID
    actor_id: UUID
    correlation_id: UUID
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class SymbolicEvaluationOutcome:
    evaluation: SymbolicEvaluation
    policy: SymbolicUnknownPolicyDecision


# trace: FR-705, FR-706, FR-708
class SymbolicEvaluationService:
    def __init__(
        self,
        reasoner: SymbolicReasoner[FormalizationRevision],
        repository: SymbolicEvaluationRepository,
        unknown_policy: SymbolicUnknownPolicy | None = None,
    ) -> None:
        self._reasoner = reasoner
        self._repository = repository
        self._unknown_policy = unknown_policy or SymbolicUnknownPolicy()

    async def evaluate(
        self, revision: FormalizationRevision, *, context: SymbolicEvaluationContext
    ) -> SymbolicEvaluation:
        result = await self._reasoner.evaluate(revision)
        if result.formalization_revision_id != revision.id or result.ast_hash != revision.ast_hash:
            raise ValueError("symbolic result is not bound to the requested exact revision")
        evaluation = SymbolicEvaluation(
            id=context.evaluation_id,
            workspace_id=revision.workspace_id,
            session_id=revision.session_id,
            result=result,
            evidence_hash=symbolic_evaluation_hash(result),
            evaluated_at=context.evaluated_at,
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
        )
        return await self._repository.persist(evaluation)

    async def evaluate_with_policy(
        self, revision: FormalizationRevision, *, context: SymbolicEvaluationContext
    ) -> SymbolicEvaluationOutcome:
        """Persist the immutable solver fact, then derive the deterministic application action."""
        evaluation = await self.evaluate(revision, context=context)
        return SymbolicEvaluationOutcome(
            evaluation=evaluation,
            policy=self._unknown_policy.decide(evaluation.result),
        )
