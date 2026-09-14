"""Strict, versioned contracts for nondeterministic logical-agent activities."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.reasoning import (
    ArtifactKind,
    ArtifactPayload,
    Confidence,
    validate_artifact_payload,
)

__all__ = [
    "AGENT_TURN_ACTIVITY",
    "AgentActivityRunner",
    "AgentTurnInput",
    "AgentTurnPhase",
    "AgentTurnResult",
    "ArtifactProposal",
    "EvidenceDisposition",
    "ProposalBundle",
]

AGENT_TURN_ACTIVITY = "run_agent_turn"


# trace: FR-209, FR-210
class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AgentTurnPhase(StrEnum):
    ASSESS = "ASSESS"
    DECOMPOSE = "DECOMPOSE"
    ARGUE = "ARGUE"
    CRITIQUE = "CRITIQUE"
    REVISE = "REVISE"
    SCORE = "SCORE"


class EvidenceDisposition(StrEnum):
    """Closed evidence state for a proposed position; never an evidence identifier."""

    CITED = "CITED"
    NO_EVIDENCE = "NO_EVIDENCE"


class AgentTurnInput(_Contract):
    """Complete activity input. Workflow code supplies IDs; activity resolves durable config."""

    protocol_version: Literal["1.0"]
    kind: Literal["turn_request"]
    workspace_id: UUID
    session_id: UUID
    agent_definition_id: UUID
    agent_definition_version: int = Field(gt=0)
    agent_definition_json: str = Field(min_length=2)
    turn_id: UUID
    correlation_id: UUID
    causation_id: UUID
    round: int = Field(ge=1)
    phase: AgentTurnPhase
    problem_statement: str = Field(min_length=1)
    canonicalizer_version: str = Field(default="canonicalizer@1", min_length=1)
    objective_summaries: tuple[str, ...] = ()
    constraint_summaries: tuple[str, ...] = ()
    visible_artifact_ids: tuple[UUID, ...] = ()
    visible_artifact_json: tuple[str, ...]
    authorized_knowledge_json: str | None
    sealed: bool
    budget_remaining_tokens: int = Field(gt=0)
    timeout_s: float = Field(gt=0)
    schema_version: int = 1

    @field_validator(
        "problem_statement", "canonicalizer_version", "objective_summaries", "constraint_summaries"
    )
    @classmethod
    def not_blank(cls, value: str | tuple[str, ...]) -> str | tuple[str, ...]:
        values = (value,) if isinstance(value, str) else value
        if any(not item.strip() for item in values):
            raise ValueError("text values must not be blank")
        return value

    @model_validator(mode="after")
    def protocol_invariants(self) -> AgentTurnInput:
        if self.schema_version != 1:
            raise ValueError("unsupported AgentTurnInput schema_version")
        if len(self.visible_artifact_json) != len(self.visible_artifact_ids):
            raise ValueError("visible artifact IDs must match hydrated artifact snapshots")
        if (
            self.round == 1
            and self.phase is AgentTurnPhase.ASSESS
            and (not self.sealed or self.visible_artifact_json)
        ):
            raise ValueError("round 1 ASSESS must be sealed from other agents")
        return self


class ArtifactProposal(_Contract):
    """Model-proposed artifact content. Coordinator allocates envelope identity and commits."""

    op: Literal["propose"]
    kind: ArtifactKind
    payload: dict[str, Any]
    evidence_disposition: EvidenceDisposition | None = None
    confidence: Confidence | None = None

    @model_validator(mode="after")
    def valid_agent_content(self) -> ArtifactProposal:
        if self.kind in {ArtifactKind.FACT, ArtifactKind.EVIDENCE}:
            raise ValueError("agents may not propose FACT or EVIDENCE directly")
        validated: ArtifactPayload = validate_artifact_payload(self.kind, self.payload)
        if self.kind is ArtifactKind.POSITION:
            evidence_ids = getattr(validated, "evidence_ids", ())
            if self.evidence_disposition is EvidenceDisposition.CITED and not evidence_ids:
                raise ValueError("CITED position must declare at least one evidence ID")
            if self.evidence_disposition is EvidenceDisposition.NO_EVIDENCE and evidence_ids:
                raise ValueError("NO_EVIDENCE position must not declare evidence IDs")
            if self.evidence_disposition is None:
                raise ValueError("POSITION requires an explicit evidence disposition")
            if self.confidence is None:
                raise ValueError("POSITION requires confidence")
        elif self.evidence_disposition is not None:
            raise ValueError("evidence disposition is only valid for POSITION")
        object.__setattr__(self, "payload", validated.model_dump(mode="json"))
        return self


class ProposalBundle(_Contract):
    protocol_version: Literal["1.0"]
    kind: Literal["proposal_bundle"]
    turn_id: UUID
    artifacts: tuple[ArtifactProposal, ...]
    evidence_requests: tuple[str, ...] = ()
    simulation_request_refs: tuple[str, ...] = ()
    self_reported_limits: tuple[str, ...] = ()

    @field_validator("evidence_requests", "simulation_request_refs", "self_reported_limits")
    @classmethod
    def entries_not_blank(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("proposal bundle entries must not be blank")
        return values


class AgentTurnResult(_Contract):
    turn_id: UUID
    agent_definition_id: UUID
    bundle: ProposalBundle
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: Decimal = Field(ge=0)
    raw_artifact_ref: str = Field(pattern=r"^.+/.+#sha256:[0-9a-f]{64}$")
    schema_version: int = 1

    @model_validator(mode="after")
    def matching_turn(self) -> AgentTurnResult:
        if self.bundle.turn_id != self.turn_id:
            raise ValueError("proposal bundle turn_id does not match activity result")
        if self.schema_version != 1:
            raise ValueError("unsupported AgentTurnResult schema_version")
        return self


@runtime_checkable
class AgentActivityRunner(Protocol):
    async def run(self, command: AgentTurnInput) -> AgentTurnResult: ...
