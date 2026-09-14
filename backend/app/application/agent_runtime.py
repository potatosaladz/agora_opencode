"""Fail-closed strategy selection and Phase 4 activity composition for agent turns."""

from __future__ import annotations

from collections.abc import Iterable

from app.domain.agent_activity import (
    AgentActivityRunner,
    AgentTurnInput,
    AgentTurnPhase,
    ProposalBundle,
)
from app.ports.agent_runtime import (
    AgentRuntime,
    ProposalLike,
    ReasoningContext,
    ReasoningStrategy,
    TurnExecutionResult,
)
from app.ports.errors import PermanentPortError

__all__ = ["ActivityReasoningStrategy", "StatelessAgentRuntime", "StrategyRegistry"]


class StrategyRegistry[ProposalT: ProposalLike]:
    """Immutable registry keyed by exact strategy name and version."""

    def __init__(self, strategies: Iterable[ReasoningStrategy[ProposalT]]) -> None:
        registered: dict[tuple[str, str], ReasoningStrategy[ProposalT]] = {}
        for strategy in strategies:
            key = (
                _required(strategy.name, "strategy name"),
                _required(strategy.version, "version"),
            )
            if key in registered:
                raise ValueError(f"duplicate reasoning strategy {key[0]}@{key[1]}")
            registered[key] = strategy
        self._strategies = registered

    def resolve(self, name: str, version: str) -> ReasoningStrategy[ProposalT]:
        strategy = self._strategies.get((name, version))
        if strategy is None:
            raise PermanentPortError(
                f"unknown reasoning strategy {name}@{version}", port="agent_runtime"
            )
        return strategy


class StatelessAgentRuntime[ProposalT: ProposalLike](AgentRuntime[ProposalT]):
    """Select one pinned strategy and return its proposal without mutation authority."""

    def __init__(self, strategies: StrategyRegistry[ProposalT]) -> None:
        self._strategies = strategies

    async def run_turn(self, context: ReasoningContext) -> TurnExecutionResult[ProposalT]:
        proposed = await self._strategies.resolve(
            context.strategy_name, context.strategy_version
        ).propose(context)
        result = (
            proposed
            if isinstance(proposed, TurnExecutionResult)
            else TurnExecutionResult(proposal=proposed)
        )
        if result.proposal.turn_id != context.turn_id:
            raise PermanentPortError(
                "reasoning strategy returned a proposal for another turn", port="agent_runtime"
            )
        return result


class ActivityReasoningStrategy(ReasoningStrategy[ProposalBundle]):
    """Adapt a named Phase 6 strategy to the existing Phase 4 agent activity boundary."""

    def __init__(self, name: str, version: str, runner: AgentActivityRunner) -> None:
        self.name = _required(name, "strategy name")
        self.version = _required(version, "version")
        self._runner = runner

    async def propose(self, context: ReasoningContext) -> TurnExecutionResult[ProposalBundle]:
        result = await self._runner.run(
            AgentTurnInput(
                protocol_version="1.0",
                kind="turn_request",
                workspace_id=context.workspace_id,
                session_id=context.session_id,
                agent_definition_id=context.agent_definition_id,
                agent_definition_version=context.agent_definition_version,
                agent_definition_json=context.agent_definition.model_dump_json(),
                turn_id=context.turn_id,
                correlation_id=context.correlation_id,
                causation_id=context.causation_id,
                round=context.round,
                phase=AgentTurnPhase(context.phase.value),
                problem_statement=context.problem_statement,
                canonicalizer_version=context.canonicalizer_version,
                objective_summaries=context.objective_summaries,
                constraint_summaries=context.constraint_summaries,
                visible_artifact_ids=context.visible_artifact_ids,
                visible_artifact_json=tuple(
                    artifact.artifact_json for artifact in context.visible_artifacts
                ),
                authorized_knowledge_json=context.retrieval.model_dump_json()
                if context.retrieval is not None
                else None,
                sealed=context.sealed,
                budget_remaining_tokens=context.budget_remaining_tokens,
                timeout_s=context.timeout_s,
            )
        )
        return TurnExecutionResult(
            proposal=result.bundle,
            provider=result.provider,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
            raw_artifact_ref=result.raw_artifact_ref,
        )


def _required(value: str, label: str) -> str:
    if not value.strip():
        raise ValueError(f"{label} must not be blank")
    return value
