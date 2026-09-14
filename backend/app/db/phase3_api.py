"""PostgreSQL adapters for Phase 3 session reads/writes and API idempotency."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentDefinitionRow
from app.db.models.api import IdempotencyRecordRow
from app.db.models.reasoning import (
    SessionAgentRow,
    SessionConstraintRow,
    SessionObjectiveRow,
    SessionRow,
)
from app.domain.phase3_api import IdempotencyRecord, IdempotencyStore, Phase3SessionStore
from app.domain.session_binding import (
    AgentDefinitionBinding,
    ConstraintBinding,
    DraftSessionBinding,
    ObjectiveBinding,
    SessionBudget,
)

__all__ = ["SqlAlchemyIdempotencyStore", "SqlAlchemyPhase3SessionStore"]


class SqlAlchemyIdempotencyStore:
    """Use a transaction advisory lock to serialize each idempotency scope."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_after_lock(
        self, workspace_id: UUID, operation: str, key: str
    ) -> IdempotencyRecord | None:
        lock_name = f"{workspace_id}:{operation}:{key}"
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_name, 0))"),
            {"lock_name": lock_name},
        )
        row = await self._session.get(
            IdempotencyRecordRow,
            {"workspace_id": workspace_id, "operation": operation, "key": key},
        )
        if row is None:
            return None
        return IdempotencyRecord(
            request_hash=row.request_hash,
            status_code=row.status_code,
            response_body=row.response_body,
        )

    async def save(
        self,
        workspace_id: UUID,
        operation: str,
        key: str,
        record: IdempotencyRecord,
    ) -> None:
        self._session.add(
            IdempotencyRecordRow(
                workspace_id=workspace_id,
                operation=operation,
                key=key,
                request_hash=record.request_hash,
                status_code=record.status_code,
                response_body=record.response_body,
            )
        )
        await self._session.flush()


class SqlAlchemyPhase3SessionStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve_agents(
        self, workspace_id: UUID, session_id: UUID, agent_definition_ids: tuple[UUID, ...]
    ) -> tuple[AgentDefinitionBinding, ...]:
        rows = (
            await self._session.scalars(
                select(AgentDefinitionRow).where(
                    AgentDefinitionRow.workspace_id == workspace_id,
                    AgentDefinitionRow.id.in_(agent_definition_ids),
                )
            )
        ).all()
        by_id = {row.id: row for row in rows}
        return tuple(
            AgentDefinitionBinding(
                workspace_id=workspace_id,
                session_id=session_id,
                agent_definition_id=agent_id,
                logical_id=by_id[agent_id].logical_id,
                version=by_id[agent_id].version,
            )
            for agent_id in agent_definition_ids
            if agent_id in by_id
        )

    async def add(self, binding: DraftSessionBinding) -> None:
        self._session.add(
            SessionRow(
                id=binding.id,
                workspace_id=binding.workspace_id,
                status=binding.status.value,
                problem_statement=binding.problem_statement,
                max_rounds=binding.budget.max_rounds,
                budget_tokens=binding.budget.max_tokens,
                budget_usd=Decimal(binding.budget.max_usd),
                deadline_at=binding.budget.deadline_at,
                round=binding.round,
                created_by=binding.created_by,
                created_at=binding.created_at,
                updated_at=binding.updated_at,
            )
        )
        await self._session.flush()
        self._session.add_all(
            SessionAgentRow(
                workspace_id=item.workspace_id,
                session_id=item.session_id,
                agent_def_id=item.agent_definition_id,
                bound_at=binding.created_at,
            )
            for item in binding.agents
        )
        await self._session.flush()

    async def bind_artifacts(self, binding: DraftSessionBinding) -> None:
        self._session.add_all(
            SessionObjectiveRow(
                workspace_id=item.workspace_id,
                session_id=item.session_id,
                artifact_id=item.artifact_id,
            )
            for item in binding.objectives
        )
        self._session.add_all(
            SessionConstraintRow(
                workspace_id=item.workspace_id,
                session_id=item.session_id,
                artifact_id=item.artifact_id,
            )
            for item in binding.constraints
        )
        await self._session.flush()

    async def get(self, workspace_id: UUID, session_id: UUID) -> DraftSessionBinding | None:
        row = await self._session.scalar(
            select(SessionRow).where(
                SessionRow.workspace_id == workspace_id,
                SessionRow.id == session_id,
            )
        )
        if row is None:
            return None
        agent_rows = (
            await self._session.execute(
                select(SessionAgentRow, AgentDefinitionRow)
                .join(
                    AgentDefinitionRow,
                    (AgentDefinitionRow.id == SessionAgentRow.agent_def_id)
                    & (AgentDefinitionRow.workspace_id == SessionAgentRow.workspace_id),
                )
                .where(
                    SessionAgentRow.workspace_id == workspace_id,
                    SessionAgentRow.session_id == session_id,
                )
                .order_by(SessionAgentRow.agent_def_id)
            )
        ).all()
        objective_ids = tuple(
            await self._session.scalars(
                select(SessionObjectiveRow.artifact_id)
                .where(
                    SessionObjectiveRow.workspace_id == workspace_id,
                    SessionObjectiveRow.session_id == session_id,
                )
                .order_by(SessionObjectiveRow.artifact_id)
            )
        )
        constraint_ids = tuple(
            await self._session.scalars(
                select(SessionConstraintRow.artifact_id)
                .where(
                    SessionConstraintRow.workspace_id == workspace_id,
                    SessionConstraintRow.session_id == session_id,
                )
                .order_by(SessionConstraintRow.artifact_id)
            )
        )
        return DraftSessionBinding(
            id=row.id,
            workspace_id=row.workspace_id,
            problem_statement=row.problem_statement,
            agents=tuple(
                AgentDefinitionBinding(
                    workspace_id=session_agent.workspace_id,
                    session_id=session_agent.session_id,
                    agent_definition_id=session_agent.agent_def_id,
                    logical_id=agent.logical_id,
                    version=agent.version,
                )
                for session_agent, agent in agent_rows
            ),
            objectives=tuple(
                ObjectiveBinding(
                    workspace_id=workspace_id, session_id=session_id, artifact_id=artifact_id
                )
                for artifact_id in objective_ids
            ),
            constraints=tuple(
                ConstraintBinding(
                    workspace_id=workspace_id, session_id=session_id, artifact_id=artifact_id
                )
                for artifact_id in constraint_ids
            ),
            budget=SessionBudget(
                max_rounds=row.max_rounds,
                max_tokens=row.budget_tokens,
                max_usd=format(row.budget_usd, "f"),
                deadline_at=row.deadline_at,
            ),
            round=0,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


_IDEMPOTENCY_PORT: type[IdempotencyStore] = SqlAlchemyIdempotencyStore
_SESSION_PORT: type[Phase3SessionStore] = SqlAlchemyPhase3SessionStore
