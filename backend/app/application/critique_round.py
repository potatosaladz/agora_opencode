"""Deterministic Phase 7 CRITIQUE then REVISE round orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import field_validator, model_validator

from app.application.agent_dispatch import DispatchDisposition, TurnDispatchOutcome
from app.application.artifact_commit import ArtifactWriteResult
from app.application.coordinator_policy import BudgetedAgentTurnDispatcher
from app.application.critic_dispatch import CriticDispatchResult, CriticTurnCoordinator
from app.application.critique_commit import CritiqueProposalCommitter
from app.application.critique_response import CritiqueResponseCommand, CritiqueResponseCommitter
from app.application.proposal_commit import AgentTurnCommit
from app.domain.agent_activity import AgentTurnResult, ProposalBundle
from app.domain.critique import (
    CritiqueAssignment,
    CritiqueResponseProposal,
    CritiqueResponseResult,
    validate_critic_bundle,
)
from app.domain.critique_handoff import (
    CritiqueExplanationHandoff,
    CritiqueExplanationHandoffReader,
)
from app.domain.reasoning import ActorClass, FrozenModel
from app.domain.reasoning_ledger import AgentProposalLedger, LedgerAppend, LedgerEvent
from app.ports.agent_runtime import ReasoningContext, ReasoningPhase

__all__ = ["CritiqueRoundCommand", "CritiqueRoundCoordinator", "CritiqueRoundResult"]


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("committed_at must include an RFC 3339 offset")
    return value.astimezone(UTC)


class CritiqueRoundCommand(FrozenModel):
    """Complete coordinator-owned identities and work for one Phase 7 round."""

    workspace_id: UUID
    session_id: UUID
    round: int
    critic_contexts: tuple[ReasoningContext, ...]
    critic_assignments: tuple[CritiqueAssignment, ...]
    prior_consecutive_empty_rounds: tuple[int, ...]
    budget_event_id: UUID
    inactivity_event_ids: tuple[UUID, ...]
    timeout_event_ids: tuple[UUID, ...]
    policy_actor_id: UUID
    committed_at: datetime
    peer_contexts: tuple[ReasoningContext, ...] = ()
    peer_assignments: tuple[CritiqueAssignment, ...] = ()
    peer_budget_event_id: UUID | None = None
    peer_timeout_event_ids: tuple[UUID, ...] = ()
    response_contexts: tuple[ReasoningContext, ...] = ()
    response_budget_event_id: UUID | None = None
    response_timeout_event_ids: tuple[UUID, ...] = ()
    schema_version: int = 1

    _committed_at_utc = field_validator("committed_at")(_aware_utc)

    @model_validator(mode="after")
    def valid_round_batch(self) -> CritiqueRoundCommand:
        if self.schema_version != 1:
            raise ValueError("unsupported CritiqueRoundCommand schema_version")
        if self.round < 1:
            raise ValueError("Critique round must be positive")
        if not self.critic_contexts:
            raise ValueError("Critique round requires at least one Critic turn")
        count = len(self.critic_contexts)
        if not all(
            len(values) == count
            for values in (
                self.critic_assignments,
                self.prior_consecutive_empty_rounds,
                self.inactivity_event_ids,
                self.timeout_event_ids,
            )
        ):
            raise ValueError(
                "Critique round contexts, assignments, history, and event IDs must align"
            )
        if any(value < 0 for value in self.prior_consecutive_empty_rounds):
            raise ValueError("Critique prior consecutive empty rounds must be non-negative")

        allocated_ids = (
            self.budget_event_id,
            *self.inactivity_event_ids,
            *self.timeout_event_ids,
            *((self.peer_budget_event_id,) if self.peer_budget_event_id is not None else ()),
            *self.peer_timeout_event_ids,
            *(
                (self.response_budget_event_id,)
                if self.response_budget_event_id is not None
                else ()
            ),
            *self.response_timeout_event_ids,
        )
        if len(set(allocated_ids)) != len(allocated_ids):
            raise ValueError("Critique round event IDs must be unique")

        critic_turn_ids: set[UUID] = set()
        critic_definition_ids: set[UUID] = set()
        for context, assignment in zip(self.critic_contexts, self.critic_assignments, strict=True):
            self._validate_critic_turn(context, assignment)
            if context.turn_id in critic_turn_ids:
                raise ValueError("Critique round Critic turn IDs must be unique")
            if context.agent_definition_id in critic_definition_ids:
                raise ValueError("Critique round Critic definitions must be unique")
            critic_turn_ids.add(context.turn_id)
            critic_definition_ids.add(context.agent_definition_id)

        if len(self.peer_contexts) != len(self.peer_assignments) or len(self.peer_contexts) != len(
            self.peer_timeout_event_ids
        ):
            raise ValueError("peer Critique contexts, assignments, and timeout IDs must align")
        if bool(self.peer_contexts) != (self.peer_budget_event_id is not None):
            raise ValueError("peer Critique work and its budget event ID must be supplied together")
        peer_turn_ids: set[UUID] = set()
        peer_definition_ids: set[UUID] = set()
        for context, assignment in zip(self.peer_contexts, self.peer_assignments, strict=True):
            self._validate_critic_turn(context, assignment, role_kind="domain_expert")
            if context.turn_id in critic_turn_ids or context.turn_id in peer_turn_ids:
                raise ValueError("Critique round turn IDs must be unique")
            if context.agent_definition_id in peer_definition_ids:
                raise ValueError("peer Critique definitions must be unique")
            peer_turn_ids.add(context.turn_id)
            peer_definition_ids.add(context.agent_definition_id)

        if len(self.response_contexts) != len(self.response_timeout_event_ids):
            raise ValueError("REVISE contexts and timeout IDs must align")
        if bool(self.response_contexts) != (self.response_budget_event_id is not None):
            raise ValueError("REVISE work and its budget event ID must be supplied together")
        response_turn_ids: set[UUID] = set()
        response_definition_ids: set[UUID] = set()
        for context in self.response_contexts:
            if (context.workspace_id, context.session_id, context.round) != (
                self.workspace_id,
                self.session_id,
                self.round,
            ):
                raise ValueError("REVISE context belongs to another session round")
            if context.phase is not ReasoningPhase.REVISE or not context.sealed:
                raise ValueError("responses require sealed REVISE contexts")
            if context.turn_id in critic_turn_ids or context.turn_id in peer_turn_ids:
                raise ValueError("Critique round turn IDs must be unique")
            if context.turn_id in response_turn_ids:
                raise ValueError("REVISE turn IDs must be unique")
            if context.agent_definition_id in response_definition_ids:
                raise ValueError("REVISE responding definitions must be unique")
            response_turn_ids.add(context.turn_id)
            response_definition_ids.add(context.agent_definition_id)
        return self

    def _validate_critic_turn(
        self,
        context: ReasoningContext,
        assignment: CritiqueAssignment,
        *,
        role_kind: str = "critic",
    ) -> None:
        if (context.workspace_id, context.session_id, context.round) != (
            self.workspace_id,
            self.session_id,
            self.round,
        ):
            raise ValueError("Critic turn belongs to another session round")
        if context.phase is not ReasoningPhase.CRITIQUE:
            raise ValueError("Critique round Critic turns require CRITIQUE phase")
        if context.agent_definition.role_kind != role_kind:
            raise ValueError(f"Critique round requires {role_kind} definitions")
        if context.sealed:
            raise ValueError("Critique round requires public Critic context")
        actual = (
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
        if actual != expected:
            raise ValueError("Critique assignment does not match its round context")


class CritiqueRoundResult(FrozenModel):
    """Ordered durable effects and final handoff from one Critique/revision round."""

    dispatch: CriticDispatchResult
    peer_outcomes: tuple[TurnDispatchOutcome[ProposalBundle], ...]
    response_outcomes: tuple[TurnDispatchOutcome[CritiqueResponseProposal], ...]
    critique_writes: tuple[tuple[ArtifactWriteResult, ...], ...]
    timeout_events: tuple[LedgerEvent, ...]
    response_results: tuple[CritiqueResponseResult, ...]
    handoff: CritiqueExplanationHandoff


class CritiqueRoundCoordinator:
    """Run CRITIQUE before stably ordered REVISE commits in one caller transaction."""

    def __init__(
        self,
        critic_dispatch: CriticTurnCoordinator,
        critique_dispatcher: BudgetedAgentTurnDispatcher[ProposalBundle],
        response_dispatcher: BudgetedAgentTurnDispatcher[CritiqueResponseProposal],
        critiques: CritiqueProposalCommitter,
        responses: CritiqueResponseCommitter,
        ledger: AgentProposalLedger,
        handoffs: CritiqueExplanationHandoffReader,
    ) -> None:
        self._critic_dispatch = critic_dispatch
        self._critique_dispatcher = critique_dispatcher
        self._response_dispatcher = response_dispatcher
        self._critiques = critiques
        self._responses = responses
        self._ledger = ledger
        self._handoffs = handoffs

    async def run(self, command: CritiqueRoundCommand) -> CritiqueRoundResult:
        dispatch = await self._critic_dispatch.dispatch(
            command.critic_contexts,
            command.critic_assignments,
            prior_consecutive_empty_rounds=command.prior_consecutive_empty_rounds,
            budget_event_id=command.budget_event_id,
            inactivity_event_ids=command.inactivity_event_ids,
            actor_id=command.policy_actor_id,
            checked_at=command.committed_at,
        )
        peer_outcomes: tuple[TurnDispatchOutcome[ProposalBundle], ...] = ()
        if command.peer_contexts:
            assert command.peer_budget_event_id is not None
            peer_outcomes = await self._critique_dispatcher.dispatch(
                command.peer_contexts,
                budget_event_id=command.peer_budget_event_id,
                actor_id=command.policy_actor_id,
                checked_at=command.committed_at,
            )
            if tuple(outcome.context for outcome in peer_outcomes) != command.peer_contexts:
                raise RuntimeError("peer Critique dispatcher changed coordinator assignment order")

        critic_commits = self._prepare_critique_commits(
            dispatch.outcomes, command.critic_assignments, committed_at=command.committed_at
        )
        peer_commits = self._prepare_critique_commits(
            peer_outcomes, command.peer_assignments, committed_at=command.committed_at
        )

        critique_writes: list[tuple[ArtifactWriteResult, ...]] = []
        timeout_events: list[LedgerEvent] = []
        for index, (outcome, assignment, prepared) in enumerate(
            zip(dispatch.outcomes, command.critic_assignments, critic_commits, strict=True)
        ):
            if outcome.disposition is DispatchDisposition.ABSTAIN:
                timeout_events.append(
                    await self._ledger.append(
                        self._timeout_event(
                            outcome.context,
                            assignment.target_artifact_ids,
                            event_id=command.timeout_event_ids[index],
                            recorded_at=command.committed_at,
                        )
                    )
                )
                continue
            assert prepared is not None
            critique_writes.append(await self._critiques.commit(prepared, assignment))

        for index, (outcome, assignment, prepared) in enumerate(
            zip(peer_outcomes, command.peer_assignments, peer_commits, strict=True)
        ):
            if outcome.disposition is DispatchDisposition.ABSTAIN:
                timeout_events.append(
                    await self._ledger.append(
                        self._timeout_event(
                            outcome.context,
                            assignment.target_artifact_ids,
                            event_id=command.peer_timeout_event_ids[index],
                            recorded_at=command.committed_at,
                        )
                    )
                )
                continue
            assert prepared is not None
            critique_writes.append(await self._critiques.commit(prepared, assignment))

        response_outcomes: tuple[TurnDispatchOutcome[CritiqueResponseProposal], ...] = ()
        if command.response_contexts:
            assert command.response_budget_event_id is not None
            response_outcomes = await self._response_dispatcher.dispatch(
                command.response_contexts,
                budget_event_id=command.response_budget_event_id,
                actor_id=command.policy_actor_id,
                checked_at=command.committed_at,
            )
            if tuple(outcome.context for outcome in response_outcomes) != command.response_contexts:
                raise RuntimeError("REVISE dispatcher changed coordinator assignment order")
        response_commands = self._prepare_response_commits(
            response_outcomes, committed_at=command.committed_at
        )
        for index, response_outcome in enumerate(response_outcomes):
            if response_outcome.disposition is DispatchDisposition.ABSTAIN:
                timeout_events.append(
                    await self._ledger.append(
                        self._timeout_event(
                            response_outcome.context,
                            response_outcome.context.visible_artifact_ids,
                            event_id=command.response_timeout_event_ids[index],
                            recorded_at=command.committed_at,
                        )
                    )
                )

        ordered_responses = tuple(
            sorted(
                (response for response in response_commands if response is not None),
                key=lambda item: (
                    item.execution.proposal.target_artifact_id.int,
                    item.execution.proposal.responding_definition_id.int,
                ),
            )
        )
        response_results = tuple(
            [await self._responses.commit(response) for response in ordered_responses]
        )
        handoff = await self._handoffs.read(command.workspace_id, command.session_id)
        return CritiqueRoundResult(
            dispatch=dispatch,
            peer_outcomes=peer_outcomes,
            response_outcomes=response_outcomes,
            critique_writes=tuple(critique_writes),
            timeout_events=tuple(timeout_events),
            response_results=response_results,
            handoff=handoff,
        )

    @staticmethod
    def _prepare_critique_commits(
        outcomes: tuple[TurnDispatchOutcome[ProposalBundle], ...],
        assignments: tuple[CritiqueAssignment, ...],
        *,
        committed_at: datetime,
    ) -> tuple[AgentTurnCommit | None, ...]:
        prepared: list[AgentTurnCommit | None] = []
        for outcome, assignment in zip(outcomes, assignments, strict=True):
            if outcome.disposition is DispatchDisposition.ABSTAIN:
                prepared.append(None)
                continue
            execution = outcome.execution
            if execution is None:
                raise RuntimeError("completed Critic outcome has no execution")
            validate_critic_bundle(execution.proposal, assignment)
            if (
                execution.provider is None
                or execution.model is None
                or execution.raw_artifact_ref is None
            ):
                raise ValueError("completed Critic execution requires full provider attribution")
            prepared.append(
                AgentTurnCommit(
                    context=outcome.context,
                    result=AgentTurnResult(
                        turn_id=outcome.context.turn_id,
                        agent_definition_id=outcome.context.agent_definition_id,
                        bundle=execution.proposal,
                        provider=execution.provider,
                        model=execution.model,
                        input_tokens=execution.input_tokens,
                        output_tokens=execution.output_tokens,
                        cost_usd=execution.cost_usd,
                        raw_artifact_ref=execution.raw_artifact_ref,
                    ),
                    committed_at=committed_at,
                )
            )
        return tuple(prepared)

    @staticmethod
    def _prepare_response_commits(
        outcomes: tuple[TurnDispatchOutcome[CritiqueResponseProposal], ...],
        *,
        committed_at: datetime,
    ) -> tuple[CritiqueResponseCommand | None, ...]:
        prepared: list[CritiqueResponseCommand | None] = []
        response_ids: set[UUID] = set()
        critique_ids: set[UUID] = set()
        for outcome in outcomes:
            if outcome.disposition is DispatchDisposition.ABSTAIN:
                prepared.append(None)
                continue
            execution = outcome.execution
            if execution is None:
                raise RuntimeError("completed REVISE outcome has no execution")
            command = CritiqueResponseCommand(
                context=outcome.context,
                execution=execution,
                committed_at=committed_at,
            )
            proposal = command.execution.proposal
            if proposal.response_id in response_ids:
                raise ValueError("Critique round response IDs must be unique")
            if proposal.critique_id in critique_ids:
                raise ValueError("Critique round may respond to each Critique head only once")
            response_ids.add(proposal.response_id)
            critique_ids.add(proposal.critique_id)
            prepared.append(command)
        return tuple(prepared)

    @staticmethod
    def _timeout_event(
        context: ReasoningContext,
        target_artifact_ids: tuple[UUID, ...],
        *,
        event_id: UUID,
        recorded_at: datetime,
    ) -> LedgerAppend:
        return LedgerAppend(
            id=event_id,
            workspace_id=context.workspace_id,
            session_id=context.session_id,
            event_type="TURN_TIMEOUT",
            payload_schema_version=1,
            causation_id=context.causation_id,
            correlation_id=context.correlation_id,
            actor_class=ActorClass.AGENT,
            actor_id=context.agent_definition_id,
            round=context.round,
            payload={
                "turn_id": str(context.turn_id),
                "agent_definition_id": str(context.agent_definition_id),
                "agent_definition_version": context.agent_definition_version,
                "phase": context.phase.value,
                "disposition": DispatchDisposition.ABSTAIN.value,
                "target_artifact_ids": [str(value) for value in target_artifact_ids],
                "timeout_s": str(context.timeout_s),
                "reason": "Agent turn exceeded its coordinator deadline",
            },
            recorded_at=recorded_at,
        )
