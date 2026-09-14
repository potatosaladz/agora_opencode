"""SQLAlchemy projection for persisted decision-explanation inputs."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.reasoning import ReasoningArtifactRow
from app.db.models.reasoning_graph import GraphNodeRow
from app.db.models.source_impact import ConsensusResultRow, RecommendationRow
from app.db.reasoning_artifacts import _from_row
from app.db.reasoning_graph import _node_from_row
from app.domain.consensus import ConsensusOutcome, ConsensusRunRecord
from app.domain.explanation import (
    DecisionExplanationReader,
    DecisionExplanationSnapshot,
    PersistedRecommendation,
)

__all__ = ["SqlAlchemyDecisionExplanationReader"]


# trace: FR-504, FR-505, FR-605, FR-609, FR-804, FR-805, FR-901, NFR-005, NFR-019
class SqlAlchemyDecisionExplanationReader:
    """Read immutable rows only, with no lifecycle or omission filters."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def read(self, workspace_id: UUID, session_id: UUID) -> DecisionExplanationSnapshot:
        result_row = await self._session.scalar(
            select(ConsensusResultRow)
            .where(
                ConsensusResultRow.workspace_id == workspace_id,
                ConsensusResultRow.session_id == session_id,
            )
            .order_by(ConsensusResultRow.round.desc(), ConsensusResultRow.id.desc())
            .limit(1)
        )
        recommendation_rows = []
        if result_row is not None:
            recommendation_rows = list(
                (
                    await self._session.scalars(
                        select(RecommendationRow)
                        .where(
                            RecommendationRow.workspace_id == workspace_id,
                            RecommendationRow.session_id == session_id,
                            RecommendationRow.consensus_id == result_row.id,
                        )
                        .order_by(RecommendationRow.rank, RecommendationRow.id)
                    )
                ).all()
            )
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
        graph_node_rows = (
            await self._session.scalars(
                select(GraphNodeRow)
                .where(
                    GraphNodeRow.workspace_id == workspace_id,
                    GraphNodeRow.session_id == session_id,
                )
                .order_by(GraphNodeRow.id)
            )
        ).all()
        latest = None
        if result_row is not None:
            latest = ConsensusRunRecord(
                id=result_row.id,
                workspace_id=result_row.workspace_id,
                session_id=result_row.session_id,
                round=result_row.round,
                strategy=result_row.strategy,
                strategy_version=result_row.strategy_version,
                outcome=ConsensusOutcome(result_row.outcome),
                selected_alternative_id=result_row.selected_alternative_id,
                pareto_set=tuple(result_row.pareto_set),
                support=str(result_row.support) if result_row.support is not None else None,
                dissent=str(result_row.dissent) if result_row.dissent is not None else None,
                abstention=(
                    str(result_row.abstention) if result_row.abstention is not None else None
                ),
                coverage=str(result_row.coverage) if result_row.coverage is not None else None,
                constraint_report=result_row.constraint_report,
                conditions=tuple(result_row.conditions),
                input_hash=result_row.input_hash,
                created_at=result_row.created_at,
            )
        return DecisionExplanationSnapshot(
            latest_consensus=latest,
            recommendations=tuple(
                PersistedRecommendation(
                    id=row.id,
                    alternative_id=row.alternative_id,
                    rank=row.rank,
                    title=row.title,
                    statement=row.statement,
                    conditions=tuple(row.conditions),
                    risk_ids=tuple(row.risks),
                    open_questions=tuple(row.open_questions),
                    is_override=row.is_override,
                    override_by=row.override_by,
                    override_reason=row.override_reason,
                )
                for row in recommendation_rows
            ),
            artifacts=tuple(_from_row(row) for row in artifact_rows),
            graph_nodes=tuple(_node_from_row(row) for row in graph_node_rows),
        )


_PORT: type[DecisionExplanationReader] = SqlAlchemyDecisionExplanationReader
