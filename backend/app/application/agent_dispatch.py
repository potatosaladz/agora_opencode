"""Bounded, sealed, deterministic dispatch of independent logical-agent turns."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.ports.agent_runtime import (
    AgentRuntime,
    ProposalLike,
    ReasoningContext,
    ReasoningPhase,
    TurnExecutionResult,
)

__all__ = [
    "AgentTurnDispatcher",
    "DispatchDisposition",
    "TurnDispatchOutcome",
]


# trace: FR-203, FR-208, FR-209
class DispatchDisposition(StrEnum):
    COMPLETED = "COMPLETED"
    ABSTAIN = "ABSTAIN"


class TurnDispatchOutcome[ProposalT](BaseModel):
    """Proposal and attribution outcome; coordinator persists it in this returned order."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    context: ReasoningContext
    disposition: DispatchDisposition
    event_type: str
    execution: TurnExecutionResult[ProposalT] | None

    @property
    def proposal(self) -> ProposalT | None:
        """Compatibility view for proposal-only coordinator validation."""
        return self.execution.proposal if self.execution is not None else None

    @model_validator(mode="after")
    def valid_outcome(self) -> TurnDispatchOutcome[ProposalT]:
        if self.disposition is DispatchDisposition.COMPLETED:
            if self.event_type != "AGENT_TURN_COMPLETED" or self.execution is None:
                raise ValueError("completed dispatch requires its proposal and completion event")
            proposal = cast(ProposalLike, self.execution.proposal)
            if proposal.turn_id != self.context.turn_id:
                raise ValueError("dispatch proposal does not match its logical turn")
        elif self.event_type != "TURN_TIMEOUT" or self.execution is not None:
            raise ValueError("abstaining dispatch requires a timeout event and no proposal")
        return self


class AgentTurnDispatcher[ProposalT: ProposalLike]:
    """Run logical turns on a fixed shared pool and restore pinned input order."""

    def __init__(self, runtime: AgentRuntime[ProposalT], *, worker_limit: int) -> None:
        if worker_limit < 1:
            raise ValueError("worker_limit must be at least 1")
        self._runtime = runtime
        self._worker_limit = worker_limit

    async def dispatch(
        self, contexts: tuple[ReasoningContext, ...]
    ) -> tuple[TurnDispatchOutcome[ProposalT], ...]:
        if not contexts:
            raise ValueError("dispatch requires at least one logical turn")
        _validate_batch(contexts)

        pending: asyncio.Queue[tuple[int, ReasoningContext]] = asyncio.Queue()
        for index, context in enumerate(contexts):
            pending.put_nowait((index, context))
        outcomes: list[TurnDispatchOutcome[ProposalT] | None] = [None] * len(contexts)

        async def worker() -> None:
            while True:
                try:
                    index, context = pending.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    execution = await asyncio.wait_for(
                        self._runtime.run_turn(context), timeout=context.timeout_s
                    )
                except TimeoutError:
                    outcomes[index] = TurnDispatchOutcome(
                        context=context,
                        disposition=DispatchDisposition.ABSTAIN,
                        event_type="TURN_TIMEOUT",
                        execution=None,
                    )
                else:
                    outcomes[index] = TurnDispatchOutcome(
                        context=context,
                        disposition=DispatchDisposition.COMPLETED,
                        event_type="AGENT_TURN_COMPLETED",
                        execution=execution,
                    )

        workers = tuple(
            asyncio.create_task(worker()) for _ in range(min(self._worker_limit, len(contexts)))
        )
        try:
            await asyncio.gather(*workers)
        finally:
            for worker_task in workers:
                if not worker_task.done():
                    worker_task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

        if any(outcome is None for outcome in outcomes):
            raise RuntimeError("shared worker pool did not produce every dispatch outcome")
        return tuple(outcome for outcome in outcomes if outcome is not None)


def _validate_batch(contexts: tuple[ReasoningContext, ...]) -> None:
    first = contexts[0]
    batch_key = (first.workspace_id, first.session_id, first.round, first.phase)
    turn_ids: set[UUID] = set()
    agent_ids: set[UUID] = set()
    for context in contexts:
        if (context.workspace_id, context.session_id, context.round, context.phase) != batch_key:
            raise ValueError("dispatch contexts must belong to one session round and phase")
        if context.turn_id in turn_ids or context.agent_definition_id in agent_ids:
            raise ValueError("dispatch logical turns and pinned agents must be unique")
        turn_ids.add(context.turn_id)
        agent_ids.add(context.agent_definition_id)
        if (
            context.round == 1
            and context.phase is ReasoningPhase.ASSESS
            and (not context.sealed or context.visible_artifacts)
        ):
            raise ValueError("round 1 ASSESS dispatch must remain sealed")
