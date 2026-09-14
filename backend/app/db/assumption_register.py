"""SQLAlchemy read projection for the complete session assumption register."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.formalization import _decision, _revision, _validation
from app.db.models.formalization import (
    FormalizationDecisionRow,
    FormalizationRow,
    FormalizationValidationRow,
)
from app.db.models.reasoning import ReasoningArtifactRow
from app.db.models.reasoning_graph import GraphNodeRow
from app.db.models.source_impact import RecommendationRow
from app.db.models.symbolic_evaluation import SymbolicEvaluationRow
from app.db.reasoning_artifacts import _from_row
from app.db.reasoning_graph import _node_from_row
from app.db.symbolic_evaluation import _evaluation
from app.domain.assumption_register import (
    AssumptionRegisterReader,
    AssumptionRegisterSnapshot,
    ConstraintAnalysis,
    RegisterRecommendation,
)

__all__ = ["SqlAlchemyAssumptionRegisterReader"]


# trace: FR-311, FR-705, FR-708, NFR-005, NFR-019
class SqlAlchemyAssumptionRegisterReader:
    """Read tenant/session-scoped facts without filtering or lifecycle omission."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def read(self, workspace_id: UUID, session_id: UUID) -> AssumptionRegisterSnapshot:
        artifact_rows = (
            await self._session.scalars(
                select(ReasoningArtifactRow)
                .where(
                    ReasoningArtifactRow.workspace_id == workspace_id,
                    ReasoningArtifactRow.session_id == session_id,
                )
                .order_by(
                    ReasoningArtifactRow.kind,
                    ReasoningArtifactRow.logical_id,
                    ReasoningArtifactRow.version,
                    ReasoningArtifactRow.id,
                )
            )
        ).all()
        node_rows = (
            await self._session.scalars(
                select(GraphNodeRow)
                .where(
                    GraphNodeRow.workspace_id == workspace_id,
                    GraphNodeRow.session_id == session_id,
                )
                .order_by(GraphNodeRow.id)
            )
        ).all()

        formalization_rows = (
            await self._session.scalars(
                select(FormalizationRow)
                .where(
                    FormalizationRow.workspace_id == workspace_id,
                    FormalizationRow.session_id == session_id,
                )
                .order_by(
                    FormalizationRow.source_artifact_id,
                    FormalizationRow.revision.desc(),
                    FormalizationRow.id.desc(),
                )
            )
        ).all()
        latest_formalization: dict[UUID, FormalizationRow] = {}
        for formalization_row in formalization_rows:
            latest_formalization.setdefault(formalization_row.source_artifact_id, formalization_row)

        formalization_ids = tuple(row.id for row in latest_formalization.values())
        validations: dict[UUID, FormalizationValidationRow] = {}
        decisions: dict[UUID, FormalizationDecisionRow] = {}
        evaluations: dict[UUID, SymbolicEvaluationRow] = {}
        if formalization_ids:
            validation_rows = (
                await self._session.scalars(
                    select(FormalizationValidationRow).where(
                        FormalizationValidationRow.workspace_id == workspace_id,
                        FormalizationValidationRow.formalization_revision_id.in_(formalization_ids),
                    )
                )
            ).all()
            validations = {row.formalization_revision_id: row for row in validation_rows}
            decision_rows = (
                await self._session.scalars(
                    select(FormalizationDecisionRow).where(
                        FormalizationDecisionRow.workspace_id == workspace_id,
                        FormalizationDecisionRow.formalization_revision_id.in_(formalization_ids),
                    )
                )
            ).all()
            decisions = {row.formalization_revision_id: row for row in decision_rows}
            evaluation_rows = (
                await self._session.scalars(
                    select(SymbolicEvaluationRow)
                    .where(
                        SymbolicEvaluationRow.workspace_id == workspace_id,
                        SymbolicEvaluationRow.session_id == session_id,
                        SymbolicEvaluationRow.formalization_revision_id.in_(formalization_ids),
                    )
                    .order_by(
                        SymbolicEvaluationRow.formalization_revision_id,
                        SymbolicEvaluationRow.evaluated_at.desc(),
                        SymbolicEvaluationRow.id.desc(),
                    )
                )
            ).all()
            for evaluation_row in evaluation_rows:
                evaluations.setdefault(evaluation_row.formalization_revision_id, evaluation_row)

        analyses = tuple(
            (
                artifact_id,
                ConstraintAnalysis(
                    formalization=_revision(row),
                    validation=(
                        _validation(validations[row.id]) if row.id in validations else None
                    ),
                    decision=_decision(decisions[row.id]) if row.id in decisions else None,
                    symbolic_evaluation=(
                        _evaluation(evaluations[row.id]) if row.id in evaluations else None
                    ),
                ),
            )
            for artifact_id, row in latest_formalization.items()
        )
        recommendation_rows = (
            await self._session.scalars(
                select(RecommendationRow)
                .where(
                    RecommendationRow.workspace_id == workspace_id,
                    RecommendationRow.session_id == session_id,
                )
                .order_by(RecommendationRow.rank, RecommendationRow.id)
            )
        ).all()
        return AssumptionRegisterSnapshot(
            artifacts=tuple(_from_row(row) for row in artifact_rows),
            graph_nodes=tuple(_node_from_row(row) for row in node_rows),
            constraint_analyses=analyses,
            recommendations=tuple(
                RegisterRecommendation(row.id, row.alternative_id, row.title)
                for row in recommendation_rows
            ),
        )


_PORT: type[AssumptionRegisterReader] = SqlAlchemyAssumptionRegisterReader
