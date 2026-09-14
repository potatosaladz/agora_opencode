"""T6-07 coordinator authority over inert orchestrator proposals."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.application.orchestrator_policy import (
    CoordinatorOrchestratorPolicy,
    orchestrator_decision_event_id,
)
from app.domain.orchestrator_proposal import (
    CoordinatorProposalContext,
    OrchestratorAction,
    OrchestratorDecisionStatus,
    OrchestratorPolicyRule,
    OrchestratorProposal,
)
from app.domain.reasoning import ActorClass
from app.domain.reasoning_ledger import (
    LedgerAppend,
    LedgerEvent,
    LedgerVerification,
    ledger_event_hash,
    ledger_payload_hash,
)
from app.ports.agent_runtime import ReasoningPhase
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 13))
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)


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
        return tuple(self.events[from_seq - 1 :][:limit])

    async def verify(self, workspace_id: UUID, session_id: UUID) -> LedgerVerification:
        head = self.events[-1].event_hash if self.events else "sha256:" + "0" * 64
        return LedgerVerification(valid=True, event_count=len(self.events), head_hash=head)


def context(**changes: Any) -> CoordinatorProposalContext:
    values: dict[str, Any] = {
        "workspace_id": U[0],
        "session_id": U[1],
        "policy_actor_id": U[2],
        "orchestrator_definition_id": U[3],
        "orchestrator_definition_version": 2,
        "turn_id": U[4],
        "correlation_id": U[5],
        "causation_id": U[6],
        "round": 1,
        "current_phase": ReasoningPhase.ASSESS,
        "eligible_agent_definition_ids": (U[7], U[8]),
        "decided_at": NOW,
    }
    values.update(changes)
    return CoordinatorProposalContext.model_validate(values)


def proposal(**changes: Any) -> OrchestratorProposal:
    values: dict[str, Any] = {
        "protocol_version": "1.0",
        "kind": "orchestrator_proposal",
        "proposal_id": U[9],
        "workspace_id": U[0],
        "session_id": U[1],
        "orchestrator_definition_id": U[3],
        "orchestrator_definition_version": 2,
        "turn_id": U[4],
        "correlation_id": U[5],
        "causation_id": U[6],
        "round": 1,
        "action": OrchestratorAction.ROUTE,
        "phase": ReasoningPhase.ASSESS,
        "target_agent_definition_ids": (U[7],),
        "rationale": "Route sealed assessment to one eligible expert.",
    }
    values.update(changes)
    return OrchestratorProposal.model_validate(values)


@req("FR-206")
async def test_accepts_eligible_route_and_records_policy_attribution_without_applying_it() -> None:
    ledger = _Ledger()
    candidate = proposal()

    decision = await CoordinatorOrchestratorPolicy(ledger).decide(candidate, context())

    assert decision.status is OrchestratorDecisionStatus.ACCEPTED
    assert decision.rule is OrchestratorPolicyRule.ACCEPTED
    assert decision.event_id == orchestrator_decision_event_id(candidate.proposal_id)
    assert len(ledger.events) == 1
    event = ledger.events[0]
    assert event.event_type == "ORCHESTRATOR_PROPOSAL_ACCEPTED"
    assert event.actor_class is ActorClass.POLICY
    assert event.actor_id == U[2]
    assert event.payload["orchestrator_definition_id"] == str(U[3])
    assert event.payload["target_agent_definition_ids"] == (str(U[7]),)
    assert event.payload["rationale"] == candidate.rationale
    assert event.payload["applied"] is False


@req("FR-206")
@pytest.mark.parametrize(
    ("candidate", "coordinator_context", "rule"),
    [
        (
            proposal(phase=ReasoningPhase.ARGUE),
            context(),
            OrchestratorPolicyRule.PHASE_MISMATCH,
        ),
        (
            proposal(target_agent_definition_ids=(U[10],)),
            context(),
            OrchestratorPolicyRule.ROUTING_TARGET_INELIGIBLE,
        ),
        (
            proposal(
                action=OrchestratorAction.ADVANCE_PHASE,
                phase=ReasoningPhase.ARGUE,
                target_agent_definition_ids=(),
            ),
            context(),
            OrchestratorPolicyRule.PHASE_ORDER_VIOLATION,
        ),
        (
            proposal(
                action=OrchestratorAction.ADVANCE_PHASE,
                phase=ReasoningPhase.ARGUE,
                target_agent_definition_ids=(),
            ),
            context(current_phase=ReasoningPhase.CRITIQUE),
            OrchestratorPolicyRule.PHASE_ORDER_VIOLATION,
        ),
        (
            proposal(
                action=OrchestratorAction.ADVANCE_PHASE,
                phase=ReasoningPhase.SCORE,
                target_agent_definition_ids=(),
            ),
            context(current_phase=ReasoningPhase.SCORE),
            OrchestratorPolicyRule.PHASE_ORDER_VIOLATION,
        ),
    ],
)
async def test_rejects_pin_phase_route_and_order_violations_with_exactly_one_event(
    candidate: OrchestratorProposal,
    coordinator_context: CoordinatorProposalContext,
    rule: OrchestratorPolicyRule,
) -> None:
    ledger = _Ledger()

    decision = await CoordinatorOrchestratorPolicy(ledger).decide(candidate, coordinator_context)

    assert decision.status is OrchestratorDecisionStatus.REJECTED
    assert decision.rule is rule
    assert len(ledger.events) == 1
    assert ledger.events[0].event_type == "ORCHESTRATOR_PROPOSAL_REJECTED"
    assert ledger.events[0].payload["rule"] == rule.value
    expected_proposal = candidate.model_dump(mode="json")
    expected_proposal["target_agent_definition_ids"] = tuple(
        expected_proposal["target_agent_definition_ids"]
    )
    assert ledger.events[0].payload["proposal"] == expected_proposal


@req("FR-206")
@pytest.mark.parametrize(
    "pin_change",
    [
        {"workspace_id": U[10]},
        {"session_id": U[10]},
        {"orchestrator_definition_id": U[10]},
        {"orchestrator_definition_version": 3},
        {"turn_id": U[10]},
        {"correlation_id": U[10]},
        {"causation_id": U[10]},
        {"round": 2},
    ],
)
async def test_rejects_every_orchestrator_supplied_identity_mismatch(
    pin_change: dict[str, Any],
) -> None:
    ledger = _Ledger()

    decision = await CoordinatorOrchestratorPolicy(ledger).decide(proposal(**pin_change), context())

    assert decision.rule is OrchestratorPolicyRule.PINNED_IDENTITY_MISMATCH
    assert ledger.events[0].actor_class is ActorClass.POLICY


@req("FR-206")
@pytest.mark.parametrize(
    ("current_phase", "next_phase"),
    [
        (ReasoningPhase.ASSESS, ReasoningPhase.DECOMPOSE),
        (ReasoningPhase.DECOMPOSE, ReasoningPhase.ARGUE),
        (ReasoningPhase.ARGUE, ReasoningPhase.CRITIQUE),
        (ReasoningPhase.CRITIQUE, ReasoningPhase.REVISE),
        (ReasoningPhase.REVISE, ReasoningPhase.SCORE),
    ],
)
async def test_accepts_every_immediate_phase_advance(
    current_phase: ReasoningPhase, next_phase: ReasoningPhase
) -> None:
    candidate = proposal(
        action=OrchestratorAction.ADVANCE_PHASE,
        phase=next_phase,
        target_agent_definition_ids=(),
    )
    decision = await CoordinatorOrchestratorPolicy(_Ledger()).decide(
        candidate, context(current_phase=current_phase)
    )
    assert decision.status is OrchestratorDecisionStatus.ACCEPTED


@req("FR-206")
async def test_accepts_proposal_only_decomposition_without_replacing_t6_02() -> None:
    candidate = proposal(
        action=OrchestratorAction.DECOMPOSE,
        phase=ReasoningPhase.DECOMPOSE,
        target_agent_definition_ids=(),
    )

    decision = await CoordinatorOrchestratorPolicy(_Ledger()).decide(
        candidate, context(current_phase=ReasoningPhase.DECOMPOSE)
    )

    assert decision.status is OrchestratorDecisionStatus.ACCEPTED
    assert not hasattr(candidate, "artifacts")


@req("FR-206")
def test_contract_is_frozen_strict_and_has_no_mutation_authority() -> None:
    candidate = proposal()
    with pytest.raises(ValidationError, match="frozen"):
        candidate.action = OrchestratorAction.ADVANCE_PHASE  # type: ignore[misc]
    with pytest.raises(ValidationError, match="extra_forbidden"):
        OrchestratorProposal.model_validate(
            {**candidate.model_dump(), "state_transition": "COMPLETED"}
        )
    with pytest.raises(ValidationError, match="Input should be"):
        OrchestratorProposal.model_validate({**candidate.model_dump(), "action": "MUTATE_STATE"})


@req("FR-206")
async def test_exact_replay_returns_stable_decision_and_single_append_only_event() -> None:
    ledger = _Ledger()
    service = CoordinatorOrchestratorPolicy(ledger)
    candidate, coordinator_context = proposal(), context()

    first = await service.decide(candidate, coordinator_context)
    replay = await service.decide(candidate, coordinator_context)

    assert replay == first
    assert len(ledger.events) == 1
    assert ledger.events[0].id == orchestrator_decision_event_id(candidate.proposal_id)
