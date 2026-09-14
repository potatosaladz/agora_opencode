"""PostgreSQL adapter for immutable exact-revision symbolic evidence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.symbolic_evaluation import SymbolicEvaluationRow
from app.domain.symbolic_evaluation import (
    SymbolicEvaluation,
    SymbolicEvaluationConflict,
    SymbolicEvaluationRepository,
)
from app.ports.symbolic import (
    SymbolicCoreMember,
    SymbolicReasoningResult,
    SymbolicStatus,
    SymbolicValue,
    SymbolicValueKind,
    SymbolicWitnessBinding,
)

__all__ = ["SqlAlchemySymbolicEvaluationRepository"]


def _witness(binding: SymbolicWitnessBinding) -> dict[str, object]:
    return {
        "name": binding.name,
        "value": {
            "kind": binding.value.kind.value,
            "boolean": binding.value.boolean,
            "numerator": binding.value.numerator,
            "denominator": binding.value.denominator,
            "polynomial": list(binding.value.polynomial),
            "root_index": binding.value.root_index,
        },
    }


def _evaluation(row: SymbolicEvaluationRow) -> SymbolicEvaluation:
    return SymbolicEvaluation(
        id=row.id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        result=SymbolicReasoningResult(
            status=SymbolicStatus(row.status),
            formalization_revision_id=row.formalization_revision_id,
            ast_hash=row.ast_hash,
            solver=row.solver,
            solver_version=row.solver_version,
            timeout_ms=row.timeout_ms,
            configuration_id=row.configuration_id,
            reason_unknown=row.reason_unknown,
            witness=tuple(
                SymbolicWitnessBinding(
                    item["name"],
                    SymbolicValue(
                        SymbolicValueKind(item["value"]["kind"]),
                        boolean=item["value"]["boolean"],
                        numerator=item["value"]["numerator"],
                        denominator=item["value"]["denominator"],
                        polynomial=tuple(item["value"].get("polynomial", [])),
                        root_index=item["value"].get("root_index"),
                    ),
                )
                for item in row.witness
            ),
            unsat_core=tuple(SymbolicCoreMember(item["ast_path"]) for item in row.unsat_core),
        ),
        evidence_hash=row.evidence_hash,
        evaluated_at=row.evaluated_at,
        actor_id=row.actor_id,
        correlation_id=row.correlation_id,
    )


# trace: FR-705, FR-706
class SqlAlchemySymbolicEvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def persist(self, evaluation: SymbolicEvaluation) -> SymbolicEvaluation:
        identity = (
            f"{evaluation.workspace_id}:{evaluation.result.formalization_revision_id}:"
            f"{evaluation.result.solver}:{evaluation.result.solver_version}:"
            f"{evaluation.result.configuration_id}"
        )
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {"identity": identity},
        )
        existing = await self._session.scalar(
            select(SymbolicEvaluationRow).where(
                SymbolicEvaluationRow.workspace_id == evaluation.workspace_id,
                SymbolicEvaluationRow.formalization_revision_id
                == evaluation.result.formalization_revision_id,
                SymbolicEvaluationRow.solver == evaluation.result.solver,
                SymbolicEvaluationRow.solver_version == evaluation.result.solver_version,
                SymbolicEvaluationRow.configuration_id == evaluation.result.configuration_id,
            )
        )
        if existing is not None:
            persisted = _evaluation(existing)
            if (
                persisted.evidence_hash != evaluation.evidence_hash
                or persisted.result != evaluation.result
            ):
                raise SymbolicEvaluationConflict(
                    "exact symbolic evaluation identity already has different evidence"
                )
            return persisted
        result = evaluation.result
        self._session.add(
            SymbolicEvaluationRow(
                id=evaluation.id,
                workspace_id=evaluation.workspace_id,
                session_id=evaluation.session_id,
                formalization_revision_id=result.formalization_revision_id,
                ast_hash=result.ast_hash,
                status=result.status.value,
                witness=[_witness(binding) for binding in result.witness],
                unsat_core=[{"ast_path": member.ast_path} for member in result.unsat_core],
                reason_unknown=result.reason_unknown,
                solver=result.solver,
                solver_version=result.solver_version,
                timeout_ms=result.timeout_ms,
                configuration_id=result.configuration_id,
                evidence_hash=evaluation.evidence_hash,
                evaluated_at=evaluation.evaluated_at,
                actor_id=evaluation.actor_id,
                correlation_id=evaluation.correlation_id,
            )
        )
        await self._session.flush()
        return evaluation

    async def get(self, workspace_id: UUID, evaluation_id: UUID) -> SymbolicEvaluation | None:
        row = await self._session.scalar(
            select(SymbolicEvaluationRow).where(
                SymbolicEvaluationRow.workspace_id == workspace_id,
                SymbolicEvaluationRow.id == evaluation_id,
            )
        )
        return _evaluation(row) if row is not None else None


_PORT: type[SymbolicEvaluationRepository] = SqlAlchemySymbolicEvaluationRepository
