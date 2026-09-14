"""Coordinator mediation for authorized, bounded Phase 7 Critic turns."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import model_validator

from app.application.agent_dispatch import (
    DispatchDisposition,
    TurnDispatchOutcome,
)
from app.application.coordinator_policy import BudgetedAgentTurnDispatcher
from app.domain.agent_activity import ProposalBundle
from app.domain.critique import CritiqueAssignment, validate_critic_bundle
from app.domain.reasoning import ActorClass, FrozenModel
from app.domain.reasoning_ledger import LedgerAppend, LedgerEvent, ReasoningLedger
from app.ports.agent_runtime import ReasoningContext, ReasoningPhase

__all__ = ["CriticDispatchResult", "CriticTurnCoordinator"]


# trace: FR-205
class CriticDispatchResult(FrozenModel):
    """Stable Critic outcomes and explicit inactivity records in assignment order."""

    outcomes: tuple[TurnDispatchOutcome[ProposalBundle], ...]
    prior_consecutive_empty_rounds: tuple[int, ...]
    inactivity_events: tuple[LedgerEvent, ...]

    @model_validator(mode="after")
    def inactivity_matches_empty_completed_turns(self) -> CriticDispatchResult:
        expected_turns = tuple(
            outcome.context.turn_id
            for outcome, prior_empty in zip(
                self.outcomes, self.prior_consecutive_empty_rounds, strict=True
            )
            if prior_empty == 2
            and outcome.disposition is DispatchDisposition.COMPLETED
            and outcome.proposal is not None
            and not outcome.proposal.artifacts
        )
        actual_turns = tuple(
            UUID(str(event.payload["turn_id"])) for event in self.inactivity_events
        )
        if actual_turns != expected_turns:
            raise ValueError("Critic inactivity events do not match empty completed turns")
        if any(event.event_type != "CRITIC_INACTIVE" for event in self.inactivity_events):
            raise ValueError("Critic dispatch result contains a non-inactivity event")
        return self


class CriticTurnCoordinator:
    """Validate coordinator pins, run budgeted dispatch, and record honest inactivity."""

    def __init__(
        self,
        dispatcher: BudgetedAgentTurnDispatcher[ProposalBundle],
        ledger: ReasoningLedger,
    ) -> None:
        self._dispatcher = dispatcher
        self._ledger = ledger

    async def dispatch(
        self,
        contexts: tuple[ReasoningContext, ...],
        assignments: tuple[CritiqueAssignment, ...],
        *,
        prior_consecutive_empty_rounds: tuple[int, ...],
        budget_event_id: UUID,
        inactivity_event_ids: tuple[UUID, ...],
        actor_id: UUID,
        checked_at: datetime,
    ) -> CriticDispatchResult:
        self._validate_inputs(
            contexts, assignments, prior_consecutive_empty_rounds, inactivity_event_ids
        )
        outcomes = await self._dispatcher.dispatch(
            contexts,
            budget_event_id=budget_event_id,
            actor_id=actor_id,
            checked_at=checked_at,
        )
        if tuple(outcome.context for outcome in outcomes) != contexts:
            raise RuntimeError("Critic dispatcher changed coordinator assignment order")

        for outcome, assignment in zip(outcomes, assignments, strict=True):
            if outcome.disposition is DispatchDisposition.COMPLETED:
                if outcome.proposal is None:
                    raise RuntimeError("completed Critic turn has no proposal")
                validate_critic_bundle(outcome.proposal, assignment)

        inactivity: list[LedgerEvent] = []
        for outcome, assignment, prior_empty, event_id in zip(
            outcomes,
            assignments,
            prior_consecutive_empty_rounds,
            inactivity_event_ids,
            strict=True,
        ):
            if (
                prior_empty == 2
                and outcome.disposition is DispatchDisposition.COMPLETED
                and outcome.proposal is not None
                and not outcome.proposal.artifacts
            ):
                inactivity.append(
                    await self._ledger.append(
                        LedgerAppend(
                            id=event_id,
                            workspace_id=assignment.workspace_id,
                            session_id=assignment.session_id,
                            event_type="CRITIC_INACTIVE",
                            payload_schema_version=1,
                            causation_id=assignment.causation_id,
                            correlation_id=assignment.correlation_id,
                            actor_class=ActorClass.AGENT,
                            actor_id=assignment.critic_definition_id,
                            round=assignment.round,
                            payload={
                                "turn_id": str(assignment.turn_id),
                                "critic_definition_id": str(assignment.critic_definition_id),
                                "critic_definition_version": assignment.critic_definition_version,
                                "consecutive_empty_rounds": prior_empty + 1,
                                "target_artifact_ids": [
                                    str(value) for value in assignment.target_artifact_ids
                                ],
                                "reason": "completed Critic turn produced no Critique proposals",
                            },
                            recorded_at=checked_at,
                        )
                    )
                )
        return CriticDispatchResult(
            outcomes=outcomes,
            prior_consecutive_empty_rounds=prior_consecutive_empty_rounds,
            inactivity_events=tuple(inactivity),
        )

    @staticmethod
    def _validate_inputs(
        contexts: tuple[ReasoningContext, ...],
        assignments: tuple[CritiqueAssignment, ...],
        prior_consecutive_empty_rounds: tuple[int, ...],
        inactivity_event_ids: tuple[UUID, ...],
    ) -> None:
        if not contexts:
            raise ValueError("Critic dispatch requires at least one turn")
        if (
            len(contexts) != len(assignments)
            or len(contexts) != len(prior_consecutive_empty_rounds)
            or len(contexts) != len(inactivity_event_ids)
        ):
            raise ValueError("Critic contexts, assignments, history, and inactivity IDs must align")
        if any(value < 0 for value in prior_consecutive_empty_rounds):
            raise ValueError("Critic prior consecutive empty rounds must be non-negative")
        if len(set(inactivity_event_ids)) != len(inactivity_event_ids):
            raise ValueError("Critic inactivity event IDs must be unique")
        for context, assignment in zip(contexts, assignments, strict=True):
            if context.phase is not ReasoningPhase.CRITIQUE:
                raise ValueError("Critic dispatch requires CRITIQUE phase")
            if context.agent_definition.role_kind != "critic":
                raise ValueError("Critic dispatch requires a critic definition")
            if context.sealed:
                raise ValueError("Critic context must expose coordinator-selected public artifacts")
            pins = (
                context.workspace_id,
                context.session_id,
                context.agent_definition_id,
                context.agent_definition_version,
                context.turn_id,
                context.correlation_id,
                context.causation_id,
                context.round,
                context.visible_artifact_ids,
            )
            expected = (
                assignment.workspace_id,
                assignment.session_id,
                assignment.critic_definition_id,
                assignment.critic_definition_version,
                assignment.turn_id,
                assignment.correlation_id,
                assignment.causation_id,
                assignment.round,
                assignment.target_artifact_ids,
            )
            if pins != expected:
                raise ValueError("Critic assignment does not match authorized reasoning context")
