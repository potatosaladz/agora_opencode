"""T7-03 authorized, budgeted Critic dispatch and inactivity tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest

from app.application.agent_dispatch import AgentTurnDispatcher, DispatchDisposition
from app.application.coordinator_policy import BudgetCoordinator, BudgetedAgentTurnDispatcher
from app.application.critic_dispatch import CriticTurnCoordinator
from app.domain.agent_activity import ArtifactProposal, ProposalBundle
from app.domain.critique import CritiqueAssignment
from app.domain.reasoning import ActorClass, ArtifactKind
from app.domain.reasoning_ledger import (
    LedgerAppend,
    LedgerEvent,
    LedgerVerification,
    ReasoningLedger,
    ledger_event_hash,
    ledger_payload_hash,
)
from app.ports.agent_runtime import (
    ContextArtifact,
    PinnedAgentDefinition,
    ReasoningContext,
    ReasoningPhase,
    TurnExecutionResult,
)
from tests.traceability import req

U = tuple(UUID(f"018f5000-0000-7000-8000-{index:012d}") for index in range(1, 60))
NOW = datetime(2026, 9, 7, 14, tzinfo=UTC)


def context(index: int, **changes: object) -> ReasoningContext:
    definition_id = U[10 + index]
    target_id = U[20 + index]
    values: dict[str, object] = {
        "workspace_id": U[0],
        "session_id": U[1],
        "agent_definition_id": definition_id,
        "agent_definition_version": 1,
        "agent_definition": PinnedAgentDefinition(
            id=definition_id,
            logical_id=U[30 + index],
            version=1,
            name=f"critic-{index}",
            domain="cross-cutting-critique",
            role_kind="critic",
            strategy_name="cross-cutting-critique",
            strategy_version="1.0.0",
            prompt_ref=f"prompts/critics/{index}.txt",
            prompt_hash="sha256:" + f"{index + 1:064x}",
        ),
        "strategy_name": "cross-cutting-critique",
        "strategy_version": "1.0.0",
        "canonicalizer_version": "canonicalizer@1",
        "turn_id": U[2 + index],
        "correlation_id": U[4],
        "causation_id": U[5],
        "round": 2,
        "phase": ReasoningPhase.CRITIQUE,
        "problem_statement": "Critique the selected public reasoning artifacts.",
        "visible_artifact_ids": (target_id,),
        "visible_artifacts": (
            ContextArtifact(
                id=target_id,
                kind=ArtifactKind.CLAIM.value,
                owner_actor_class=ActorClass.AGENT.value,
                owner_actor_id=U[40 + index],
                round=1,
                content_hash="sha256:" + f"{index + 10:064x}",
                artifact_json=f'{{"id":"{target_id}","kind":"CLAIM"}}',
            ),
        ),
        "sealed": False,
        "budget_remaining_tokens": 500,
        "budget_remaining_usd": Decimal("2"),
        "timeout_s": 1.0,
    }
    values.update(changes)
    return ReasoningContext.model_validate(values)


def assignment(value: ReasoningContext, **changes: object) -> CritiqueAssignment:
    values: dict[str, object] = {
        "protocol_version": "1.0",
        "kind": "critique_assignment",
        "workspace_id": value.workspace_id,
        "session_id": value.session_id,
        "critic_definition_id": value.agent_definition_id,
        "critic_definition_version": value.agent_definition_version,
        "turn_id": value.turn_id,
        "correlation_id": value.correlation_id,
        "causation_id": value.causation_id,
        "round": value.round,
        "target_artifact_ids": value.visible_artifact_ids,
    }
    values.update(changes)
    return CritiqueAssignment.model_validate(values)


def critique_bundle(value: ReasoningContext) -> ProposalBundle:
    return ProposalBundle(
        protocol_version="1.0",
        kind="proposal_bundle",
        turn_id=value.turn_id,
        artifacts=(
            ArtifactProposal(
                op="propose",
                kind=ArtifactKind.CRITIQUE,
                payload={
                    "target_id": value.visible_artifact_ids[0],
                    "critique_type": "EVIDENCE_GAP",
                    "severity": "HIGH",
                    "argument": "The selected Claim has no supporting Evidence.",
                    "resolution": "OPEN",
                },
            ),
        ),
        self_reported_limits=("Fixture Critic",),
    )


def empty_bundle(value: ReasoningContext) -> ProposalBundle:
    return ProposalBundle(
        protocol_version="1.0",
        kind="proposal_bundle",
        turn_id=value.turn_id,
        artifacts=(),
        self_reported_limits=("No defect detected in assigned scope",),
    )


class _Runtime:
    def __init__(
        self,
        bundles: dict[UUID, ProposalBundle],
        *,
        timeout_turn: UUID | None = None,
    ) -> None:
        self.bundles = bundles
        self.timeout_turn = timeout_turn
        self.started: list[ReasoningContext] = []

    async def run_turn(self, value: ReasoningContext) -> TurnExecutionResult[ProposalBundle]:
        self.started.append(value)
        if value.turn_id == self.timeout_turn:
            await asyncio.sleep(1)
        return TurnExecutionResult(proposal=self.bundles[value.turn_id])


class _Budgets:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, ...]] = []

    async def enforce(self, **values: object) -> None:
        agent_ids = cast(tuple[UUID, ...], values["agent_definition_ids"])
        self.calls.append(agent_ids)


class _Ledger:
    def __init__(self) -> None:
        self.events: list[LedgerEvent] = []

    async def append(self, event: LedgerAppend) -> LedgerEvent:
        prior = next((value for value in self.events if value.id == event.id), None)
        if prior is not None:
            expected = prior.model_dump(
                exclude={"ledger_seq", "payload_hash", "prev_hash", "event_hash"}
            )
            if expected != event.model_dump():
                raise ValueError("event id reused with different content")
            return prior
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

    async def read(
        self, workspace_id: UUID, session_id: UUID, *, from_seq: int = 1, limit: int = 1000
    ) -> tuple[LedgerEvent, ...]:
        del workspace_id, session_id
        return tuple(self.events[from_seq - 1 :][:limit])

    async def verify(self, workspace_id: UUID, session_id: UUID) -> LedgerVerification:
        del workspace_id, session_id
        head = self.events[-1].event_hash if self.events else "sha256:" + "0" * 64
        return LedgerVerification(valid=True, event_count=len(self.events), head_hash=head)


def coordinator(runtime: _Runtime) -> tuple[CriticTurnCoordinator, _Budgets, _Ledger]:
    budgets = _Budgets()
    ledger = _Ledger()
    dispatcher = BudgetedAgentTurnDispatcher(
        AgentTurnDispatcher(runtime, worker_limit=2), cast(BudgetCoordinator, budgets)
    )
    return CriticTurnCoordinator(dispatcher, cast(ReasoningLedger, ledger)), budgets, ledger


@req("FR-205", "FR-208", "NFR-009")
async def test_dispatch_is_budgeted_ordered_and_records_only_completed_empty_turn() -> None:
    contexts = (context(0), context(1))
    runtime = _Runtime(
        {
            contexts[0].turn_id: critique_bundle(contexts[0]),
            contexts[1].turn_id: empty_bundle(contexts[1]),
        }
    )
    service, budgets, ledger = coordinator(runtime)

    result = await service.dispatch(
        contexts,
        tuple(assignment(value) for value in contexts),
        prior_consecutive_empty_rounds=(0, 2),
        budget_event_id=U[50],
        inactivity_event_ids=(U[51], U[52]),
        actor_id=U[53],
        checked_at=NOW,
    )

    expected_agents = tuple(value.agent_definition_id for value in contexts)
    assert budgets.calls == [expected_agents, expected_agents]
    assert tuple(outcome.context for outcome in result.outcomes) == contexts
    assert runtime.started == list(contexts)
    assert all(not hasattr(value, "peer_agent_channel") for value in runtime.started)
    assert len(result.inactivity_events) == 1
    assert result.inactivity_events[0].id == U[52]
    assert result.inactivity_events[0].event_type == "CRITIC_INACTIVE"
    assert result.inactivity_events[0].actor_id == contexts[1].agent_definition_id
    assert result.inactivity_events[0].payload["consecutive_empty_rounds"] == 3
    assert result.inactivity_events[0].payload["target_artifact_ids"] == (
        str(contexts[1].visible_artifact_ids[0]),
    )
    assert ledger.events == list(result.inactivity_events)


@req("FR-205", "FR-208", "NFR-009")
@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"phase": ReasoningPhase.ARGUE}, "requires CRITIQUE phase"),
        (
            {
                "agent_definition": context(0).agent_definition.model_copy(
                    update={"role_kind": "domain_expert"}
                )
            },
            "requires a critic definition",
        ),
        ({"sealed": True}, "must expose coordinator-selected public artifacts"),
    ],
)
async def test_non_critic_phase_role_or_visibility_fails_before_budget_and_runtime(
    change: dict[str, object], message: str
) -> None:
    invalid = context(0, **change)
    runtime = _Runtime({invalid.turn_id: empty_bundle(invalid)})
    service, budgets, ledger = coordinator(runtime)

    with pytest.raises(ValueError, match=message):
        await service.dispatch(
            (invalid,),
            (assignment(invalid),),
            prior_consecutive_empty_rounds=(0,),
            budget_event_id=U[50],
            inactivity_event_ids=(U[51],),
            actor_id=U[53],
            checked_at=NOW,
        )

    assert budgets.calls == []
    assert runtime.started == []
    assert ledger.events == []


@req("FR-205", "FR-208", "NFR-009")
async def test_assignment_pin_mismatch_and_input_shape_fail_before_dispatch() -> None:
    value = context(0)
    runtime = _Runtime({value.turn_id: empty_bundle(value)})
    service, budgets, ledger = coordinator(runtime)

    for assignments, history, event_ids, message in (
        (
            (assignment(value, target_artifact_ids=(U[22],)),),
            (0,),
            (U[51],),
            "does not match authorized reasoning context",
        ),
        ((), (), (), "contexts, assignments, history, and inactivity IDs must align"),
        (
            (assignment(value),),
            (),
            (U[51], U[52]),
            "contexts, assignments, history, and inactivity IDs must align",
        ),
        (
            (assignment(value), assignment(value)),
            (0,),
            (U[51], U[51]),
            "contexts, assignments, history, and inactivity IDs must align",
        ),
        (
            (assignment(value),),
            (-1,),
            (U[51],),
            "must be non-negative",
        ),
    ):
        with pytest.raises(ValueError, match=message):
            await service.dispatch(
                (value,),
                assignments,
                prior_consecutive_empty_rounds=history,
                budget_event_id=U[50],
                inactivity_event_ids=event_ids,
                actor_id=U[53],
                checked_at=NOW,
            )

    assert budgets.calls == []
    assert runtime.started == []
    assert ledger.events == []


@req("FR-205", "FR-208", "NFR-009")
async def test_invalid_peer_bundle_leaves_no_partial_inactivity_event() -> None:
    contexts = (context(0), context(1))
    invalid = ProposalBundle(
        protocol_version="1.0",
        kind="proposal_bundle",
        turn_id=contexts[1].turn_id,
        artifacts=(
            ArtifactProposal(
                op="propose",
                kind=ArtifactKind.CLAIM,
                payload={
                    "statement": "Critic exceeded its role.",
                    "claim_type": "FACTUAL",
                    "direction": "SUPPORTS",
                    "strength": "WEAK",
                    "supporting_evidence_ids": [],
                    "opposing_evidence_ids": [],
                    "review_status": "PROPOSED",
                },
            ),
        ),
    )
    runtime = _Runtime(
        {contexts[0].turn_id: empty_bundle(contexts[0]), contexts[1].turn_id: invalid}
    )
    service, budgets, ledger = coordinator(runtime)

    with pytest.raises(ValueError, match="only CRITIQUE"):
        await service.dispatch(
            contexts,
            tuple(assignment(value) for value in contexts),
            prior_consecutive_empty_rounds=(0, 0),
            budget_event_id=U[50],
            inactivity_event_ids=(U[51], U[52]),
            actor_id=U[53],
            checked_at=NOW,
        )

    assert len(budgets.calls) == 2
    assert ledger.events == []


@req("FR-205", "FR-208", "NFR-009")
async def test_timeout_is_abstention_not_critic_inactivity() -> None:
    value = context(0, timeout_s=0.01)
    runtime = _Runtime({value.turn_id: empty_bundle(value)}, timeout_turn=value.turn_id)
    service, budgets, ledger = coordinator(runtime)

    result = await service.dispatch(
        (value,),
        (assignment(value),),
        prior_consecutive_empty_rounds=(2,),
        budget_event_id=U[50],
        inactivity_event_ids=(U[51],),
        actor_id=U[53],
        checked_at=NOW,
    )

    assert result.outcomes[0].disposition is DispatchDisposition.ABSTAIN
    assert result.outcomes[0].event_type == "TURN_TIMEOUT"
    assert result.inactivity_events == ()
    assert len(budgets.calls) == 2
    assert ledger.events == []


@req("FR-205", "FR-208", "NFR-009")
async def test_inactivity_is_not_emitted_before_threshold_or_repeated_after_it() -> None:
    contexts = (context(0), context(1), context(2))
    runtime = _Runtime({value.turn_id: empty_bundle(value) for value in contexts})
    service, budgets, ledger = coordinator(runtime)

    result = await service.dispatch(
        contexts,
        tuple(assignment(value) for value in contexts),
        prior_consecutive_empty_rounds=(0, 1, 3),
        budget_event_id=U[50],
        inactivity_event_ids=(U[51], U[52], U[54]),
        actor_id=U[53],
        checked_at=NOW,
    )

    assert result.inactivity_events == ()
    assert len(budgets.calls) == 2
    assert ledger.events == []
