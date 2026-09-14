"""Strict public contracts for the session assumption register."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.domain.critique import CritiqueResponseDisposition
from app.domain.formalization import FormalizationStatus
from app.domain.reasoning import (
    ActorClass,
    ArtifactKind,
    ConstraintType,
    LifecycleStatus,
    Resolution,
)
from app.domain.symbolic_unknown_policy import SymbolicAssuranceAction
from app.ports.symbolic import SymbolicStatus

__all__ = ["AssumptionRegisterResponse"]


class _StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterOwner(_StrictResponse):
    actor_class: ActorClass
    actor_id: str


class RegisterRelation(_StrictResponse):
    id: str
    kind: ArtifactKind | Literal["RECOMMENDATION"]
    relationship: str
    label: str | None
    graph_node_id: str | None
    provenance_href: str | None


class RegisterCritique(_StrictResponse):
    id: str
    artifact_id: str
    logical_id: str
    version: int
    critique_type: str
    severity: str
    resolution: Resolution
    response_disposition: CritiqueResponseDisposition | None
    graph_node_id: str | None
    provenance_href: str


class RegisterFormalization(_StrictResponse):
    id: str
    revision_id: str
    revision: int
    source_artifact_id: str
    source_artifact_version: int
    validation_status: FormalizationStatus


class RegisterSymbolicState(_StrictResponse):
    analysis_status: Literal["AVAILABLE", "MISSING_FORMALIZATION", "MISSING_EVALUATION"]
    formalization: RegisterFormalization | None
    evaluation_id: str | None
    status: SymbolicStatus | None
    reason: str
    policy_action: SymbolicAssuranceAction


class RegisterItem(_StrictResponse):
    id: str
    logical_id: str
    kind: Literal[ArtifactKind.ASSUMPTION, ArtifactKind.CONSTRAINT, ArtifactKind.UNCERTAINTY]
    statement: str | None
    basis: str | None
    materiality: str | None
    challengeable: bool | None
    constraint_type: ConstraintType | None
    category: str | None
    formal_status: str | None
    uncertainty_type: str | None
    drivers: tuple[str, ...] | None
    representation: dict[str, Any] | None
    context_artifact_id: str | None
    owner: RegisterOwner
    round: int
    version: int
    lifecycle: LifecycleStatus
    supersedes_id: str | None
    graph_node_id: str | None
    provenance_href: str
    evidence: tuple[RegisterRelation, ...]
    dependents: tuple[RegisterRelation, ...]
    critiques: tuple[RegisterCritique, ...]
    symbolic: RegisterSymbolicState | None


class AssumptionRegisterData(_StrictResponse):
    session_id: str
    items: tuple[RegisterItem, ...]


class AssumptionRegisterMeta(_StrictResponse):
    request_id: str
    schema_version: int
    workspace_id: str


class AssumptionRegisterResponse(_StrictResponse):
    data: AssumptionRegisterData
    meta: AssumptionRegisterMeta
