"""Strict proposal-only contract between an orchestrator and coordinator policy."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.domain.reasoning import FrozenModel
from app.ports.agent_runtime import ReasoningPhase

__all__ = [
    "CoordinatorProposalContext",
    "OrchestratorAction",
    "OrchestratorDecision",
    "OrchestratorDecisionStatus",
    "OrchestratorPolicyRule",
    "OrchestratorPolicyVersion",
    "OrchestratorProposal",
]


# trace: FR-206
class OrchestratorAction(StrEnum):
    """Closed recommendation set. No member grants mutation or transition authority."""

    DECOMPOSE = "DECOMPOSE"
    ROUTE = "ROUTE"
    ADVANCE_PHASE = "ADVANCE_PHASE"


class OrchestratorPolicyVersion(StrEnum):
    V1 = "orchestrator-coordinator-policy@1"


class OrchestratorPolicyRule(StrEnum):
    ACCEPTED = "ACCEPTED"
    PINNED_IDENTITY_MISMATCH = "PINNED_IDENTITY_MISMATCH"
    PHASE_MISMATCH = "PHASE_MISMATCH"
    ROUTING_TARGET_INELIGIBLE = "ROUTING_TARGET_INELIGIBLE"
    PHASE_ORDER_VIOLATION = "PHASE_ORDER_VIOLATION"


class OrchestratorDecisionStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class OrchestratorProposal(FrozenModel):
    """One inert orchestrator recommendation; coordinator policy decides what may follow."""

    protocol_version: Literal["1.0"]
    kind: Literal["orchestrator_proposal"]
    proposal_id: UUID
    workspace_id: UUID
    session_id: UUID
    orchestrator_definition_id: UUID
    orchestrator_definition_version: int = Field(gt=0)
    turn_id: UUID
    correlation_id: UUID
    causation_id: UUID
    round: int = Field(ge=1)
    action: OrchestratorAction
    phase: ReasoningPhase
    target_agent_definition_ids: tuple[UUID, ...] = ()
    rationale: str = Field(min_length=1)
    schema_version: int = 1

    @field_validator("rationale")
    @classmethod
    def rationale_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("orchestrator proposal rationale must not be blank")
        return value

    @model_validator(mode="after")
    def action_shape(self) -> OrchestratorProposal:
        if self.schema_version != 1:
            raise ValueError("unsupported OrchestratorProposal schema_version")
        targets = self.target_agent_definition_ids
        if len(set(targets)) != len(targets):
            raise ValueError("orchestrator routing targets must be unique")
        if self.action is OrchestratorAction.ROUTE and not targets:
            raise ValueError("ROUTE proposal requires at least one target agent")
        if self.action is not OrchestratorAction.ROUTE and targets:
            raise ValueError("only ROUTE proposal may contain target agents")
        if (
            self.action is OrchestratorAction.DECOMPOSE
            and self.phase is not ReasoningPhase.DECOMPOSE
        ):
            raise ValueError("DECOMPOSE proposal must name DECOMPOSE phase")
        return self


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("decided_at must include an RFC 3339 offset")
    return value.astimezone(UTC)


class CoordinatorProposalContext(FrozenModel):
    """Coordinator-owned pins and routing eligibility used by deterministic policy."""

    workspace_id: UUID
    session_id: UUID
    policy_actor_id: UUID
    orchestrator_definition_id: UUID
    orchestrator_definition_version: int = Field(gt=0)
    turn_id: UUID
    correlation_id: UUID
    causation_id: UUID
    round: int = Field(ge=1)
    current_phase: ReasoningPhase
    eligible_agent_definition_ids: tuple[UUID, ...] = ()
    decided_at: datetime
    policy_version: OrchestratorPolicyVersion = OrchestratorPolicyVersion.V1
    schema_version: int = 1

    _decided_at_utc = field_validator("decided_at")(_aware_utc)

    @model_validator(mode="after")
    def context_shape(self) -> CoordinatorProposalContext:
        if self.schema_version != 1:
            raise ValueError("unsupported CoordinatorProposalContext schema_version")
        if len(set(self.eligible_agent_definition_ids)) != len(self.eligible_agent_definition_ids):
            raise ValueError("eligible routing agents must be unique")
        return self


class OrchestratorDecision(FrozenModel):
    """Recorded policy outcome. Acceptance is authorization data, not an applied mutation."""

    proposal_id: UUID
    event_id: UUID
    status: OrchestratorDecisionStatus
    rule: OrchestratorPolicyRule
    policy_version: OrchestratorPolicyVersion
    schema_version: int = 1

    @model_validator(mode="after")
    def decision_shape(self) -> OrchestratorDecision:
        if self.schema_version != 1:
            raise ValueError("unsupported OrchestratorDecision schema_version")
        accepted = self.status is OrchestratorDecisionStatus.ACCEPTED
        if accepted != (self.rule is OrchestratorPolicyRule.ACCEPTED):
            raise ValueError("decision status and policy rule are inconsistent")
        return self
