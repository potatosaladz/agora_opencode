"""T6-06 bounded sealed multi-agent dispatch tests."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import UUID

import pytest

from app.application.agent_dispatch import (
    AgentTurnDispatcher,
    DispatchDisposition,
    TurnDispatchOutcome,
)
from app.domain.agent_activity import ProposalBundle
from app.ports.agent_runtime import (
    PinnedAgentDefinition,
    ReasoningContext,
    ReasoningPhase,
    TurnExecutionResult,
)
from tests.traceability import req

U = tuple(UUID(f"018f3000-0000-7000-8000-{value:012d}") for value in range(1, 40))


def context(index: int, **changes: object) -> ReasoningContext:
    definition_id = U[10 + index]
    values: dict[str, object] = {
        "workspace_id": U[0],
        "session_id": U[1],
        "agent_definition_id": definition_id,
        "agent_definition_version": 1,
        "agent_definition": PinnedAgentDefinition(
            id=definition_id,
            logical_id=U[20 + index],
            version=1,
            name=f"expert-{index}",
            domain=f"domain-{index}",
            role_kind="domain_expert",
            strategy_name="fixture",
            strategy_version="1",
            prompt_ref=f"prompts/{index}.txt",
            prompt_hash="sha256:" + f"{index + 1:064x}",
        ),
        "strategy_name": "fixture",
        "strategy_version": "1",
        "canonicalizer_version": "canonicalizer@1",
        "turn_id": U[2 + index],
        "correlation_id": U[8],
        "causation_id": U[9],
        "round": 1,
        "phase": ReasoningPhase.ASSESS,
        "problem_statement": "Evaluate policy.",
        "sealed": True,
        "budget_remaining_tokens": 100,
        "budget_remaining_usd": Decimal("1"),
        "timeout_s": 1.0,
    }
    values.update(changes)
    return ReasoningContext.model_validate(values)


def bundle(value: ReasoningContext) -> ProposalBundle:
    return ProposalBundle(
        protocol_version="1.0",
        kind="proposal_bundle",
        turn_id=value.turn_id,
        artifacts=(),
        self_reported_limits=("Fixture only",),
    )


class RacingRuntime:
    def __init__(self, delays: dict[UUID, float]) -> None:
        self.delays = delays
        self.active = 0
        self.peak = 0
        self.started: list[ReasoningContext] = []
        self.completed: list[UUID] = []

    async def run_turn(self, value: ReasoningContext) -> TurnExecutionResult[ProposalBundle]:
        self.started.append(value)
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(self.delays.get(value.turn_id, 0))
            self.completed.append(value.turn_id)
            return TurnExecutionResult(proposal=bundle(value))
        finally:
            self.active -= 1


@req("FR-203")
async def test_shared_pool_is_bounded_and_returns_stable_pinned_order() -> None:
    contexts = tuple(context(index) for index in range(5))
    runtime = RacingRuntime(
        {
            contexts[0].turn_id: 0.04,
            contexts[1].turn_id: 0.01,
            contexts[2].turn_id: 0.03,
        }
    )

    outcomes = await AgentTurnDispatcher(runtime, worker_limit=2).dispatch(contexts)

    assert runtime.peak == 2
    assert runtime.completed[0] == contexts[1].turn_id
    assert runtime.completed != [value.turn_id for value in contexts]
    assert tuple(outcome.context for outcome in outcomes) == contexts
    assert tuple(outcome.proposal for outcome in outcomes) == tuple(map(bundle, contexts))
    assert all(outcome.execution is not None for outcome in outcomes)
    assert all(outcome.disposition is DispatchDisposition.COMPLETED for outcome in outcomes)


@req("FR-208", "FR-209")
async def test_round_one_inputs_remain_sealed_and_expose_no_peer_channel() -> None:
    contexts = tuple(context(index) for index in range(3))
    runtime = RacingRuntime({})

    await AgentTurnDispatcher(runtime, worker_limit=3).dispatch(contexts)

    assert runtime.started == list(contexts)
    assert all(value.sealed and value.visible_artifacts == () for value in runtime.started)
    assert all(not hasattr(value, "peer_agent_channel") for value in runtime.started)

    invalid = contexts[0].model_copy(update={"sealed": False})
    with pytest.raises(ValueError, match="must remain sealed"):
        await AgentTurnDispatcher(runtime, worker_limit=1).dispatch((invalid,))


@req("FR-203", "FR-208", "FR-209")
async def test_timeout_becomes_ordered_abstention_and_cancels_turn() -> None:
    contexts = (context(0), context(1, timeout_s=0.01), context(2))
    runtime = RacingRuntime({contexts[1].turn_id: 1.0})

    outcomes = await AgentTurnDispatcher(runtime, worker_limit=3).dispatch(contexts)

    timed_out = outcomes[1]
    assert timed_out == TurnDispatchOutcome(
        context=contexts[1],
        disposition=DispatchDisposition.ABSTAIN,
        event_type="TURN_TIMEOUT",
        execution=None,
    )
    assert contexts[1].turn_id not in runtime.completed
    assert [outcome.context for outcome in outcomes] == list(contexts)


@req("FR-203", "FR-208", "FR-209")
async def test_dispatch_preserves_complete_provider_accounting_metadata() -> None:
    value = context(0)

    class AttributedRuntime:
        async def run_turn(self, turn: ReasoningContext) -> TurnExecutionResult[ProposalBundle]:
            return TurnExecutionResult(
                proposal=bundle(turn),
                provider="mock",
                model="fixture-model",
                input_tokens=13,
                output_tokens=5,
                cost_usd=Decimal("0.0042"),
                raw_artifact_ref="raw/dispatch.json#sha256:" + "d" * 64,
            )

    (outcome,) = await AgentTurnDispatcher(AttributedRuntime(), worker_limit=1).dispatch((value,))

    assert outcome.execution is not None
    assert outcome.execution.provider == "mock"
    assert outcome.execution.model == "fixture-model"
    assert outcome.execution.input_tokens == 13
    assert outcome.execution.output_tokens == 5
    assert outcome.execution.cost_usd == Decimal("0.0042")
    assert outcome.execution.raw_artifact_ref == "raw/dispatch.json#sha256:" + "d" * 64


@req("FR-203", "FR-208", "FR-209")
@pytest.mark.parametrize("worker_limit", [0, -1])
def test_worker_limit_must_be_positive(worker_limit: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        AgentTurnDispatcher(RacingRuntime({}), worker_limit=worker_limit)


@req("FR-203", "FR-208", "FR-209")
async def test_empty_mixed_or_duplicate_batches_fail_before_runtime() -> None:
    runtime = RacingRuntime({})
    dispatcher = AgentTurnDispatcher(runtime, worker_limit=2)

    with pytest.raises(ValueError, match="at least one"):
        await dispatcher.dispatch(())
    with pytest.raises(ValueError, match="one session round and phase"):
        await dispatcher.dispatch((context(0), context(1, round=2, phase=ReasoningPhase.ARGUE)))
    with pytest.raises(ValueError, match="unique"):
        await dispatcher.dispatch((context(0), context(0)))
    assert runtime.started == []


@req("FR-203", "FR-208", "FR-209")
async def test_runtime_failure_cancels_other_workers_and_propagates() -> None:
    class FailingRuntime(RacingRuntime):
        async def run_turn(self, value: ReasoningContext) -> TurnExecutionResult[ProposalBundle]:
            if value.agent_definition_id == U[10]:
                raise RuntimeError("provider failed")
            return await super().run_turn(value)

    runtime = FailingRuntime({U[3]: 1.0})
    with pytest.raises(RuntimeError, match="provider failed"):
        await AgentTurnDispatcher(runtime, worker_limit=2).dispatch((context(0), context(1)))
    assert runtime.active == 0
