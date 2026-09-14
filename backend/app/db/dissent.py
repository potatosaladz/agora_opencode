"""PostgreSQL reader for exact persisted Dissent View consensus explanations."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.source_impact import ConsensusExplanationRow
from app.domain.dissent import DissentConsensusExplanationReader
from app.ports.consensus import ConsensusExplanation

__all__ = ["SqlAlchemyDissentConsensusExplanationReader"]


class SqlAlchemyDissentConsensusExplanationReader:
    """Read canonical JSON through Pydantic's JSON-aware strict validation path."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, workspace_id: UUID, consensus_result_id: UUID
    ) -> ConsensusExplanation | None:
        row = await self._session.scalar(
            select(ConsensusExplanationRow).where(
                ConsensusExplanationRow.workspace_id == workspace_id,
                ConsensusExplanationRow.consensus_id == consensus_result_id,
            )
        )
        if row is None:
            return None
        return ConsensusExplanation.model_validate_json(
            json.dumps(row.explanation, separators=(",", ":"), sort_keys=True)
        )


_DISSENT_READER_PORT: type[DissentConsensusExplanationReader] = (
    SqlAlchemyDissentConsensusExplanationReader
)
