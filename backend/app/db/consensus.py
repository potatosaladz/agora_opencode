"""PostgreSQL persistence for consensus results and explanations."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.source_impact import ConsensusExplanationRow, ConsensusResultRow
from app.domain.consensus import (
    ConsensusExplanation,
    ConsensusOutcome,
    ConsensusResultStore,
    ConsensusRunRecord,
)

__all__ = ["SqlAlchemyConsensusResultStore"]

# trace: FR-807, NFR-006
class SqlAlchemyConsensusResultStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_result(self, record: ConsensusRunRecord) -> None:
        self._session.add(
            ConsensusResultRow(
                id=record.id,
                workspace_id=record.workspace_id,
                session_id=record.session_id,
                round=record.round,
                strategy=record.strategy,
                strategy_version=record.strategy_version,
                outcome=record.outcome.value,
                selected_alternative_id=record.selected_alternative_id,
                pareto_set=list(record.pareto_set),
                support=record.support,
                dissent=record.dissent,
                abstention=record.abstention,
                coverage=record.coverage,
                constraint_report=record.constraint_report,
                conditions=list(record.conditions),
                input_hash=record.input_hash,
                created_at=record.created_at,
            )
        )
        await self._session.flush()

    async def get_result(self, workspace_id: UUID, result_id: UUID) -> ConsensusRunRecord | None:
        row = await self._session.scalar(
            select(ConsensusResultRow).where(
                ConsensusResultRow.workspace_id == workspace_id,
                ConsensusResultRow.id == result_id,
            )
        )
        return _result(row) if row is not None else None

    async def list_results(
        self,
        workspace_id: UUID,
        session_id: UUID,
        *,
        strategy: str | None = None,
    ) -> tuple[ConsensusRunRecord, ...]:
        query = select(ConsensusResultRow).where(
            ConsensusResultRow.workspace_id == workspace_id,
            ConsensusResultRow.session_id == session_id,
        )
        if strategy is not None:
            query = query.where(ConsensusResultRow.strategy == strategy)
        rows = (
            await self._session.scalars(
                query.order_by(ConsensusResultRow.round, ConsensusResultRow.id)
            )
        ).all()
        return tuple(_result(row) for row in rows)

    async def get_round_result(
        self,
        workspace_id: UUID,
        session_id: UUID,
        *,
        round: int,
    ) -> ConsensusRunRecord | None:
        if round < 1:
            raise ValueError("round must be a positive number")
        row = await self._session.scalar(
            select(ConsensusResultRow)
            .where(
                ConsensusResultRow.workspace_id == workspace_id,
                ConsensusResultRow.session_id == session_id,
                ConsensusResultRow.round == round,
            )
            .order_by(ConsensusResultRow.id)
            .limit(1)
        )
        return _result(row) if row is not None else None

    async def add_explanation(
        self,
        workspace_id: UUID,
        result_id: UUID,
        explanation: ConsensusExplanation,
    ) -> None:
        self._session.add(
            ConsensusExplanationRow(
                id=result_id,
                workspace_id=workspace_id,
                consensus_id=result_id,
                explanation=explanation.model_dump(mode="json"),
                created_at=datetime.now(UTC),
            )
        )
        await self._session.flush()

    async def get_explanation(
        self, workspace_id: UUID, result_id: UUID
    ) -> ConsensusExplanation | None:
        row = await self._session.scalar(
            select(ConsensusExplanationRow).where(
                ConsensusExplanationRow.workspace_id == workspace_id,
                ConsensusExplanationRow.consensus_id == result_id,
            )
        )
        return ConsensusExplanation.model_validate(row.explanation) if row is not None else None


def _result(row: ConsensusResultRow) -> ConsensusRunRecord:
    return ConsensusRunRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        round=row.round,
        strategy=row.strategy,
        strategy_version=row.strategy_version,
        outcome=ConsensusOutcome(row.outcome),
        selected_alternative_id=row.selected_alternative_id,
        pareto_set=tuple(row.pareto_set),
        support=str(row.support) if row.support is not None else None,
        dissent=str(row.dissent) if row.dissent is not None else None,
        abstention=str(row.abstention) if row.abstention is not None else None,
        coverage=str(row.coverage) if row.coverage is not None else None,
        constraint_report=row.constraint_report,
        conditions=tuple(row.conditions),
        input_hash=row.input_hash,
        created_at=row.created_at,
    )


_CONSENSUS_STORE_PORT: type[ConsensusResultStore] = SqlAlchemyConsensusResultStore
