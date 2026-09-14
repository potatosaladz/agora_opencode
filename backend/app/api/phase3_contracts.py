"""Strict request contracts and response projection for the Phase 3 HTTP surface."""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from app.common.ids import parse_id, public_id
from app.domain.reasoning import (
    ArtifactKind,
    ClaimPayload,
    GraphEdgeType,
    ProvenanceOrigin,
    ReasoningArtifact,
    SourceReference,
    validate_artifact_payload,
)
from app.domain.session_binding import DraftSessionBinding, SessionBudget
from app.domain.session_control import HumanDirectiveKind
from app.domain.session_lifecycle import SessionLifecycle
from app.ports.auth import VerifiedPrincipal, WorkspaceRole

__all__ = [
    "ArtifactCreate",
    "ArtifactRevisionCreate",
    "ArtifactWithdrawalCreate",
    "HumanInputCreate",
    "SessionControlCreate",
    "SessionCreate",
    "SourceRetractionCreate",
    "artifact_response",
    "decode_artifact_payload",
    "session_response",
]


_SOURCE_REFERENCES_ADAPTER = TypeAdapter(tuple[SourceReference, ...])
_SESSION_BUDGET_ADAPTER = TypeAdapter(SessionBudget)


# trace: FR-103, FR-301, FR-305
class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRetractionCreate(_StrictRequest):
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value


class ParentRelationshipInput(_StrictRequest):
    edge_type: GraphEdgeType
    target_artifact_id: str

    @field_validator("target_artifact_id")
    @classmethod
    def valid_target(cls, value: str) -> str:
        parse_id("artifact", value)
        return value


class ConfidenceInput(_StrictRequest):
    kind: str = Field(min_length=1)
    value: str = Field(pattern=r"^(?:-?0(?:\.0+)?|0\.\d+|1(?:\.0+)?)$")
    meaning: str = Field(min_length=1)
    basis_artifact_ids: tuple[str, ...]

    @field_validator("kind", "meaning")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("basis_artifact_ids")
    @classmethod
    def valid_basis(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            parse_id("artifact", value)
        return values


class ProvenanceInput(_StrictRequest):
    origin: ProvenanceOrigin
    reference: str = Field(min_length=1)

    @field_validator("reference")
    @classmethod
    def reference_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reference must not be blank")
        return value


class ArtifactCreate(_StrictRequest):
    kind: ArtifactKind
    payload: dict[str, Any]
    provenance: ProvenanceInput
    source_references: tuple[SourceReference, ...]
    parent_relationships: tuple[ParentRelationshipInput, ...]
    confidence: ConfidenceInput | None = None
    metadata: dict[str, Any]

    @field_validator("source_references", mode="before")
    @classmethod
    def decode_source_references(cls, value: Any) -> tuple[SourceReference, ...]:
        return _SOURCE_REFERENCES_ADAPTER.validate_json(json.dumps(value, default=str))


class ArtifactRevisionCreate(_StrictRequest):
    payload: dict[str, Any]
    provenance: ProvenanceInput
    source_references: tuple[SourceReference, ...]
    parent_relationships: tuple[ParentRelationshipInput, ...]
    confidence: ConfidenceInput | None = None
    metadata: dict[str, Any]
    reason: str = Field(min_length=1)

    @field_validator("source_references", mode="before")
    @classmethod
    def decode_source_references(cls, value: Any) -> tuple[SourceReference, ...]:
        return _SOURCE_REFERENCES_ADAPTER.validate_json(json.dumps(value, default=str))

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value


class ArtifactWithdrawalCreate(_StrictRequest):
    reason: str = Field(min_length=1)
    warrant_artifact_ids: tuple[str, ...]

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value

    @field_validator("warrant_artifact_ids")
    @classmethod
    def valid_warrants(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("at least one warrant artifact id is required")
        for value in values:
            parse_id("artifact", value)
        if len(values) != len(set(values)):
            raise ValueError("warrant artifact ids must be unique")
        return values


class SessionControlCreate(_StrictRequest):
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value


class HumanInputCreate(SessionControlCreate):
    kind: HumanDirectiveKind
    instruction: str = Field(min_length=1, max_length=10_000)
    artifact_ids: tuple[str, ...] = ()

    @field_validator("instruction")
    @classmethod
    def instruction_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("instruction must not be blank")
        return value

    @field_validator("artifact_ids")
    @classmethod
    def valid_artifact_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            parse_id("artifact", value)
        if len(values) != len(set(values)):
            raise ValueError("artifact_ids must be unique")
        return values


class SessionCreate(_StrictRequest):
    problem_statement: str = Field(min_length=1)
    agent_definition_ids: tuple[str, ...]
    objectives: tuple[ArtifactCreate, ...]
    constraints: tuple[ArtifactCreate, ...]
    budget: SessionBudget

    @field_validator("budget", mode="before")
    @classmethod
    def decode_budget(cls, value: Any) -> SessionBudget:
        return _SESSION_BUDGET_ADAPTER.validate_json(json.dumps(value, default=str))

    @field_validator("problem_statement")
    @classmethod
    def problem_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("problem_statement must not be blank")
        return value

    @field_validator("agent_definition_ids")
    @classmethod
    def valid_agents(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("at least one agent definition id is required")
        for value in values:
            parse_id("agent", value)
        if len(values) != len(set(values)):
            raise ValueError("agent definition ids must be unique")
        return values

    @field_validator("objectives")
    @classmethod
    def objective_kinds(cls, values: tuple[ArtifactCreate, ...]) -> tuple[ArtifactCreate, ...]:
        if not values:
            raise ValueError("at least one objective is required")
        if any(value.kind is not ArtifactKind.OBJECTIVE for value in values):
            raise ValueError("objectives must have kind OBJECTIVE")
        return values

    @field_validator("constraints")
    @classmethod
    def constraint_kinds(cls, values: tuple[ArtifactCreate, ...]) -> tuple[ArtifactCreate, ...]:
        if any(value.kind is not ArtifactKind.CONSTRAINT for value in values):
            raise ValueError("constraints must have kind CONSTRAINT")
        return values


def _permissions(role: WorkspaceRole, resource: str) -> list[str]:
    result = [f"{resource}:read"]
    if role in {WorkspaceRole.ADMIN, WorkspaceRole.RESEARCHER}:
        result.append(f"{resource}:write")
        if resource == "artifacts":
            result.append("artifacts:validate")
    return result


def _artifact_id(value: Any) -> Any:
    """Translate artifact references recursively at the public boundary."""
    if isinstance(value, UUID):
        return public_id("artifact", value)
    if isinstance(value, tuple | list):
        return [_artifact_id(item) for item in value]
    if isinstance(value, dict):
        return {key: _artifact_id(item) for key, item in value.items()}
    return value


def decode_artifact_payload(kind: ArtifactKind, value: dict[str, Any]) -> Any:
    """Decode one JSON payload through its strict kind-specific domain contract."""
    decoded = {key: _decode_payload_reference(key, item) for key, item in value.items()}
    return validate_artifact_payload(kind, decoded)


def _decode_payload_reference(key: str, value: Any) -> Any:
    if key.endswith("_id") and isinstance(value, str):
        try:
            return parse_id("artifact", value)
        except ValueError:
            return value
    if key.endswith("_ids") and isinstance(value, list | tuple):
        result: list[Any] = []
        for item in value:
            if isinstance(item, str):
                with suppress(ValueError):
                    item = parse_id("artifact", item)
            result.append(item)
        return tuple(result)
    return value


def artifact_response(
    artifact: ReasoningArtifact,
    principal: VerifiedPrincipal,
    *,
    request_id: str,
) -> dict[str, Any]:
    payload = _artifact_id(artifact.payload.model_dump(mode="python"))
    if artifact.kind is ArtifactKind.CLAIM and isinstance(artifact.payload, ClaimPayload):
        payload["unsupported"] = not artifact.payload.supporting_evidence_ids
    missing: list[str] = []
    if (
        artifact.kind in {ArtifactKind.FACT, ArtifactKind.EVIDENCE}
        and not artifact.source_references
    ):
        missing.append("source_references")
    return {
        "data": {
            "id": public_id("artifact", artifact.id),
            "kind": artifact.kind.value,
            "attributes": payload,
            "source_references": artifact.model_dump(mode="json")["source_references"],
            "parent_relationships": _artifact_id(
                artifact.model_dump(mode="python")["parent_relationships"]
            ),
            "confidence": _artifact_id(artifact.model_dump(mode="python")["confidence"]),
            "metadata": artifact.model_dump(mode="json")["metadata"],
            "content_hash": artifact.content_hash,
        },
        "meta": {
            "request_id": request_id,
            "schema_version": artifact.schema_version,
            "version": artifact.version,
            "workspace_id": public_id("workspace", artifact.workspace_id),
            "session_id": public_id("session", artifact.session_id),
            "logical_id": public_id("artifact", artifact.logical_id),
            "created_at": artifact.created_at.isoformat().replace("+00:00", "Z"),
            "updated_at": artifact.updated_at.isoformat().replace("+00:00", "Z"),
            "owner": {
                "id": public_id(
                    {
                        "HUMAN": "user",
                        "AGENT": "agent",
                        "SERVICE": "service",
                        "POLICY": "policy",
                    }[artifact.owner_actor_class.value],
                    artifact.owner_actor_id,
                ),
                "class": artifact.owner_actor_class.value,
            },
            "lifecycle_status": artifact.status.value,
            "supersedes_id": (
                public_id("artifact", artifact.supersedes_id)
                if artifact.supersedes_id is not None
                else None
            ),
            "provenance": {
                "origin": artifact.provenance.origin.value,
                "reference": artifact.provenance.reference,
                "complete": not missing,
                "missing": missing,
            },
            "permissions": _permissions(principal.role, "artifacts"),
            "trace": None,
        },
    }


def session_response(
    binding: DraftSessionBinding,
    principal: VerifiedPrincipal,
    *,
    request_id: str,
    lifecycle: SessionLifecycle,
) -> dict[str, Any]:
    return {
        "data": {
            "id": public_id("session", binding.id),
            "status": lifecycle.state.value,
            "problem_statement": binding.problem_statement,
            "agent_definition_ids": [
                public_id("agent", item.agent_definition_id) for item in binding.agents
            ],
            "objective_ids": [
                public_id("artifact", item.artifact_id) for item in binding.objectives
            ],
            "constraint_ids": [
                public_id("artifact", item.artifact_id) for item in binding.constraints
            ],
            "budget": binding.budget.model_dump(mode="json"),
            "round": lifecycle.round,
            "workflow_id": lifecycle.workflow_id,
            "run_id": lifecycle.run_id,
            "initialized_at": _optional_timestamp(lifecycle.initialized_at),
            "started_at": _optional_timestamp(lifecycle.started_at),
            "ended_at": _optional_timestamp(lifecycle.ended_at),
        },
        "meta": {
            "request_id": request_id,
            "schema_version": 1,
            "version": 1,
            "workspace_id": public_id("workspace", binding.workspace_id),
            "created_at": binding.created_at.isoformat().replace("+00:00", "Z"),
            "updated_at": lifecycle.updated_at.isoformat().replace("+00:00", "Z"),
            "owner": {"id": public_id("user", binding.created_by), "class": "HUMAN"},
            "permissions": _permissions(principal.role, "sessions"),
            "trace": None,
        },
    }


def _optional_timestamp(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None
