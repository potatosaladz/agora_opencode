"""Offline behavioral contract for the T6-01 logical-agent runtime reference adapter."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from app.adapters.inmemory.reasoning_strategy import DeterministicReasoningStrategy
from app.application.agent_runtime import StatelessAgentRuntime, StrategyRegistry
from app.domain.agent_activity import ProposalBundle
from app.ports.agent_runtime import (
    PinnedAgentDefinition,
    ReasoningContext,
    ReasoningPhase,
    TurnExecutionResult,
)
from tests.traceability import req

pytestmark = pytest.mark.contract

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 7))


@req("FR-208", "FR-210")
async def test_deterministic_strategy_and_runtime_preserve_typed_turn_identity() -> None:
    context = ReasoningContext(
        workspace_id=U[0],
        session_id=U[1],
        agent_definition_id=U[2],
        agent_definition_version=1,
        agent_definition=PinnedAgentDefinition(
            id=U[2],
            logical_id=U[2],
            version=1,
            name="fixture",
            domain="contract",
            role_kind="domain_expert",
            strategy_name="fixture",
            strategy_version="1",
            prompt_ref="prompts/fixture/v1.txt",
            prompt_hash="sha256:" + "a" * 64,
        ),
        strategy_name="fixture",
        strategy_version="1",
        canonicalizer_version="canonicalizer@1",
        turn_id=U[3],
        correlation_id=U[4],
        causation_id=U[5],
        round=1,
        phase=ReasoningPhase.ASSESS,
        problem_statement="Contract fixture",
        sealed=True,
        budget_remaining_tokens=100,
        budget_remaining_usd=Decimal("0.10"),
        timeout_s=5.0,
    )
    expected = ProposalBundle(
        protocol_version="1.0",
        kind="proposal_bundle",
        turn_id=context.turn_id,
        artifacts=(),
        self_reported_limits=("Fixture has no external knowledge",),
    )
    strategy = DeterministicReasoningStrategy("fixture", "1", lambda _context: expected)
    runtime = StatelessAgentRuntime(StrategyRegistry((strategy,)))

    assert await runtime.run_turn(context) == TurnExecutionResult(proposal=expected)
    assert strategy.contexts == [context]
