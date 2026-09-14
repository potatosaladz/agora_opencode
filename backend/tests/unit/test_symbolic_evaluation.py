"""T11-03 exact-revision symbolic evidence service tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.application.symbolic_evaluation import SymbolicEvaluationContext, SymbolicEvaluationService
from app.domain.formalization import BooleanLiteral
from app.domain.symbolic_evaluation import SymbolicEvaluation
from app.domain.symbolic_unknown_policy import SymbolicAssuranceAction
from app.ports.symbolic import SymbolicReasoningResult, SymbolicStatus
from tests.traceability import req
from tests.unit.test_z3_symbolic_reasoner import U, revision

NOW = datetime(2026, 9, 12, 13, tzinfo=UTC)


class Reasoner:
    def __init__(self, result: SymbolicReasoningResult) -> None:
        self.result = result

    async def evaluate(self, model: object) -> SymbolicReasoningResult:
        return self.result


class Repository:
    def __init__(self) -> None:
        self.value: SymbolicEvaluation | None = None

    async def persist(self, evaluation: SymbolicEvaluation) -> SymbolicEvaluation:
        self.value = evaluation
        return evaluation

    async def get(self, workspace_id: UUID, evaluation_id: UUID) -> SymbolicEvaluation | None:
        return self.value


@req("FR-705", "FR-706")
async def test_service_persists_hash_bound_exact_revision_result() -> None:
    formalization = revision(BooleanLiteral(value=True))
    result = SymbolicReasoningResult(
        status=SymbolicStatus.SAT,
        formalization_revision_id=formalization.id,
        ast_hash=formalization.ast_hash,
        solver="test",
        solver_version="1",
        timeout_ms=10,
        configuration_id="test:10",
    )
    repository = Repository()
    persisted = await SymbolicEvaluationService(Reasoner(result), repository).evaluate(
        formalization,
        context=SymbolicEvaluationContext(U[7], U[5], U[6], NOW),
    )

    assert persisted is repository.value
    assert persisted.result == result
    assert persisted.evidence_hash.startswith("sha256:")


@req("FR-705", "FR-706")
async def test_service_rejects_result_for_another_revision() -> None:
    formalization = revision(BooleanLiteral(value=True))
    result = SymbolicReasoningResult(
        status=SymbolicStatus.SAT,
        formalization_revision_id=U[7],
        ast_hash=formalization.ast_hash,
        solver="test",
        solver_version="1",
        timeout_ms=10,
        configuration_id="test:10",
    )
    with pytest.raises(ValueError, match="exact revision"):
        await SymbolicEvaluationService(Reasoner(result), Repository()).evaluate(
            formalization,
            context=SymbolicEvaluationContext(U[7], U[5], U[6], NOW),
        )


@req("FR-708", "NFR-020")
async def test_service_persists_unknown_then_derives_defer_without_mutating_evidence() -> None:
    formalization = revision(BooleanLiteral(value=True))
    result = SymbolicReasoningResult(
        status=SymbolicStatus.UNKNOWN,
        formalization_revision_id=formalization.id,
        ast_hash=formalization.ast_hash,
        solver="test",
        solver_version="1",
        timeout_ms=10,
        configuration_id="test:10",
        reason_unknown="timeout",
    )
    repository = Repository()
    outcome = await SymbolicEvaluationService(Reasoner(result), repository).evaluate_with_policy(
        formalization,
        context=SymbolicEvaluationContext(U[7], U[5], U[6], NOW),
    )

    assert outcome.evaluation is repository.value
    assert outcome.evaluation.result == result
    assert outcome.evaluation.result.status is SymbolicStatus.UNKNOWN
    assert outcome.policy.action is SymbolicAssuranceAction.DEFER
    assert not outcome.policy.provides_affirmative_assurance
