"""Strict public response contracts for persisted session dissent."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.domain.critique import CritiqueResponseDisposition
from app.domain.reasoning import ArtifactKind, CritiqueType, LifecycleStatus, Resolution, Severity
from app.ports.consensus import ConsensusOutcome

__all__ = ["DissentEmptyReason", "DissentResponse"]


class _StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DissentEmptyReason(StrEnum):
    NO_CONSENSUS_RESULT = "NO_CONSENSUS_RESULT"
    CONSENSUS_EXPLANATION_UNAVAILABLE = "CONSENSUS_EXPLANATION_UNAVAILABLE"
    EVALUATED_NO_DISSENT = "EVALUATED_NO_DISSENT"


class DissentWarrant(_StrictResponse):
    id: str
    kind: ArtifactKind
    label: str | None
    lifecycle: LifecycleStatus
    graph_node_id: str | None
    provenance_href: str


class MinorityDissent(_StrictResponse):
    agent_id: str
    position: str
    warrants: tuple[DissentWarrant, ...]
    disputed_proposition_ids: tuple[str, ...]
    unresolved_critique_ids: tuple[str, ...]
    what_would_change: str | None


class CritiqueDissent(_StrictResponse):
    critique_id: str
    critique_artifact_id: str
    logical_id: str
    version: int
    target_artifact_id: str
    critique_type: CritiqueType
    severity: Severity
    resolution: Resolution
    response_disposition: CritiqueResponseDisposition | None
    warrant_artifact_ids: tuple[str, ...]
    replacement_target_artifact_id: str | None
    graph_node_id: str | None
    provenance_href: str
    argument: str | None


class MajorityContext(_StrictResponse):
    consensus_result_id: str
    outcome: ConsensusOutcome
    selected_alternative_id: str | None
    selected_alternative_label: str | None
    selected_alternative_graph_node_id: str | None
    selected_alternative_provenance_href: str | None
    strategy: str
    strategy_version: str
    round: int


class DissentEvidenceContext(_StrictResponse):
    supports_selected: tuple[DissentWarrant, ...]
    opposes_selected: tuple[DissentWarrant, ...]
    qualifies_selected: tuple[DissentWarrant, ...]


class DissentData(_StrictResponse):
    session_id: str
    evaluated: bool
    empty_reason: DissentEmptyReason | None
    majority: MajorityContext | None
    evidence_context: DissentEvidenceContext
    minority: tuple[MinorityDissent, ...]
    critiques: tuple[CritiqueDissent, ...]


class DissentMeta(_StrictResponse):
    request_id: str
    schema_version: int
    workspace_id: str


class DissentResponse(_StrictResponse):
    data: DissentData
    meta: DissentMeta
