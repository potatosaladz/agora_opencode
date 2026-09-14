"""Deterministic coordinator validation and recording of orchestrator proposals."""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, UUID, uuid5

from app.domain.orchestrator_proposal import (
    CoordinatorProposalContext,
    OrchestratorAction,
    OrchestratorDecision,
    OrchestratorDecisionStatus,
    OrchestratorPolicyRule,
    OrchestratorProposal,
)
from app.domain.reasoning import ActorClass, content_hash
from app.domain.reasoning_ledger import LedgerAppend, ReasoningLedger
from app.ports.agent_runtime import ReasoningPhase

__all__ = ["CoordinatorOrchestratorPolicy", "orchestrator_decision_event_id"]

_PHASE_ORDER = (
    ReasoningPhase.ASSESS,
    ReasoningPhase.DECOMPOSE,
    ReasoningPhase.ARGUE,
    ReasoningPhase.CRITIQUE,
    ReasoningPhase.REVISE,
    ReasoningPhase.SCORE,
)


# trace: FR-206
def orchestrator_decision_event_id(proposal_id: UUID) -> UUID:
    """Derive one replay-stable policy event identity per proposal."""
    return uuid5(NAMESPACE_URL, f"agora:orchestrator-proposal:{proposal_id}:policy-decision")


def _proposal_hash(proposal: OrchestratorProposal) -> str:
    return content_hash(json.loads(proposal.model_dump_json()))


class CoordinatorOrchestratorPolicy:
    """Validate recommendations and append decisions without applying accepted actions."""

    def __init__(self, ledger: ReasoningLedger) -> None:
        self._ledger = ledger

    async def decide(
        self, proposal: OrchestratorProposal, context: CoordinatorProposalContext
    ) -> OrchestratorDecision:
        rule = self._evaluate(proposal, context)
        status = (
            OrchestratorDecisionStatus.ACCEPTED
            if rule is OrchestratorPolicyRule.ACCEPTED
            else OrchestratorDecisionStatus.REJECTED
        )
        event_id = orchestrator_decision_event_id(proposal.proposal_id)
        await self._ledger.append(
            LedgerAppend(
                id=event_id,
                workspace_id=context.workspace_id,
                session_id=context.session_id,
                event_type=f"ORCHESTRATOR_PROPOSAL_{status.value}",
                payload_schema_version=1,
                causation_id=context.causation_id,
                correlation_id=context.correlation_id,
                actor_class=ActorClass.POLICY,
                actor_id=context.policy_actor_id,
                round=context.round,
                payload={
                    "proposal_id": str(proposal.proposal_id),
                    "proposal_hash": _proposal_hash(proposal),
                    "proposal": proposal.model_dump(mode="json"),
                    "orchestrator_definition_id": str(proposal.orchestrator_definition_id),
                    "orchestrator_definition_version": proposal.orchestrator_definition_version,
                    "turn_id": str(proposal.turn_id),
                    "action": proposal.action.value,
                    "phase": proposal.phase.value,
                    "target_agent_definition_ids": [
                        str(value) for value in proposal.target_agent_definition_ids
                    ],
                    "rationale": proposal.rationale,
                    "status": status.value,
                    "rule": rule.value,
                    "policy_version": context.policy_version.value,
                    "applied": False,
                },
                recorded_at=context.decided_at,
            )
        )
        return OrchestratorDecision(
            proposal_id=proposal.proposal_id,
            event_id=event_id,
            status=status,
            rule=rule,
            policy_version=context.policy_version,
        )

    @staticmethod
    def _evaluate(
        proposal: OrchestratorProposal, context: CoordinatorProposalContext
    ) -> OrchestratorPolicyRule:
        proposal_pin = (
            proposal.workspace_id,
            proposal.session_id,
            proposal.orchestrator_definition_id,
            proposal.orchestrator_definition_version,
            proposal.turn_id,
            proposal.correlation_id,
            proposal.causation_id,
            proposal.round,
        )
        context_pin = (
            context.workspace_id,
            context.session_id,
            context.orchestrator_definition_id,
            context.orchestrator_definition_version,
            context.turn_id,
            context.correlation_id,
            context.causation_id,
            context.round,
        )
        if proposal_pin != context_pin:
            return OrchestratorPolicyRule.PINNED_IDENTITY_MISMATCH
        if proposal.action is OrchestratorAction.ADVANCE_PHASE:
            current_index = _PHASE_ORDER.index(context.current_phase)
            if current_index + 1 >= len(_PHASE_ORDER):
                return OrchestratorPolicyRule.PHASE_ORDER_VIOLATION
            if proposal.phase is not _PHASE_ORDER[current_index + 1]:
                return OrchestratorPolicyRule.PHASE_ORDER_VIOLATION
            return OrchestratorPolicyRule.ACCEPTED
        if proposal.phase is not context.current_phase:
            return OrchestratorPolicyRule.PHASE_MISMATCH
        if proposal.action is OrchestratorAction.ROUTE and not set(
            proposal.target_agent_definition_ids
        ).issubset(context.eligible_agent_definition_ids):
            return OrchestratorPolicyRule.ROUTING_TARGET_INELIGIBLE
        return OrchestratorPolicyRule.ACCEPTED
