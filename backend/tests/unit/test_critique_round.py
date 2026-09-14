"""T7-07 deterministic Critique/revision round and handoff contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.application.agent_dispatch import DispatchDisposition, TurnDispatchOutcome
from app.application.coordinator_policy import BudgetedAgentTurnDispatcher
from app.application.critic_dispatch import CriticDispatchResult, CriticTurnCoordinator
from app.application.critique_commit import CritiqueProposalCommitter
from app.application.critique_response import CritiqueResponseCommand, CritiqueResponseCommitter
from app.application.critique_round import CritiqueRoundCommand, CritiqueRoundCoordinator
from app.domain.agent_activity import ArtifactProposal, ProposalBundle
from app.domain.critique import (
    CritiqueAssignment,
    CritiqueResponseDisposition,
    CritiqueResponseProposal,
    CritiqueResponseResult,
    CritiqueResponseResultStatus,
)
from app.domain.critique_handoff import (
    CritiqueExplanationEntry,
    CritiqueExplanationHandoff,
    CritiqueExplanationHandoffReader,
    CritiqueHandoffEmptyReason,
)
from app.domain.reasoning import (
    ActorClass,
    ArtifactKind,
    CritiqueType,
    Resolution,
    Severity,
)
from app.domain.reasoning_ledger import (
    AgentProposalLedger,
    LedgerAppend,
    LedgerEvent,
    LedgerVerification,
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

U = tuple(UUID(f"018fa000-0000-7000-8000-{value:012d}") for value in range(1, 100))
NOW = datetime(2026, 9, 7, 20, tzinfo=UTC)


def _definition(index: int, *, role: str) -> PinnedAgentDefinition:
    return PinnedAgentDefinition(
        id=U[index],
        logical_id=U[index + 30],
        version=1,
        name=f"{role}-{index}",
        domain="critique-round",
        role_kind=role,
        strategy_name=f"{role}-strategy",
        strategy_version="1.0.0",
        prompt_ref=f"prompts/{role}/{index}.txt",
        prompt_hash="sha256:" + f"{index:064x}",
    )


def critic_context(index: int, *, role: str = "critic") -> ReasoningContext:
    definition = _definition(10 + index, role=role)
    target_id = U[20 + index]
    return ReasoningContext(
        workspace_id=U[0],
        session_id=U[1],
        agent_definition_id=definition.id,
        agent_definition_version=definition.version,
        agent_definition=definition,
        strategy_name=definition.strategy_name,
        strategy_version=definition.strategy_version,
        canonicalizer_version="canonicalizer@1",
        turn_id=U[2 + index],
        correlation_id=U[5],
        causation_id=U[6],
        round=2,
        phase=ReasoningPhase.CRITIQUE,
        problem_statement="Critique assigned public artifacts.",
        visible_artifact_ids=(target_id,),
        visible_artifacts=(
            ContextArtifact(
                id=target_id,
                kind=ArtifactKind.CLAIM.value,
                owner_actor_class=ActorClass.AGENT.value,
                owner_actor_id=U[40 + index],
                round=1,
                content_hash="sha256:" + f"{index + 1:064x}",
                artifact_json=f'{{"id":"{target_id}","kind":"CLAIM"}}',
            ),
        ),
        sealed=False,
        budget_remaining_tokens=500,
        budget_remaining_usd=Decimal("1"),
        timeout_s=10,
    )


def assignment(context: ReasoningContext) -> CritiqueAssignment:
    return CritiqueAssignment(
        protocol_version="1.0",
        kind="critique_assignment",
        workspace_id=context.workspace_id,
        session_id=context.session_id,
        critic_definition_id=context.agent_definition_id,
        critic_definition_version=context.agent_definition_version,
        turn_id=context.turn_id,
        correlation_id=context.correlation_id,
        causation_id=context.causation_id,
        round=context.round,
        target_artifact_ids=context.visible_artifact_ids,
    )


def critique_bundle(
    context: ReasoningContext,
    *,
    critique_type: str = "EVIDENCE_GAP",
) -> ProposalBundle:
    return ProposalBundle(
        protocol_version="1.0",
        kind="proposal_bundle",
        turn_id=context.turn_id,
        artifacts=(
            ArtifactProposal(
                op="propose",
                kind=ArtifactKind.CRITIQUE,
                payload={
                    "target_id": str(context.visible_artifact_ids[0]),
                    "critique_type": critique_type,
                    "severity": "HIGH",
                    "argument": "The Claim has no supporting Evidence.",
                    "resolution": "OPEN",
                },
            ),
        ),
    )


def outcome(
    context: ReasoningContext,
    *,
    attributed: bool = True,
    bundle: ProposalBundle | None = None,
) -> TurnDispatchOutcome[ProposalBundle]:
    return TurnDispatchOutcome(
        context=context,
        disposition=DispatchDisposition.COMPLETED,
        event_type="AGENT_TURN_COMPLETED",
        execution=TurnExecutionResult(
            proposal=bundle or critique_bundle(context),
            provider="mock" if attributed else None,
            model="critic-fixture" if attributed else None,
            input_tokens=10 if attributed else 0,
            output_tokens=5 if attributed else 0,
            cost_usd=Decimal("0.001") if attributed else Decimal(0),
            raw_artifact_ref=("raw/critic.json#sha256:" + "a" * 64) if attributed else None,
        ),
    )


def timeout_outcome(context: ReasoningContext) -> TurnDispatchOutcome[ProposalBundle]:
    return TurnDispatchOutcome(
        context=context,
        disposition=DispatchDisposition.ABSTAIN,
        event_type="TURN_TIMEOUT",
        execution=None,
    )


def response_timeout_outcome(
    context: ReasoningContext,
) -> TurnDispatchOutcome[CritiqueResponseProposal]:
    return TurnDispatchOutcome(
        context=context,
        disposition=DispatchDisposition.ABSTAIN,
        event_type="TURN_TIMEOUT",
        execution=None,
    )


def response_outcome(
    index: int,
    *,
    target_id: UUID,
    responder_id: UUID,
    response_id: UUID | None = None,
    critique_id: UUID | None = None,
    attributed: bool = True,
) -> TurnDispatchOutcome[CritiqueResponseProposal]:
    definition = PinnedAgentDefinition(
        id=responder_id,
        logical_id=U[70 + index],
        version=1,
        name=f"responder-{index}",
        domain="critique-response",
        role_kind="domain_expert",
        strategy_name="response-strategy",
        strategy_version="1.0.0",
        prompt_ref=f"prompts/responder/{index}.txt",
        prompt_hash="sha256:" + f"{index + 20:064x}",
    )
    assigned_critique_id = critique_id or U[50 + index]
    visible_ids = (assigned_critique_id, target_id)

    def artifact_kind(artifact_id: UUID) -> str:
        return (
            ArtifactKind.CRITIQUE.value
            if artifact_id == assigned_critique_id
            else ArtifactKind.CLAIM.value
        )

    context = ReasoningContext(
        workspace_id=U[0],
        session_id=U[1],
        agent_definition_id=responder_id,
        agent_definition_version=1,
        agent_definition=definition,
        strategy_name=definition.strategy_name,
        strategy_version=definition.strategy_version,
        canonicalizer_version="canonicalizer@1",
        turn_id=U[60 + index],
        correlation_id=U[5],
        causation_id=U[6],
        round=2,
        phase=ReasoningPhase.REVISE,
        problem_statement="Address the assigned Critique.",
        visible_artifact_ids=visible_ids,
        visible_artifacts=tuple(
            ContextArtifact(
                id=artifact_id,
                kind=artifact_kind(artifact_id),
                owner_actor_class=ActorClass.AGENT.value,
                owner_actor_id=responder_id,
                round=1,
                content_hash="sha256:" + f"{artifact_id.int % 100:064x}",
                artifact_json=f'{{"id":"{artifact_id}"}}',
            )
            for artifact_id in visible_ids
        ),
        sealed=True,
        budget_remaining_tokens=500,
        budget_remaining_usd=Decimal("1"),
        timeout_s=10,
    )
    proposal = CritiqueResponseProposal(
        protocol_version="1.0",
        kind="critique_response",
        response_id=response_id or U[80 + index],
        workspace_id=U[0],
        session_id=U[1],
        responding_definition_id=responder_id,
        responding_definition_version=1,
        turn_id=context.turn_id,
        correlation_id=context.correlation_id,
        causation_id=context.causation_id,
        round=2,
        critique_id=assigned_critique_id,
        critique_version=1,
        target_artifact_id=target_id,
        target_artifact_version=1,
        disposition=CritiqueResponseDisposition.ACCEPT,
        rationale="Accept the identified gap.",
    )
    return TurnDispatchOutcome(
        context=context,
        disposition=DispatchDisposition.COMPLETED,
        event_type="AGENT_TURN_COMPLETED",
        execution=TurnExecutionResult(
            proposal=proposal,
            provider="mock" if attributed else None,
            model="response-fixture" if attributed else None,
            input_tokens=10 if attributed else 0,
            output_tokens=5 if attributed else 0,
            cost_usd=Decimal("0.001") if attributed else Decimal(0),
            raw_artifact_ref=("raw/response.json#sha256:" + "b" * 64) if attributed else None,
        ),
    )


class CriticDispatchStub:
    def __init__(
        self, outcomes: tuple[TurnDispatchOutcome[ProposalBundle], ...], calls: list[str]
    ) -> None:
        self.outcomes = outcomes
        self.calls = calls

    async def dispatch(self, *args: object, **kwargs: object) -> CriticDispatchResult:
        del args, kwargs
        self.calls.append("critic-dispatch")
        return CriticDispatchResult(
            outcomes=self.outcomes,
            prior_consecutive_empty_rounds=tuple(0 for _ in self.outcomes),
            inactivity_events=(),
        )


class BudgetedDispatchStub:
    def __init__(
        self,
        label: str,
        outcomes: tuple[TurnDispatchOutcome[Any], ...],
        calls: list[str],
    ) -> None:
        self.label = label
        self.outcomes = outcomes
        self.calls = calls

    async def dispatch(
        self, contexts: tuple[ReasoningContext, ...], **kwargs: object
    ) -> tuple[TurnDispatchOutcome[Any], ...]:
        expected_budget_event_id = U[40] if self.label == "peer" else U[43]
        assert kwargs == {
            "budget_event_id": expected_budget_event_id,
            "actor_id": U[39],
            "checked_at": NOW,
        }
        self.calls.append(f"{self.label}-dispatch")
        assert contexts == tuple(value.context for value in self.outcomes)
        return self.outcomes


class CritiqueCommitStub:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def commit(self, command: object, assignment: CritiqueAssignment) -> tuple[()]:
        del command
        self.calls.append(f"critique:{assignment.critic_definition_id}")
        return ()


class ResponseCommitStub:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def commit(self, command: CritiqueResponseCommand) -> CritiqueResponseResult:
        proposal = command.execution.proposal
        self.calls.append(
            f"response:{proposal.target_artifact_id}:{proposal.responding_definition_id}"
        )
        return CritiqueResponseResult(
            response_id=proposal.response_id,
            workspace_id=proposal.workspace_id,
            session_id=proposal.session_id,
            status=CritiqueResponseResultStatus.RESOLVED,
            disposition=CritiqueResponseDisposition.ACCEPT,
            resolution=Resolution.RESOLVED,
            critique_revision_id=U[90 + proposal.response_id.int % 5],
            critique_revision_version=2,
            response_event_id=U[95 + proposal.response_id.int % 4],
            committed_at=command.committed_at,
        )


class LedgerStub:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.events: list[LedgerEvent] = []

    async def append(self, value: LedgerAppend) -> LedgerEvent:
        self.calls.append(f"ledger:{value.event_type}:{value.actor_id}")
        event = LedgerEvent(
            **value.model_dump(),
            ledger_seq=len(self.events) + 1,
            payload_hash=ledger_payload_hash(value.payload),
            prev_hash=self.events[-1].event_hash if self.events else "sha256:" + "0" * 64,
            event_hash="sha256:" + "0" * 64,
        )
        event = event.model_copy(update={"event_hash": ledger_event_hash(event)})
        self.events.append(event)
        return event

    async def get_by_id(
        self, workspace_id: UUID, session_id: UUID, event_id: UUID
    ) -> LedgerEvent | None:
        del workspace_id, session_id, event_id
        return None

    async def read(
        self, workspace_id: UUID, session_id: UUID, *, from_seq: int = 1, limit: int = 1000
    ) -> tuple[LedgerEvent, ...]:
        del workspace_id, session_id
        return tuple(self.events[from_seq - 1 :][:limit])

    async def verify(self, workspace_id: UUID, session_id: UUID) -> LedgerVerification:
        del workspace_id, session_id
        return LedgerVerification(
            valid=True,
            event_count=len(self.events),
            head_hash=self.events[-1].event_hash if self.events else "sha256:" + "0" * 64,
        )


class HandoffStub:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def read(self, workspace_id: UUID, session_id: UUID) -> CritiqueExplanationHandoff:
        self.calls.append("handoff")
        return CritiqueExplanationHandoff(
            workspace_id=workspace_id,
            session_id=session_id,
            entries=(),
            empty_reason=CritiqueHandoffEmptyReason.COMPLETED_CRITIC_RUN_WITHOUT_CRITIQUES,
        )


def round_command(
    contexts: tuple[ReasoningContext, ...],
    *,
    peers: tuple[ReasoningContext, ...] = (),
    responses: tuple[ReasoningContext, ...] = (),
    **changes: Any,
) -> CritiqueRoundCommand:
    values: dict[str, Any] = {
        "workspace_id": U[0],
        "session_id": U[1],
        "round": 2,
        "critic_contexts": contexts,
        "critic_assignments": tuple(assignment(context) for context in contexts),
        "prior_consecutive_empty_rounds": tuple(0 for _ in contexts),
        "budget_event_id": U[30],
        "inactivity_event_ids": tuple(U[31 + index] for index in range(len(contexts))),
        "timeout_event_ids": tuple(U[35 + index] for index in range(len(contexts))),
        "policy_actor_id": U[39],
        "committed_at": NOW,
    }
    if peers:
        values.update(
            {
                "peer_contexts": peers,
                "peer_assignments": tuple(assignment(context) for context in peers),
                "peer_budget_event_id": U[40],
                "peer_timeout_event_ids": tuple(U[41 + index] for index in range(len(peers))),
            }
        )
    if responses:
        values.update(
            {
                "response_contexts": responses,
                "response_budget_event_id": U[43],
                "response_timeout_event_ids": tuple(
                    U[44 + index] for index in range(len(responses))
                ),
            }
        )
    values.update(changes)
    return CritiqueRoundCommand.model_validate(values)


def coordinator(
    outcomes: tuple[TurnDispatchOutcome[ProposalBundle], ...],
    calls: list[str],
    *,
    peer_outcomes: tuple[TurnDispatchOutcome[ProposalBundle], ...] = (),
    response_outcomes: tuple[TurnDispatchOutcome[CritiqueResponseProposal], ...] = (),
) -> CritiqueRoundCoordinator:
    ledger = LedgerStub(calls)
    return CritiqueRoundCoordinator(
        cast(CriticTurnCoordinator, CriticDispatchStub(outcomes, calls)),
        cast(
            BudgetedAgentTurnDispatcher[ProposalBundle],
            BudgetedDispatchStub("peer", peer_outcomes, calls),
        ),
        cast(
            BudgetedAgentTurnDispatcher[CritiqueResponseProposal],
            BudgetedDispatchStub("response", response_outcomes, calls),
        ),
        cast(CritiqueProposalCommitter, CritiqueCommitStub(calls)),
        cast(CritiqueResponseCommitter, ResponseCommitStub(calls)),
        cast(AgentProposalLedger, ledger),
        cast(CritiqueExplanationHandoffReader, HandoffStub(calls)),
    )


@req("FR-205", "FR-501", "FR-503", "FR-504")
async def test_round_dispatches_and_commits_all_phases_in_deterministic_order() -> None:
    contexts = (critic_context(0), critic_context(1))
    peers = (critic_context(2, role="domain_expert"),)
    later_target = response_outcome(0, target_id=U[29], responder_id=U[45])
    earlier_target = response_outcome(1, target_id=U[28], responder_id=U[46])
    calls: list[str] = []
    service = coordinator(
        (outcome(contexts[0]), timeout_outcome(contexts[1])),
        calls,
        peer_outcomes=(outcome(peers[0]),),
        response_outcomes=(later_target, earlier_target),
    )

    result = await service.run(
        round_command(
            contexts,
            peers=peers,
            responses=(later_target.context, earlier_target.context),
        )
    )
    assert earlier_target.execution is not None
    assert later_target.execution is not None

    assert calls == [
        "critic-dispatch",
        "peer-dispatch",
        f"critique:{contexts[0].agent_definition_id}",
        f"ledger:TURN_TIMEOUT:{contexts[1].agent_definition_id}",
        f"critique:{peers[0].agent_definition_id}",
        "response-dispatch",
        (
            f"response:{earlier_target.execution.proposal.target_artifact_id}:"
            f"{earlier_target.execution.proposal.responding_definition_id}"
        ),
        (
            f"response:{later_target.execution.proposal.target_artifact_id}:"
            f"{later_target.execution.proposal.responding_definition_id}"
        ),
        "handoff",
    ]
    assert len(result.critique_writes) == 2
    assert result.peer_outcomes == (outcome(peers[0]),)
    assert result.response_outcomes == (later_target, earlier_target)
    assert result.timeout_events[0].event_type == "TURN_TIMEOUT"
    assert result.timeout_events[0].payload["phase"] == "CRITIQUE"
    assert tuple(value.response_id for value in result.response_results) == (
        earlier_target.execution.proposal.response_id,
        later_target.execution.proposal.response_id,
    )


@req("FR-205", "FR-501", "FR-503", "FR-504")
async def test_all_dispatch_outputs_validate_before_first_commit_side_effect() -> None:
    contexts = (critic_context(0), critic_context(1))
    calls: list[str] = []
    service = coordinator((outcome(contexts[0]), outcome(contexts[1], attributed=False)), calls)

    with pytest.raises(ValueError, match="full provider attribution"):
        await service.run(round_command(contexts))

    assert calls == ["critic-dispatch"]


@req("FR-205", "FR-501", "FR-503", "FR-504")
async def test_all_peer_outputs_validate_before_any_critique_commit() -> None:
    context = critic_context(0)
    peers = (
        critic_context(1, role="domain_expert"),
        critic_context(2, role="domain_expert"),
    )
    candidate = critique_bundle(peers[1])
    invalid_proposal = candidate.artifacts[0].model_copy(update={"kind": ArtifactKind.CLAIM})
    invalid = candidate.model_copy(update={"artifacts": (invalid_proposal,)})
    calls: list[str] = []
    service = coordinator(
        (outcome(context),),
        calls,
        peer_outcomes=(outcome(peers[0]), outcome(peers[1], bundle=invalid)),
    )

    with pytest.raises(ValueError, match="only CRITIQUE proposals"):
        await service.run(round_command((context,), peers=peers))

    assert calls == ["critic-dispatch", "peer-dispatch"]


@req("FR-205", "FR-501", "FR-503", "FR-504")
async def test_exact_duplicate_peer_attacks_fail_before_any_critique_commit() -> None:
    context = critic_context(0)
    peer = critic_context(1, role="domain_expert")
    candidate = critique_bundle(peer)
    duplicate = candidate.model_copy(update={"artifacts": candidate.artifacts * 2})
    calls: list[str] = []
    service = coordinator(
        (outcome(context),),
        calls,
        peer_outcomes=(outcome(peer, bundle=duplicate),),
    )

    with pytest.raises(ValueError, match="exact duplicate attack"):
        await service.run(round_command((context,), peers=(peer,)))

    assert calls == ["critic-dispatch", "peer-dispatch"]


@req("FR-205", "FR-501", "FR-503", "FR-504")
@pytest.mark.parametrize(
    ("duplicate", "message"),
    [
        ("response", "response IDs must be unique"),
        ("critique", "respond to each Critique head only once"),
    ],
)
async def test_duplicate_response_outputs_fail_before_first_response_commit(
    duplicate: str, message: str
) -> None:
    context = critic_context(0)
    first = response_outcome(
        0,
        target_id=U[28],
        responder_id=U[45],
        response_id=U[80],
        critique_id=U[50],
    )
    second = response_outcome(
        1,
        target_id=U[29],
        responder_id=U[46],
        response_id=U[80] if duplicate == "response" else U[81],
        critique_id=U[51] if duplicate == "response" else U[50],
    )
    calls: list[str] = []
    service = coordinator((outcome(context),), calls, response_outcomes=(first, second))

    with pytest.raises(ValueError, match=message):
        await service.run(round_command((context,), responses=(first.context, second.context)))

    assert calls == [
        "critic-dispatch",
        f"critique:{context.agent_definition_id}",
        "response-dispatch",
    ]


@req("FR-205", "FR-501", "FR-503", "FR-504")
async def test_all_response_outputs_validate_before_first_response_commit() -> None:
    context = critic_context(0)
    first = response_outcome(0, target_id=U[28], responder_id=U[45])
    second = response_outcome(1, target_id=U[29], responder_id=U[46])
    assert second.execution is not None
    invalid_proposal = second.execution.proposal.model_copy(update={"session_id": U[4]})
    invalid_execution = second.execution.model_copy(update={"proposal": invalid_proposal})
    invalid = second.model_copy(update={"execution": invalid_execution})
    calls: list[str] = []
    service = coordinator((outcome(context),), calls, response_outcomes=(first, invalid))

    with pytest.raises(ValueError, match="authorized reasoning context"):
        await service.run(round_command((context,), responses=(first.context, second.context)))

    assert calls == [
        "critic-dispatch",
        f"critique:{context.agent_definition_id}",
        "response-dispatch",
    ]


@req("FR-205", "FR-501", "FR-503", "FR-504")
async def test_metadata_free_deterministic_response_output_is_preserved() -> None:
    context = critic_context(0)
    response = response_outcome(0, target_id=U[28], responder_id=U[45], attributed=False)
    calls: list[str] = []
    service = coordinator((outcome(context),), calls, response_outcomes=(response,))

    result = await service.run(round_command((context,), responses=(response.context,)))

    assert calls == [
        "critic-dispatch",
        f"critique:{context.agent_definition_id}",
        "response-dispatch",
        f"response:{U[28]}:{U[45]}",
        "handoff",
    ]
    assert result.response_outcomes == (response,)
    assert response.execution is not None
    assert response.execution.provider is None


@req("FR-205", "FR-501", "FR-503", "FR-504")
async def test_timeouts_in_each_phase_append_ordered_abstention_events() -> None:
    context = critic_context(0)
    peer = critic_context(1, role="domain_expert")
    response = response_outcome(0, target_id=U[28], responder_id=U[45])
    calls: list[str] = []
    service = coordinator(
        (timeout_outcome(context),),
        calls,
        peer_outcomes=(timeout_outcome(peer),),
        response_outcomes=(response_timeout_outcome(response.context),),
    )

    result = await service.run(
        round_command((context,), peers=(peer,), responses=(response.context,))
    )

    assert calls == [
        "critic-dispatch",
        "peer-dispatch",
        f"ledger:TURN_TIMEOUT:{context.agent_definition_id}",
        f"ledger:TURN_TIMEOUT:{peer.agent_definition_id}",
        "response-dispatch",
        f"ledger:TURN_TIMEOUT:{response.context.agent_definition_id}",
        "handoff",
    ]
    assert tuple(event.id for event in result.timeout_events) == (U[35], U[41], U[44])
    assert tuple(event.payload["phase"] for event in result.timeout_events) == (
        ReasoningPhase.CRITIQUE.value,
        ReasoningPhase.CRITIQUE.value,
        ReasoningPhase.REVISE.value,
    )
    assert all(
        event.payload["reason"] == "Agent turn exceeded its coordinator deadline"
        for event in result.timeout_events
    )
    assert result.response_results == ()


@req("FR-205", "FR-501", "FR-503", "FR-504")
async def test_unsupported_claim_is_reported_as_evidence_gap_not_deprecated_alias() -> None:
    context = critic_context(0)
    calls: list[str] = []
    service = coordinator(
        (outcome(context, bundle=critique_bundle(context, critique_type="EVIDENCE_GAP")),),
        calls,
    )

    await service.run(round_command((context,)))

    assert context.visible_artifacts[0].kind == ArtifactKind.CLAIM.value
    assert calls == [
        "critic-dispatch",
        f"critique:{context.agent_definition_id}",
        "handoff",
    ]


@req("FR-205", "FR-501", "FR-503", "FR-504")
async def test_deprecated_unsupported_claim_alias_fails_before_critique_commit() -> None:
    context = critic_context(0)
    candidate = critique_bundle(context)
    proposal = candidate.artifacts[0]
    malformed_payload = {**proposal.payload, "critique_type": "UNSUPPORTED_CLAIM"}
    malformed_proposal = ArtifactProposal.model_construct(
        op="propose",
        kind=ArtifactKind.CRITIQUE,
        payload=malformed_payload,
        evidence_disposition=None,
        confidence=None,
    )
    malformed_bundle = candidate.model_copy(update={"artifacts": (malformed_proposal,)})
    calls: list[str] = []
    service = coordinator((outcome(context, bundle=malformed_bundle),), calls)

    with pytest.raises(ValidationError, match="critique_type"):
        await service.run(round_command((context,)))

    assert calls == ["critic-dispatch"]


@req("FR-205", "FR-501", "FR-503", "FR-504")
@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"session_id": U[4]}, "another session round"),
        ({"timeout_event_ids": (U[35],)}, "must align"),
        ({"inactivity_event_ids": (U[30], U[32])}, "event IDs must be unique"),
    ],
)
def test_round_batch_rejects_invalid_global_pins_before_service_invocation(
    changes: dict[str, Any], message: str
) -> None:
    contexts = (critic_context(0), critic_context(1))
    with pytest.raises(ValidationError, match=message):
        round_command(contexts, **changes)


def handoff_entry(index: int, *, sequence: int) -> CritiqueExplanationEntry:
    return CritiqueExplanationEntry(
        critique_id=U[50 + index],
        logical_id=U[55 + index],
        version=1,
        target_artifact_id=U[20 + index],
        critique_type=CritiqueType.EVIDENCE_GAP,
        severity=Severity.HIGH,
        resolution=Resolution.OPEN,
        creation_ledger_seq=sequence,
    )


@req("FR-205", "FR-501", "FR-503", "FR-504")
def test_handoff_contract_requires_explicit_empty_reason_and_stable_unique_heads() -> None:
    with pytest.raises(ValidationError, match="entries or exactly one empty reason"):
        CritiqueExplanationHandoff(workspace_id=U[0], session_id=U[1], entries=())
    with pytest.raises(ValidationError, match="stable ledger/id order"):
        CritiqueExplanationHandoff(
            workspace_id=U[0],
            session_id=U[1],
            entries=(handoff_entry(0, sequence=2), handoff_entry(1, sequence=1)),
        )
    duplicate = handoff_entry(1, sequence=2).model_copy(
        update={"logical_id": handoff_entry(0, sequence=1).logical_id}
    )
    with pytest.raises(ValidationError, match="more than one head"):
        CritiqueExplanationHandoff(
            workspace_id=U[0],
            session_id=U[1],
            entries=(handoff_entry(0, sequence=1), duplicate),
        )


@req("FR-205", "FR-501", "FR-503", "FR-504")
def test_handoff_entry_preserves_resolved_disputed_and_unresolved_response_metadata() -> None:
    disputed = CritiqueExplanationEntry(
        critique_id=U[50],
        logical_id=U[55],
        version=2,
        target_artifact_id=U[20],
        critique_type=CritiqueType.LOGICAL_FALLACY,
        severity=Severity.BLOCKING,
        resolution=Resolution.DISPUTED,
        response_disposition=CritiqueResponseDisposition.REJECT_WITH_JUSTIFICATION,
        warrant_artifact_ids=(U[21],),
        creation_ledger_seq=4,
    )
    revised = CritiqueExplanationEntry(
        critique_id=U[51],
        logical_id=U[56],
        version=2,
        target_artifact_id=U[22],
        critique_type=CritiqueType.EVIDENCE_GAP,
        severity=Severity.HIGH,
        resolution=Resolution.RESOLVED,
        response_disposition=CritiqueResponseDisposition.REVISE,
        replacement_target_artifact_id=U[23],
        creation_ledger_seq=5,
    )

    handoff = CritiqueExplanationHandoff(
        workspace_id=U[0], session_id=U[1], entries=(disputed, revised)
    )

    assert tuple(entry.resolution for entry in handoff.entries) == (
        Resolution.DISPUTED,
        Resolution.RESOLVED,
    )
