"""PostgreSQL membership history and durable usage aggregation."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentDefinitionRow, LLMCallRecordRow
from app.db.models.reasoning import (
    SessionAgentInterventionRow,
    SessionAgentRow,
    SessionRow,
)
from app.db.models.reasoning_ledger import ReasoningEventRow
from app.db.models.session_lifecycle import SessionLifecycleRow
from app.domain.agent_registry import AgentDefinition, AgentRoleKind, AgentStatus
from app.domain.coordinator_policy import (
    BudgetCeiling,
    BudgetUsage,
    CoordinatorPolicyStore,
    MembershipIntervention,
    MembershipInterventionKind,
    MembershipSnapshot,
)
from app.domain.reasoning_ledger import LedgerIntegrityError

__all__ = ["SqlAlchemyCoordinatorPolicyStore"]


class SqlAlchemyCoordinatorPolicyStore:
    """Map coordinator policy to rows inside one caller-owned RLS transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_membership(self, workspace_id: UUID, session_id: UUID) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_name, 0))"),
            {"lock_name": f"session-membership:{workspace_id}:{session_id}"},
        )
        await self._session.scalar(
            select(SessionLifecycleRow)
            .where(
                SessionLifecycleRow.workspace_id == workspace_id,
                SessionLifecycleRow.session_id == session_id,
            )
            .with_for_update()
        )

    async def get_definition(
        self, workspace_id: UUID, agent_definition_id: UUID
    ) -> AgentDefinition | None:
        row = await self._session.scalar(
            select(AgentDefinitionRow)
            .where(
                AgentDefinitionRow.workspace_id == workspace_id,
                AgentDefinitionRow.id == agent_definition_id,
            )
            .with_for_update()
        )
        return _definition(row) if row is not None else None

    async def membership(
        self, workspace_id: UUID, session_id: UUID, *, round: int
    ) -> MembershipSnapshot:
        if round < 1:
            raise ValueError("membership round must be at least 1")
        initial = (
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
                .order_by(SessionAgentRow.bound_at, SessionAgentRow.agent_def_id)
            )
        ).all()
        ordered = [_definition(agent) for _, agent in initial]
        interventions = (
            await self._session.scalars(
                select(SessionAgentInterventionRow)
                .join(
                    ReasoningEventRow,
                    (ReasoningEventRow.id == SessionAgentInterventionRow.event_id)
                    & (ReasoningEventRow.workspace_id == SessionAgentInterventionRow.workspace_id)
                    & (ReasoningEventRow.session_id == SessionAgentInterventionRow.session_id),
                )
                .where(
                    SessionAgentInterventionRow.workspace_id == workspace_id,
                    SessionAgentInterventionRow.session_id == session_id,
                    SessionAgentInterventionRow.effective_round <= round,
                )
                .order_by(
                    SessionAgentInterventionRow.effective_round,
                    ReasoningEventRow.ledger_seq,
                )
            )
        ).all()
        definitions = {
            item.id: item
            for item in (
                await self._session.scalars(
                    select(AgentDefinitionRow).where(
                        AgentDefinitionRow.workspace_id == workspace_id,
                        AgentDefinitionRow.id.in_(
                            {item.agent_def_id for item in interventions}
                            | {
                                item.replaced_agent_def_id
                                for item in interventions
                                if item.replaced_agent_def_id is not None
                            }
                        ),
                    )
                )
            ).all()
        }
        for intervention in interventions:
            definition = _definition(definitions[intervention.agent_def_id])
            if intervention.kind == MembershipInterventionKind.REPLACE.value:
                replaced_id = intervention.replaced_agent_def_id
                try:
                    index = next(i for i, item in enumerate(ordered) if item.id == replaced_id)
                except StopIteration as exc:
                    raise LedgerIntegrityError(
                        "membership history replaces a definition that is not effective"
                    ) from exc
                ordered[index] = definition
            else:
                ordered.append(definition)
        return MembershipSnapshot(
            workspace_id=workspace_id,
            session_id=session_id,
            round=round,
            definitions=tuple(ordered),
        )

    async def add_intervention(self, intervention: MembershipIntervention) -> None:
        existing = await self._session.get(SessionAgentInterventionRow, intervention.event_id)
        if existing is not None:
            if _intervention(existing) != intervention:
                raise LedgerIntegrityError(
                    "membership intervention event id was reused with different content"
                )
            return
        self._session.add(
            SessionAgentInterventionRow(
                event_id=intervention.event_id,
                workspace_id=intervention.workspace_id,
                session_id=intervention.session_id,
                kind=intervention.kind.value,
                replaced_agent_def_id=intervention.replaced_agent_definition_id,
                agent_def_id=intervention.agent_definition_id,
                effective_round=intervention.effective_round,
                actor_id=intervention.actor_id,
                correlation_id=intervention.correlation_id,
                reason=intervention.reason,
                recorded_at=intervention.recorded_at,
            )
        )
        await self._session.execute(
            text(
                "UPDATE agent_definitions SET referenced_at = COALESCE(referenced_at, :at) "
                "WHERE workspace_id = :workspace_id AND id = :agent_id"
            ),
            {
                "at": intervention.recorded_at,
                "workspace_id": intervention.workspace_id,
                "agent_id": intervention.agent_definition_id,
            },
        )
        await self._session.flush()

    async def get_intervention(self, event_id: UUID) -> MembershipIntervention | None:
        row = await self._session.get(SessionAgentInterventionRow, event_id)
        return _intervention(row) if row is not None else None

    async def session_ceiling(self, workspace_id: UUID, session_id: UUID) -> BudgetCeiling | None:
        row = await self._session.scalar(
            select(SessionRow).where(
                SessionRow.workspace_id == workspace_id, SessionRow.id == session_id
            )
        )
        if row is None:
            return None
        return BudgetCeiling(max_tokens=row.budget_tokens, max_usd=row.budget_usd)

    async def session_usage(self, workspace_id: UUID, session_id: UUID) -> BudgetUsage:
        return await self._usage(workspace_id, session_id)

    async def agent_ceiling(
        self, workspace_id: UUID, agent_definition_id: UUID
    ) -> BudgetCeiling | None:
        budget = await self._session.scalar(
            select(AgentDefinitionRow.budget).where(
                AgentDefinitionRow.workspace_id == workspace_id,
                AgentDefinitionRow.id == agent_definition_id,
            )
        )
        if not budget:
            return None
        if set(budget) != {"max_tokens", "max_cost_usd"}:
            raise ValueError("agent budget must contain max_tokens and max_cost_usd exactly")
        try:
            return BudgetCeiling(
                max_tokens=_max_tokens(budget["max_tokens"]),
                max_usd=Decimal(str(budget["max_cost_usd"])),
            )
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("agent budget ceiling is invalid") from exc

    async def agent_usage(
        self, workspace_id: UUID, session_id: UUID, agent_definition_id: UUID
    ) -> BudgetUsage:
        return await self._usage(workspace_id, session_id, agent_definition_id)

    async def _usage(
        self, workspace_id: UUID, session_id: UUID, agent_definition_id: UUID | None = None
    ) -> BudgetUsage:
        statement = select(
            func.coalesce(func.sum(LLMCallRecordRow.input_tokens), 0),
            func.coalesce(func.sum(LLMCallRecordRow.output_tokens), 0),
            func.coalesce(func.sum(LLMCallRecordRow.cost_usd), Decimal("0")),
        ).where(
            LLMCallRecordRow.workspace_id == workspace_id,
            LLMCallRecordRow.session_id == session_id,
        )
        if agent_definition_id is not None:
            statement = statement.where(LLMCallRecordRow.agent_def_id == agent_definition_id)
        row = (await self._session.execute(statement)).one()
        return BudgetUsage(
            input_tokens=_token_total(row[0]),
            output_tokens=_token_total(row[1]),
            cost_usd=row[2],
        )


def _max_tokens(value: object) -> int:
    if type(value) is not int:
        raise ValueError("max_tokens must be an integer")
    return value


def _token_total(value: object) -> int:
    if type(value) is int:
        return value
    if isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value():
        return int(value)
    raise ValueError("durable token aggregate must be an integer")


def _definition(row: AgentDefinitionRow) -> AgentDefinition:
    return AgentDefinition(
        id=row.id,
        workspace_id=row.workspace_id,
        logical_id=row.logical_id,
        version=row.version,
        name=row.name,
        domain=row.domain,
        role_kind=AgentRoleKind(row.role_kind),
        objectives=tuple(row.objectives),
        constraints=tuple(row.constraints),
        knowledge_ns=tuple(row.knowledge_ns),
        strategy_ref=row.strategy_ref,
        strategy_ver=row.strategy_ver,
        prompt_ref=row.prompt_ref,
        prompt_hash=row.prompt_hash,
        llm_config_id=row.llm_config_id,
        tool_perms=tuple(row.tool_perms),
        budget=dict(row.budget),
        status=AgentStatus(row.status),
        superseded_by=row.superseded_by,
        referenced_at=row.referenced_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _intervention(row: SessionAgentInterventionRow) -> MembershipIntervention:
    return MembershipIntervention(
        event_id=row.event_id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        kind=MembershipInterventionKind(row.kind),
        replaced_agent_definition_id=row.replaced_agent_def_id,
        agent_definition_id=row.agent_def_id,
        effective_round=row.effective_round,
        actor_id=row.actor_id,
        correlation_id=row.correlation_id,
        reason=row.reason,
        recorded_at=row.recorded_at,
    )


_POLICY_PORT: type[CoordinatorPolicyStore] = SqlAlchemyCoordinatorPolicyStore
