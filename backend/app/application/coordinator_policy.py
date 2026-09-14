"""Coordinator policy for membership interventions and durable budget enforcement."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.application.agent_dispatch import AgentTurnDispatcher, TurnDispatchOutcome
from app.domain.agent_registry import AgentStatus
from app.domain.coordinator_policy import (
    BudgetCeiling,
    BudgetUsage,
    CoordinatorPolicyStore,
    MembershipIntervention,
    MembershipInterventionKind,
    MembershipSnapshot,
)
from app.domain.reasoning import ActorClass
from app.domain.reasoning_ledger import LedgerAppend, ReasoningLedger
from app.domain.session_lifecycle import (
    TERMINAL_SESSION_STATES,
    InvalidSessionTransition,
    SessionLifecycle,
    SessionLifecycleState,
    SessionLifecycleStore,
    SessionTransition,
)
from app.ports.agent_runtime import ProposalLike, ReasoningContext

__all__ = [
    "BudgetCoordinator",
    "BudgetExhausted",
    "BudgetedAgentTurnDispatcher",
    "MembershipInterventionRequest",
    "SessionMembershipCoordinator",
]


class BudgetExhausted(RuntimeError):
    """A durable session or agent ceiling has been reached."""

    def __init__(self, lifecycle: SessionLifecycle) -> None:
        super().__init__("BUDGET_EXHAUSTED")
        self.lifecycle = lifecycle


class MembershipInterventionRequest(MembershipIntervention):
    """Strict authorized request; effective round is verified against lifecycle state."""


class SessionMembershipCoordinator:
    def __init__(
        self,
        policy: CoordinatorPolicyStore,
        lifecycle: SessionLifecycleStore,
        ledger: ReasoningLedger,
    ) -> None:
        self._policy = policy
        self._lifecycle = lifecycle
        self._ledger = ledger

    async def apply(self, request: MembershipInterventionRequest) -> MembershipSnapshot:
        await self._policy.lock_membership(request.workspace_id, request.session_id)
        prior = await self._policy.get_intervention(request.event_id)
        if prior is not None:
            expected = MembershipIntervention.model_validate(request.model_dump())
            persisted = MembershipIntervention.model_validate(prior.model_dump())
            if persisted != expected:
                raise ValueError(
                    "membership intervention event id was reused with different content"
                )
            return await self._policy.membership(
                request.workspace_id, request.session_id, round=request.effective_round
            )
        lifecycle = await self._lifecycle.get(request.workspace_id, request.session_id)
        if lifecycle is None or lifecycle.state in TERMINAL_SESSION_STATES:
            raise InvalidSessionTransition("session is missing or terminal")
        expected_round = 1 if lifecycle.round == 0 else lifecycle.round + 1
        if request.effective_round != expected_round:
            raise InvalidSessionTransition(
                f"membership intervention must become effective in round {expected_round}"
            )
        if request.kind is MembershipInterventionKind.REPLACE and lifecycle.round != 0:
            raise InvalidSessionTransition("agent replacement is allowed only before round 1")
        if request.kind is MembershipInterventionKind.INJECT and lifecycle.round == 0:
            raise InvalidSessionTransition("agent injection requires a started session")

        definition = await self._policy.get_definition(
            request.workspace_id, request.agent_definition_id
        )
        if (
            definition is None
            or definition.workspace_id != request.workspace_id
            or definition.status is not AgentStatus.ACTIVE
        ):
            raise ValueError("new agent definition must be active in the session workspace")
        current = await self._policy.membership(
            request.workspace_id, request.session_id, round=request.effective_round
        )
        by_id = {item.id: item for item in current.definitions}
        if request.kind is MembershipInterventionKind.REPLACE:
            replaced_id = request.replaced_agent_definition_id
            assert replaced_id is not None
            replaced = by_id.get(replaced_id)
            if replaced is None:
                raise ValueError("replaced agent definition is not effective for the target round")
            final_logical_ids = {
                item.logical_id for item in current.definitions if item.id != replaced.id
            }
            if definition.logical_id in final_logical_ids:
                raise ValueError("replacement would add multiple versions of one logical agent")
        elif definition.logical_id in {item.logical_id for item in current.definitions}:
            raise ValueError("injection would add multiple versions of one logical agent")

        event_type = (
            "SESSION_AGENT_REPLACED"
            if request.kind is MembershipInterventionKind.REPLACE
            else "SESSION_AGENT_INJECTED"
        )
        await self._ledger.append(
            LedgerAppend(
                id=request.event_id,
                workspace_id=request.workspace_id,
                session_id=request.session_id,
                event_type=event_type,
                payload_schema_version=1,
                correlation_id=request.correlation_id,
                actor_class=ActorClass.HUMAN,
                actor_id=request.actor_id,
                round=lifecycle.round,
                payload={
                    "kind": request.kind.value,
                    "replaced_agent_definition_id": str(request.replaced_agent_definition_id)
                    if request.replaced_agent_definition_id is not None
                    else None,
                    "agent_definition_id": str(request.agent_definition_id),
                    "agent_definition_version": definition.version,
                    "logical_agent_id": str(definition.logical_id),
                    "effective_round": request.effective_round,
                    "reason": request.reason,
                },
                recorded_at=request.recorded_at,
            )
        )
        await self._policy.add_intervention(request)
        return await self._policy.membership(
            request.workspace_id, request.session_id, round=request.effective_round
        )


class BudgetCoordinator:
    def __init__(self, policy: CoordinatorPolicyStore, lifecycle: SessionLifecycleStore) -> None:
        self._policy = policy
        self._lifecycle = lifecycle

    async def enforce(
        self,
        *,
        workspace_id: UUID,
        session_id: UUID,
        agent_definition_ids: tuple[UUID, ...],
        event_id: UUID,
        correlation_id: UUID,
        actor_id: UUID,
        checked_at: datetime,
    ) -> None:
        lifecycle = await self._lifecycle.get(workspace_id, session_id)
        if lifecycle is None:
            raise InvalidSessionTransition("session lifecycle does not exist")
        if lifecycle.state in TERMINAL_SESSION_STATES:
            if (
                lifecycle.last_event_id == event_id
                and lifecycle.state is SessionLifecycleState.FAILED
            ):
                raise BudgetExhausted(lifecycle)
            raise InvalidSessionTransition("session is already terminal")

        session_usage = await self._policy.session_usage(workspace_id, session_id)
        session_ceiling = await self._policy.session_ceiling(workspace_id, session_id)
        breach = _breach("SESSION", None, session_usage, session_ceiling)
        if breach is None:
            for agent_id in dict.fromkeys(agent_definition_ids):
                usage = await self._policy.agent_usage(workspace_id, session_id, agent_id)
                ceiling = await self._policy.agent_ceiling(workspace_id, agent_id)
                breach = _breach("AGENT", agent_id, usage, ceiling)
                if breach is not None:
                    break
        if breach is None:
            return

        scope, breached_agent_id, usage, ceiling = breach
        terminated = await self._lifecycle.transition(
            SessionTransition(
                source=lifecycle.state,
                target=SessionLifecycleState.FAILED,
                round=lifecycle.round,
                event=LedgerAppend(
                    id=event_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    event_type="BUDGET_EXHAUSTED",
                    payload_schema_version=1,
                    correlation_id=correlation_id,
                    actor_class=ActorClass.SERVICE,
                    actor_id=actor_id,
                    round=lifecycle.round,
                    payload={
                        "from": lifecycle.state.value,
                        "to": SessionLifecycleState.FAILED.value,
                        "termination_reason": "BUDGET_EXHAUSTED",
                        "scope": scope,
                        "agent_definition_id": str(breached_agent_id)
                        if breached_agent_id is not None
                        else None,
                        "usage_tokens": usage.tokens,
                        "usage_usd": str(usage.cost_usd),
                        "max_tokens": ceiling.max_tokens,
                        "max_usd": str(ceiling.max_usd),
                    },
                    recorded_at=checked_at,
                ),
            )
        )
        raise BudgetExhausted(terminated)


class BudgetedAgentTurnDispatcher[ProposalT: ProposalLike]:
    """Check durable totals on both sides of existing bounded dispatch."""

    def __init__(
        self, dispatcher: AgentTurnDispatcher[ProposalT], budgets: BudgetCoordinator
    ) -> None:
        self._dispatcher = dispatcher
        self._budgets = budgets

    async def dispatch(
        self,
        contexts: tuple[ReasoningContext, ...],
        *,
        budget_event_id: UUID,
        actor_id: UUID,
        checked_at: datetime,
    ) -> tuple[TurnDispatchOutcome[ProposalT], ...]:
        if not contexts:
            raise ValueError("dispatch requires at least one logical turn")
        first = contexts[0]
        agent_ids = tuple(item.agent_definition_id for item in contexts)
        await self._budgets.enforce(
            workspace_id=first.workspace_id,
            session_id=first.session_id,
            agent_definition_ids=agent_ids,
            event_id=budget_event_id,
            correlation_id=first.correlation_id,
            actor_id=actor_id,
            checked_at=checked_at,
        )
        outcomes = await self._dispatcher.dispatch(contexts)
        await self._budgets.enforce(
            workspace_id=first.workspace_id,
            session_id=first.session_id,
            agent_definition_ids=agent_ids,
            event_id=budget_event_id,
            correlation_id=first.correlation_id,
            actor_id=actor_id,
            checked_at=checked_at,
        )
        return outcomes


def _breach(
    scope: str,
    agent_id: UUID | None,
    usage: BudgetUsage,
    ceiling: BudgetCeiling | None,
) -> tuple[str, UUID | None, BudgetUsage, BudgetCeiling] | None:
    if ceiling is None:
        return None
    if usage.tokens >= ceiling.max_tokens or usage.cost_usd >= ceiling.max_usd:
        return scope, agent_id, usage, ceiling
    return None
