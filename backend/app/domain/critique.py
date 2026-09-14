"""Strict Phase 7 contracts for Critic assignments, output, and responses."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.domain.agent_activity import EvidenceDisposition, ProposalBundle
from app.domain.reasoning import (
    ArtifactKind,
    Confidence,
    CritiquePayload,
    FrozenModel,
    Resolution,
    _frozen_json,
    content_hash,
    validate_artifact_payload,
)

__all__ = [
    "ArtifactRevisionProposal",
    "CritiqueAssignment",
    "CritiqueResponseDisposition",
    "CritiqueResponseProposal",
    "CritiqueResponseRequest",
    "CritiqueResponseResult",
    "CritiqueResponseResultStatus",
    "CritiqueResponseStore",
    "critique_response_request_hash",
    "validate_critic_bundle",
]


# trace: FR-501, FR-502, FR-503
class CritiqueResponseDisposition(StrEnum):
    """The exact response vocabulary required by FR-503."""

    ACCEPT = "ACCEPT"
    PARTIALLY_ACCEPT = "PARTIALLY_ACCEPT"
    REJECT_WITH_JUSTIFICATION = "REJECT_WITH_JUSTIFICATION"
    REVISE = "REVISE"
    REQUEST_EVIDENCE = "REQUEST_EVIDENCE"
    REQUEST_SIMULATION = "REQUEST_SIMULATION"
    ABSTAIN = "ABSTAIN"


class CritiqueResponseResultStatus(StrEnum):
    """Durable terminal outcome of one accepted response request."""

    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    DISPUTED = "DISPUTED"
    REVISED = "REVISED"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    SIMULATION_DEFERRED = "SIMULATION_DEFERRED"
    ABSTAINED = "ABSTAINED"


class ArtifactRevisionProposal(FrozenModel):
    """Replacement content for an existing artifact; never creation authority."""

    op: Literal["propose"]
    kind: ArtifactKind
    payload: dict[str, Any]
    evidence_disposition: EvidenceDisposition | None = None
    confidence: Confidence | None = None

    @model_validator(mode="after")
    def valid_revision_content(self) -> ArtifactRevisionProposal:
        validated = validate_artifact_payload(self.kind, self.payload)
        if self.kind is ArtifactKind.POSITION:
            evidence_ids = getattr(validated, "evidence_ids", ())
            if self.evidence_disposition is EvidenceDisposition.CITED and not evidence_ids:
                raise ValueError("CITED position must declare at least one evidence ID")
            if self.evidence_disposition is EvidenceDisposition.NO_EVIDENCE and evidence_ids:
                raise ValueError("NO_EVIDENCE position must not declare evidence IDs")
            if self.evidence_disposition not in {
                EvidenceDisposition.CITED,
                EvidenceDisposition.NO_EVIDENCE,
            }:
                raise ValueError("POSITION revision requires an explicit evidence disposition")
            if self.confidence is None:
                raise ValueError("POSITION revision requires confidence")
        elif self.evidence_disposition is not None:
            raise ValueError("evidence disposition is only valid for POSITION")
        object.__setattr__(self, "payload", validated.model_dump(mode="json"))
        return self


class CritiqueAssignment(FrozenModel):
    """Coordinator-owned target allowlist for one Critic turn."""

    protocol_version: Literal["1.0"]
    kind: Literal["critique_assignment"]
    workspace_id: UUID
    session_id: UUID
    critic_definition_id: UUID
    critic_definition_version: int = Field(gt=0)
    turn_id: UUID
    correlation_id: UUID
    causation_id: UUID
    round: int = Field(ge=1)
    target_artifact_ids: tuple[UUID, ...]
    schema_version: int = 1

    @model_validator(mode="after")
    def assignment_shape(self) -> CritiqueAssignment:
        if self.schema_version != 1:
            raise ValueError("unsupported CritiqueAssignment schema_version")
        if not self.target_artifact_ids:
            raise ValueError("Critique assignment requires at least one target artifact")
        if len(set(self.target_artifact_ids)) != len(self.target_artifact_ids):
            raise ValueError("Critique assignment targets must be unique")
        return self


class CritiqueResponseProposal(FrozenModel):
    """Agent proposal for one coordinator-validated response to one Critique head."""

    protocol_version: Literal["1.0"]
    kind: Literal["critique_response"]
    response_id: UUID
    workspace_id: UUID
    session_id: UUID
    responding_definition_id: UUID
    responding_definition_version: int = Field(gt=0)
    turn_id: UUID
    correlation_id: UUID
    causation_id: UUID
    round: int = Field(ge=1)
    critique_id: UUID
    critique_version: int = Field(gt=0)
    target_artifact_id: UUID
    target_artifact_version: int = Field(gt=0)
    disposition: CritiqueResponseDisposition
    rationale: str = Field(min_length=1)
    remaining_issue: str | None = None
    warrant_artifact_ids: tuple[UUID, ...] = ()
    proposed_revision: ArtifactRevisionProposal | None = None
    evidence_query: str | None = None
    simulation_request_ref: str | None = None
    schema_version: int = 1

    @field_validator("rationale", "remaining_issue", "evidence_query", "simulation_request_ref")
    @classmethod
    def text_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Critique response text must not be blank")
        return value

    @model_validator(mode="after")
    def response_shape(self) -> CritiqueResponseProposal:
        if self.schema_version != 1:
            raise ValueError("unsupported CritiqueResponseProposal schema_version")
        if len(set(self.warrant_artifact_ids)) != len(self.warrant_artifact_ids):
            raise ValueError("Critique response warrants must be unique")

        supplied = {
            "remaining_issue": self.remaining_issue is not None,
            "warrant_artifact_ids": bool(self.warrant_artifact_ids),
            "proposed_revision": self.proposed_revision is not None,
            "evidence_query": self.evidence_query is not None,
            "simulation_request_ref": self.simulation_request_ref is not None,
        }
        required_by_disposition: dict[CritiqueResponseDisposition, str | None] = {
            CritiqueResponseDisposition.ACCEPT: None,
            CritiqueResponseDisposition.PARTIALLY_ACCEPT: "remaining_issue",
            CritiqueResponseDisposition.REJECT_WITH_JUSTIFICATION: "warrant_artifact_ids",
            CritiqueResponseDisposition.REVISE: "proposed_revision",
            CritiqueResponseDisposition.REQUEST_EVIDENCE: "evidence_query",
            CritiqueResponseDisposition.REQUEST_SIMULATION: "simulation_request_ref",
            CritiqueResponseDisposition.ABSTAIN: None,
        }
        required = required_by_disposition[self.disposition]
        if required is not None and not supplied[required]:
            raise ValueError(f"{self.disposition.value} requires {required}")
        unexpected = tuple(
            name for name, present in supplied.items() if present and name != required
        )
        if unexpected:
            raise ValueError(
                f"{self.disposition.value} does not permit response fields: {', '.join(unexpected)}"
            )
        return self


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an RFC 3339 offset")
    return value.astimezone(UTC)


class CritiqueResponseRequest(FrozenModel):
    """Append-only exact request identity for one coordinator response commit."""

    response_id: UUID
    workspace_id: UUID
    session_id: UUID
    turn_id: UUID
    responding_definition_id: UUID
    responding_definition_version: int = Field(gt=0)
    critique_id: UUID
    critique_version: int = Field(gt=0)
    target_artifact_id: UUID
    target_artifact_version: int = Field(gt=0)
    disposition: CritiqueResponseDisposition
    request_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    request_payload: dict[str, Any]
    execution_metadata: dict[str, Any]
    requested_at: datetime
    schema_version: int = 1

    _requested_at_utc = field_validator("requested_at")(_aware_utc)
    _payload_json = field_validator("request_payload", "execution_metadata")(_frozen_json)

    @model_validator(mode="after")
    def request_shape(self) -> CritiqueResponseRequest:
        if self.schema_version != 1:
            raise ValueError("unsupported CritiqueResponseRequest schema_version")
        proposal = CritiqueResponseProposal.model_validate_json(
            json.dumps(self.request_payload, default=str)
        )
        pins = (
            proposal.response_id,
            proposal.workspace_id,
            proposal.session_id,
            proposal.turn_id,
            proposal.responding_definition_id,
            proposal.responding_definition_version,
            proposal.critique_id,
            proposal.critique_version,
            proposal.target_artifact_id,
            proposal.target_artifact_version,
            proposal.disposition,
        )
        expected = (
            self.response_id,
            self.workspace_id,
            self.session_id,
            self.turn_id,
            self.responding_definition_id,
            self.responding_definition_version,
            self.critique_id,
            self.critique_version,
            self.target_artifact_id,
            self.target_artifact_version,
            self.disposition,
        )
        if pins != expected:
            raise ValueError("response request payload does not match its indexed identity")
        required_attribution = {
            "agent_definition_id",
            "agent_definition_version",
            "strategy_name",
            "strategy_version",
            "provider",
            "model",
            "prompt_ref",
            "prompt_hash",
            "round",
            "phase",
            "turn_id",
            "correlation_id",
            "causation_id",
            "raw_artifact_ref",
            "context_hash",
            "response_hash",
            "input_tokens",
            "output_tokens",
            "cost_usd",
            "committed_at",
        }
        if set(self.execution_metadata) != required_attribution:
            raise ValueError("response execution attribution is incomplete")
        if self.request_hash != critique_response_request_hash(
            self.request_payload, self.execution_metadata, self.requested_at
        ):
            raise ValueError("response request hash does not match its immutable content")
        return self


class CritiqueResponseResult(FrozenModel):
    """Append-only committed effects for one exact response request."""

    response_id: UUID
    workspace_id: UUID
    session_id: UUID
    status: CritiqueResponseResultStatus
    disposition: CritiqueResponseDisposition
    resolution: Resolution
    critique_revision_id: UUID
    critique_revision_version: int = Field(gt=1)
    target_revision_id: UUID | None = None
    target_revision_version: int | None = Field(default=None, gt=1)
    response_event_id: UUID
    committed_at: datetime
    schema_version: int = 1

    _committed_at_utc = field_validator("committed_at")(_aware_utc)

    @model_validator(mode="after")
    def result_shape(self) -> CritiqueResponseResult:
        if self.schema_version != 1:
            raise ValueError("unsupported CritiqueResponseResult schema_version")
        revised = self.disposition is CritiqueResponseDisposition.REVISE
        if revised != (self.target_revision_id is not None):
            raise ValueError("only REVISE results carry a target revision")
        if revised != (self.target_revision_version is not None):
            raise ValueError("target revision identity and version must be supplied together")
        expected = {
            CritiqueResponseDisposition.ACCEPT: (
                CritiqueResponseResultStatus.RESOLVED,
                Resolution.RESOLVED,
            ),
            CritiqueResponseDisposition.PARTIALLY_ACCEPT: (
                CritiqueResponseResultStatus.UNRESOLVED,
                Resolution.UNRESOLVED,
            ),
            CritiqueResponseDisposition.REJECT_WITH_JUSTIFICATION: (
                CritiqueResponseResultStatus.DISPUTED,
                Resolution.DISPUTED,
            ),
            CritiqueResponseDisposition.REVISE: (
                CritiqueResponseResultStatus.REVISED,
                Resolution.RESOLVED,
            ),
            CritiqueResponseDisposition.REQUEST_EVIDENCE: (
                CritiqueResponseResultStatus.EVIDENCE_REQUESTED,
                Resolution.UNRESOLVED,
            ),
            CritiqueResponseDisposition.REQUEST_SIMULATION: (
                CritiqueResponseResultStatus.SIMULATION_DEFERRED,
                Resolution.UNRESOLVED,
            ),
            CritiqueResponseDisposition.ABSTAIN: (
                CritiqueResponseResultStatus.ABSTAINED,
                Resolution.UNRESOLVED,
            ),
        }
        if (self.status, self.resolution) != expected[self.disposition]:
            raise ValueError("response result status and resolution do not match disposition")
        return self


@runtime_checkable
class CritiqueResponseStore(Protocol):
    """Caller-transaction-scoped append-only response persistence boundary."""

    async def lock_response(
        self, workspace_id: UUID, session_id: UUID, response_id: UUID
    ) -> None: ...

    async def get_request(
        self, workspace_id: UUID, session_id: UUID, response_id: UUID
    ) -> CritiqueResponseRequest | None: ...

    async def get_result(
        self, workspace_id: UUID, session_id: UUID, response_id: UUID
    ) -> CritiqueResponseResult | None: ...

    async def add_request(self, request: CritiqueResponseRequest) -> None: ...

    async def add_result(self, result: CritiqueResponseResult) -> None: ...


def critique_response_request_hash(
    request_payload: dict[str, Any], execution_metadata: dict[str, Any], requested_at: datetime
) -> str:
    """Hash the exact immutable response request and execution attribution."""
    return content_hash(
        {
            "execution_metadata": execution_metadata,
            "request_payload": request_payload,
            "requested_at": _aware_utc(requested_at).isoformat().replace("+00:00", "Z"),
        }
    )


def validate_critic_bundle(
    bundle: ProposalBundle, assignment: CritiqueAssignment
) -> ProposalBundle:
    """Fail closed unless a bundle is a pure set of assigned, new, open Critiques."""
    if bundle.turn_id != assignment.turn_id:
        raise ValueError("Critic bundle turn_id does not match its assignment")
    if bundle.evidence_requests or bundle.simulation_request_refs:
        raise ValueError("Critic bundle must not carry evidence or simulation requests")

    assigned = set(assignment.target_artifact_ids)
    seen: set[str] = set()
    for proposal in bundle.artifacts:
        if proposal.kind is not ArtifactKind.CRITIQUE:
            raise ValueError("Critic bundle may contain only CRITIQUE proposals")
        if proposal.evidence_disposition is not None or proposal.confidence is not None:
            raise ValueError("Critique proposals must not carry position disposition or confidence")
        payload = validate_artifact_payload(ArtifactKind.CRITIQUE, proposal.payload)
        if not isinstance(payload, CritiquePayload):
            raise TypeError("validated CRITIQUE payload has an unexpected type")
        if payload.resolution is not Resolution.OPEN:
            raise ValueError("new Critique proposals must have OPEN resolution")
        if payload.target_id not in assigned:
            raise ValueError("Critique target is not in the coordinator assignment")
        identity = payload.model_dump_json()
        if identity in seen:
            raise ValueError("Critic bundle contains an exact duplicate attack")
        seen.add(identity)
    return bundle
