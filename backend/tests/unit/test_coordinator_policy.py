"""T6-08 membership, durable budget, and 20-agent coordinator policy tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.agent_dispatch import AgentTurnDispatcher
from app.application.coordinator_policy import (
    BudgetCoordinator,
    BudgetedAgentTurnDispatcher,
    BudgetExhausted,
    MembershipInterventionRequest,
    SessionMembershipCoordinator,
)
from app.application.proposal_commit import AgentProposalCommitter, AgentTurnCommit
from app.db.coordinator_policy import SqlAlchemyCoordinatorPolicyStore
from app.domain.agent_activity import AgentTurnResult, ArtifactProposal, ProposalBundle
from app.domain.agent_registry import AgentDefinition, AgentRoleKind, AgentStatus
from app.domain.coordinator_policy import (
    BudgetCeiling,
    BudgetUsage,
    MembershipIntervention,
    MembershipInterventionKind,
    MembershipSnapshot,
)
from app.domain.reasoning import ArtifactKind, LifecycleStatus, ReasoningArtifact
from app.domain.reasoning_graph import GraphEdge, GraphNode
from app.domain.reasoning_ledger import (
    LedgerAppend,
    LedgerEvent,
    LedgerVerification,
    ledger_event_hash,
    ledger_payload_hash,
)
from app.domain.session_lifecycle import (
    InvalidSessionTransition,
    SessionLifecycle,
    SessionLifecycleState,
    SessionTransition,
)
from app.ports.agent_runtime import (
    PinnedAgentDefinition,
    ReasoningContext,
    ReasoningPhase,
    TurnExecutionResult,
)
from tests.traceability import req

U = tuple(UUID(f"018f8000-0000-7000-8000-{value:012d}") for value in range(1, 100))
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)


class BudgetSession:
    def __init__(self, max_tokens: object) -> None:
        self.max_tokens = max_tokens

    async def scalar(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        return {"max_tokens": self.max_tokens, "max_cost_usd": "1"}


class UsageResult:
    def __init__(self, input_tokens: object, output_tokens: object) -> None:
        self.values = (input_tokens, output_tokens, Decimal("0.3"))

    def one(self) -> tuple[object, object, object]:
        return self.values


class UsageSession:
    def __init__(self, input_tokens: object, output_tokens: object) -> None:
        self.result = UsageResult(input_tokens, output_tokens)

    async def execute(self, *_args: object, **_kwargs: object) -> UsageResult:
        return self.result


def definition(index: int, *, version: int = 1, logical_id: UUID | None = None) -> AgentDefinition:
    return AgentDefinition(
        id=U[10 + index],
        workspace_id=U[0],
        logical_id=logical_id or U[40 + index],
        version=version,
        name=f"expert-{index}-v{version}",
        domain=f"domain-{index}",
        role_kind=AgentRoleKind.DOMAIN_EXPERT,
        strategy_ref="fixture",
        strategy_ver="1",
        prompt_ref=f"prompts/{index}/v{version}.txt",
        prompt_hash="sha256:" + f"{index + version:064x}",
        budget={"max_tokens": 100, "max_cost_usd": "1"},
        status=AgentStatus.ACTIVE,
    )


@req("FR-108", "FR-211", "NFR-009")
@pytest.mark.parametrize("max_tokens", [True, 1.5, "100"])
async def test_persisted_agent_budget_requires_exact_integer_tokens(max_tokens: object) -> None:
    store = SqlAlchemyCoordinatorPolicyStore(cast(AsyncSession, BudgetSession(max_tokens)))

    with pytest.raises(ValueError, match="agent budget ceiling is invalid"):
        await store.agent_ceiling(U[0], U[10])


@req("FR-108", "FR-211", "NFR-009")
async def test_postgres_numeric_token_aggregates_cross_the_strict_domain_boundary() -> None:
    session = UsageSession(Decimal("30"), Decimal("12"))
    store = SqlAlchemyCoordinatorPolicyStore(cast(AsyncSession, session))

    usage = await store.session_usage(U[0], U[1])

    assert usage == BudgetUsage(input_tokens=30, output_tokens=12, cost_usd=Decimal("0.3"))


@req("FR-108", "FR-211", "NFR-009")
@pytest.mark.parametrize("invalid", [True, Decimal("1.5"), Decimal("NaN"), "1"])
async def test_durable_token_aggregate_rejects_non_integer_adapter_values(invalid: object) -> None:
    session = UsageSession(invalid, 0)
    store = SqlAlchemyCoordinatorPolicyStore(cast(AsyncSession, session))

    with pytest.raises(ValueError, match="durable token aggregate must be an integer"):
        await store.session_usage(U[0], U[1])


def lifecycle(state: SessionLifecycleState, *, round: int) -> SessionLifecycle:
    terminal = state is SessionLifecycleState.FAILED
    return SessionLifecycle(
        workspace_id=U[0],
        session_id=U[1],
        state=state,
        round=round,
        workflow_id="workflow" if round else None,
        run_id="run" if round else None,
        last_event_id=U[2] if state is not SessionLifecycleState.DRAFT else None,
        initialized_at=NOW if state is not SessionLifecycleState.DRAFT else None,
        started_at=NOW if round else None,
        ended_at=NOW if terminal else None,
        created_at=NOW,
        updated_at=NOW,
    )


class Ledger:
    def __init__(self) -> None:
        self.events: list[LedgerEvent] = []

    async def append(self, event: LedgerAppend) -> LedgerEvent:
        existing = next((item for item in self.events if item.id == event.id), None)
        if existing is not None:
            return existing
        persisted = LedgerEvent(
            **event.model_dump(),
            ledger_seq=len(self.events) + 1,
            payload_hash=ledger_payload_hash(event.payload),
            prev_hash=self.events[-1].event_hash if self.events else "sha256:" + "0" * 64,
            event_hash="sha256:" + "0" * 64,
        )
        persisted = persisted.model_copy(update={"event_hash": ledger_event_hash(persisted)})
        self.events.append(persisted)
        return persisted

    async def get_by_id(
        self, workspace_id: UUID, session_id: UUID, event_id: UUID
    ) -> LedgerEvent | None:
        return next((item for item in self.events if item.id == event_id), None)

    async def read(self, *_args: object, **_kwargs: object) -> tuple[LedgerEvent, ...]:
        return tuple(self.events)

    async def verify(self, *_args: object, **_kwargs: object) -> LedgerVerification:
        head = self.events[-1].event_hash if self.events else "sha256:" + "0" * 64
        return LedgerVerification(valid=True, event_count=len(self.events), head_hash=head)


class LifecycleStore:
    def __init__(self, value: SessionLifecycle, ledger: Ledger) -> None:
        self.value = value
        self.ledger = ledger

    async def get(self, workspace_id: UUID, session_id: UUID) -> SessionLifecycle | None:
        return self.value if (workspace_id, session_id) == (U[0], U[1]) else None

    async def transition(self, command: SessionTransition) -> SessionLifecycle:
        if self.value.state is command.target and self.value.last_event_id == command.event.id:
            await self.ledger.append(command.event)
            return self.value
        await self.ledger.append(command.event)
        self.value = self.value.model_copy(
            update={
                "state": command.target,
                "last_event_id": command.event.id,
                "ended_at": command.event.recorded_at,
                "updated_at": command.event.recorded_at,
            }
        )
        return self.value

    async def add_draft(self, *_args: object, **_kwargs: object) -> SessionLifecycle:
        raise NotImplementedError

    async def attach_workflow(self, *_args: object, **_kwargs: object) -> SessionLifecycle:
        raise NotImplementedError


class PolicyStore:
    def __init__(self, definitions: tuple[AgentDefinition, ...]) -> None:
        self.definitions = {item.id: item for item in definitions}
        self.initial = list(definitions[:1])
        self.interventions: list[MembershipIntervention] = []
        self.session_limit = BudgetCeiling(max_tokens=1000, max_usd=Decimal("10"))
        self.session_total = BudgetUsage(input_tokens=0, output_tokens=0, cost_usd=Decimal("0"))
        self.agent_totals: dict[UUID, BudgetUsage] = {}
        self.locked = 0

    async def lock_membership(self, workspace_id: UUID, session_id: UUID) -> None:
        assert (workspace_id, session_id) == (U[0], U[1])
        self.locked += 1

    async def get_definition(
        self, workspace_id: UUID, agent_definition_id: UUID
    ) -> AgentDefinition | None:
        value = self.definitions.get(agent_definition_id)
        return value if value is not None and value.workspace_id == workspace_id else None

    async def membership(
        self, workspace_id: UUID, session_id: UUID, *, round: int
    ) -> MembershipSnapshot:
        current = list(self.initial)
        for item in self.interventions:
            if item.effective_round > round:
                continue
            agent = self.definitions[item.agent_definition_id]
            if item.kind is MembershipInterventionKind.REPLACE:
                replaced = item.replaced_agent_definition_id
                index = next(index for index, value in enumerate(current) if value.id == replaced)
                current[index] = agent
            else:
                current.append(agent)
        return MembershipSnapshot(
            workspace_id=workspace_id,
            session_id=session_id,
            round=round,
            definitions=tuple(current),
        )

    async def add_intervention(self, intervention: MembershipIntervention) -> None:
        existing = next(
            (item for item in self.interventions if item.event_id == intervention.event_id), None
        )
        if existing is None:
            self.interventions.append(intervention)
        elif existing != intervention:
            raise ValueError("conflicting intervention")

    async def get_intervention(self, event_id: UUID) -> MembershipIntervention | None:
        return next((item for item in self.interventions if item.event_id == event_id), None)

    async def session_ceiling(self, workspace_id: UUID, session_id: UUID) -> BudgetCeiling | None:
        return self.session_limit

    async def session_usage(self, workspace_id: UUID, session_id: UUID) -> BudgetUsage:
        return self.session_total

    async def agent_ceiling(
        self, workspace_id: UUID, agent_definition_id: UUID
    ) -> BudgetCeiling | None:
        return BudgetCeiling(max_tokens=100, max_usd=Decimal("1"))

    async def agent_usage(
        self, workspace_id: UUID, session_id: UUID, agent_definition_id: UUID
    ) -> BudgetUsage:
        return self.agent_totals.get(
            agent_definition_id,
            BudgetUsage(input_tokens=0, output_tokens=0, cost_usd=Decimal("0")),
        )


def intervention(
    kind: MembershipInterventionKind,
    agent_id: UUID,
    *,
    effective_round: int,
    replaced_id: UUID | None = None,
) -> MembershipInterventionRequest:
    return MembershipInterventionRequest(
        event_id=U[5],
        workspace_id=U[0],
        session_id=U[1],
        kind=kind,
        replaced_agent_definition_id=replaced_id,
        agent_definition_id=agent_id,
        effective_round=effective_round,
        actor_id=U[3],
        correlation_id=U[4],
        reason="Authorized membership change",
        recorded_at=NOW,
    )


@req("FR-108")
async def test_pre_round_replacement_is_ledgered_and_effective_in_round_one() -> None:
    first = definition(0)
    replacement = definition(1, version=2, logical_id=first.logical_id)
    policy, ledger = PolicyStore((first, replacement)), Ledger()
    service = SessionMembershipCoordinator(
        policy, LifecycleStore(lifecycle(SessionLifecycleState.DRAFT, round=0), ledger), ledger
    )
    request = intervention(
        MembershipInterventionKind.REPLACE,
        replacement.id,
        effective_round=1,
        replaced_id=first.id,
    )

    result = await service.apply(request)
    replay = await service.apply(request)

    assert result == replay
    assert result.definitions == (replacement,)
    assert len(policy.interventions) == len(ledger.events) == 1
    assert ledger.events[0].event_type == "SESSION_AGENT_REPLACED"
    assert ledger.events[0].payload["effective_round"] == 1


@req("FR-108")
async def test_mid_session_injection_only_appears_in_next_round() -> None:
    first, injected = definition(0), definition(1)
    policy, ledger = PolicyStore((first, injected)), Ledger()
    service = SessionMembershipCoordinator(
        policy, LifecycleStore(lifecycle(SessionLifecycleState.RUNNING, round=2), ledger), ledger
    )

    result = await service.apply(
        intervention(MembershipInterventionKind.INJECT, injected.id, effective_round=3)
    )

    assert (await policy.membership(U[0], U[1], round=2)).definitions == (first,)
    assert result.definitions == (first, injected)
    assert ledger.events[0].event_type == "SESSION_AGENT_INJECTED"


@req("FR-108", "FR-211", "NFR-009")
async def test_membership_rejects_bad_timing_inactive_and_duplicate_logical_agent() -> None:
    first = definition(0)
    duplicate = definition(1, logical_id=first.logical_id)
    inactive = definition(2)
    inactive = replace(inactive, status=AgentStatus.WITHDRAWN)
    policy, ledger = PolicyStore((first, duplicate, inactive)), Ledger()
    service = SessionMembershipCoordinator(
        policy, LifecycleStore(lifecycle(SessionLifecycleState.RUNNING, round=2), ledger), ledger
    )

    with pytest.raises(InvalidSessionTransition, match="round 3"):
        await service.apply(
            intervention(MembershipInterventionKind.INJECT, duplicate.id, effective_round=2)
        )
    with pytest.raises(ValueError, match="active"):
        await service.apply(
            intervention(MembershipInterventionKind.INJECT, inactive.id, effective_round=3)
        )
    with pytest.raises(ValueError, match="multiple versions"):
        await service.apply(
            intervention(MembershipInterventionKind.INJECT, duplicate.id, effective_round=3)
        )
    assert policy.interventions == []
    assert ledger.events == []


@req("NFR-009")
async def test_session_and_agent_durable_ceiling_terminate_once_with_explicit_reason() -> None:
    agent = definition(0)
    for scope in ("SESSION", "AGENT"):
        policy, ledger = PolicyStore((agent,)), Ledger()
        if scope == "SESSION":
            policy.session_total = BudgetUsage(
                input_tokens=900, output_tokens=100, cost_usd=Decimal("2")
            )
        else:
            policy.agent_totals[agent.id] = BudgetUsage(
                input_tokens=80, output_tokens=20, cost_usd=Decimal("0.5")
            )
        lifecycles = LifecycleStore(lifecycle(SessionLifecycleState.RUNNING, round=2), ledger)
        budgets = BudgetCoordinator(policy, lifecycles)

        with pytest.raises(BudgetExhausted) as exhausted:
            await budgets.enforce(
                workspace_id=U[0],
                session_id=U[1],
                agent_definition_ids=(agent.id,),
                event_id=U[6],
                correlation_id=U[4],
                actor_id=U[7],
                checked_at=NOW,
            )

        assert exhausted.value.lifecycle.state is SessionLifecycleState.FAILED
        assert len(ledger.events) == 1
        assert ledger.events[0].event_type == "BUDGET_EXHAUSTED"
        assert ledger.events[0].payload["termination_reason"] == "BUDGET_EXHAUSTED"
        assert ledger.events[0].payload["scope"] == scope


@req("NFR-009")
async def test_post_dispatch_durable_accounting_breach_terminates_before_return() -> None:
    turn = context(0)
    agent = definition(0)
    policy, ledger = PolicyStore((agent,)), Ledger()
    lifecycles = LifecycleStore(lifecycle(SessionLifecycleState.RUNNING, round=1), ledger)

    class AccountingRuntime:
        async def run_turn(self, value: ReasoningContext) -> TurnExecutionResult[ProposalBundle]:
            policy.session_total = BudgetUsage(
                input_tokens=900, output_tokens=100, cost_usd=Decimal("2")
            )
            return TurnExecutionResult(
                proposal=ProposalBundle(
                    protocol_version="1.0",
                    kind="proposal_bundle",
                    turn_id=value.turn_id,
                    artifacts=(),
                    self_reported_limits=("Fixture only",),
                )
            )

    dispatcher = BudgetedAgentTurnDispatcher(
        AgentTurnDispatcher(AccountingRuntime(), worker_limit=1),
        BudgetCoordinator(policy, lifecycles),
    )

    with pytest.raises(BudgetExhausted):
        await dispatcher.dispatch((turn,), budget_event_id=U[9], actor_id=U[7], checked_at=NOW)

    assert [event.event_type for event in ledger.events] == ["BUDGET_EXHAUSTED"]


def context(index: int) -> ReasoningContext:
    agent_id, logical_id = U[10 + index], U[40 + index]
    pinned = PinnedAgentDefinition(
        id=agent_id,
        logical_id=logical_id,
        version=1,
        name=f"expert-{index}",
        domain=f"domain-{index}",
        role_kind="domain_expert",
        strategy_name="fixture",
        strategy_version="1",
        prompt_ref=f"prompts/{index}.txt",
        prompt_hash="sha256:" + f"{index + 1:064x}",
    )
    return ReasoningContext(
        workspace_id=U[0],
        session_id=U[1],
        agent_definition_id=agent_id,
        agent_definition_version=1,
        agent_definition=pinned,
        strategy_name="fixture",
        strategy_version="1",
        canonicalizer_version="canonicalizer@1",
        turn_id=U[60 + index],
        correlation_id=U[4],
        causation_id=U[8],
        round=1,
        phase=ReasoningPhase.ASSESS,
        problem_statement="Evaluate policy.",
        sealed=True,
        budget_remaining_tokens=100,
        budget_remaining_usd=Decimal("1"),
        timeout_s=1,
    )


class TwentyAgentRuntime:
    def __init__(self) -> None:
        self.active = 0
        self.peak = 0

    async def run_turn(self, value: ReasoningContext) -> TurnExecutionResult[ProposalBundle]:
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep((20 - int(value.agent_definition.name.split("-")[1])) / 10000)
            return TurnExecutionResult(
                proposal=ProposalBundle(
                    protocol_version="1.0",
                    kind="proposal_bundle",
                    turn_id=value.turn_id,
                    artifacts=(
                        ArtifactProposal(
                            op="propose",
                            kind=ArtifactKind.CLAIM,
                            payload={
                                "statement": f"Assessment from {value.agent_definition.name}",
                                "claim_type": "EVALUATIVE",
                                "direction": "SUPPORTS",
                                "strength": "MODERATE",
                                "supporting_evidence_ids": [],
                                "opposing_evidence_ids": [],
                                "review_status": "PROPOSED",
                            },
                        ),
                    ),
                    self_reported_limits=("Fixture only",),
                )
            )
        finally:
            self.active -= 1


class MemoryArtifacts:
    def __init__(self) -> None:
        self.values: dict[UUID, ReasoningArtifact] = {}

    async def lock_agent_turn(self, *_args: object) -> None:
        return None

    async def get_for_update(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> ReasoningArtifact | None:
        value = self.values.get(artifact_id)
        if value is None or (value.workspace_id, value.session_id) != (workspace_id, session_id):
            return None
        return value

    async def add(self, artifact: ReasoningArtifact) -> None:
        self.values[artifact.id] = artifact

    async def set_lifecycle(
        self,
        workspace_id: UUID,
        session_id: UUID,
        artifact_id: UUID,
        status: LifecycleStatus,
        *,
        updated_at: datetime,
    ) -> None:
        raise AssertionError("proposal commit never changes lifecycle")


class MemoryGraph:
    def __init__(self) -> None:
        self.nodes: dict[UUID, GraphNode] = {}

    async def node_for_artifact(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> GraphNode | None:
        value = self.nodes.get(artifact_id)
        if value is None or (value.workspace_id, value.session_id) != (workspace_id, session_id):
            return None
        return value

    async def add_node(self, node: GraphNode) -> None:
        self.nodes[node.ref_id] = node

    async def add_edge(self, edge: GraphEdge) -> None:
        raise AssertionError(f"fixture claims have no graph edges: {edge.id}")


@req("FR-210", "FR-211")
async def test_twenty_agents_stay_bounded_and_commit_full_attribution_in_pinned_order() -> None:
    contexts = tuple(context(index) for index in range(20))
    runtime = TwentyAgentRuntime()
    policy, budget_ledger = PolicyStore(tuple(definition(index) for index in range(20))), Ledger()
    lifecycles = LifecycleStore(lifecycle(SessionLifecycleState.RUNNING, round=1), budget_ledger)
    dispatcher = BudgetedAgentTurnDispatcher(
        AgentTurnDispatcher(runtime, worker_limit=4), BudgetCoordinator(policy, lifecycles)
    )

    outcomes = await dispatcher.dispatch(
        contexts, budget_event_id=U[9], actor_id=U[7], checked_at=NOW
    )
    ledger = Ledger()
    artifacts = MemoryArtifacts()
    committer = AgentProposalCommitter(artifacts, MemoryGraph(), ledger)
    for outcome in outcomes:
        assert outcome.proposal is not None
        await committer.commit(
            AgentTurnCommit(
                context=outcome.context,
                result=AgentTurnResult(
                    turn_id=outcome.context.turn_id,
                    agent_definition_id=outcome.context.agent_definition_id,
                    bundle=outcome.proposal,
                    provider="mock",
                    model="fixture-model",
                    input_tokens=3,
                    output_tokens=2,
                    cost_usd=Decimal("0.001"),
                    raw_artifact_ref=f"raw/{outcome.context.turn_id}.json#sha256:" + "a" * 64,
                ),
                committed_at=NOW,
            )
        )

    assert runtime.peak == 4
    assert tuple(outcome.context for outcome in outcomes) == contexts
    completion_events = tuple(
        event for event in ledger.events if event.event_type == "AGENT_TURN_COMPLETED"
    )
    attributions = tuple(event.payload["attribution"] for event in completion_events)
    assert tuple(value["agent_definition_id"] for value in attributions) == tuple(
        str(value.agent_definition_id) for value in contexts
    )
    required = {
        "agent_definition_id",
        "agent_definition_version",
        "strategy_name",
        "strategy_version",
        "provider",
        "model",
        "prompt_ref",
        "prompt_hash",
        "round",
        "phase",
        "turn_id",
        "correlation_id",
        "causation_id",
        "raw_artifact_ref",
        "context_hash",
        "bundle_hash",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "committed_at",
    }
    assert all(set(value) == required for value in attributions)
    assert len(artifacts.values) == 20
    assert all(
        artifact.metadata["attribution"] in attributions for artifact in artifacts.values.values()
    )
    assert budget_ledger.events == []
