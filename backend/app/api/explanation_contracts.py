"""Strict public contract for the persisted session decision explanation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.domain.explanation import ExplanationEmptyReason

__all__ = ["ExplanationEmptyReason", "ExplanationResponse"]


class _StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExplanationData(_StrictResponse):
    session_id: str
    status: str
    empty_reason: ExplanationEmptyReason | None
    decision: dict[str, Any]
    recommendation: dict[str, Any]
    why: dict[str, Any]
    alternatives: tuple[dict[str, Any], ...]
    evidence: dict[str, Any]
    assumptions_constraints: dict[str, Any]
    minority: tuple[dict[str, Any], ...]
    critiques: dict[str, Any]
    risks_uncertainties: dict[str, Any]
    symbolic_feasibility: dict[str, Any]
    conditions_counterfactuals: dict[str, Any]
    weakest_evidence: dict[str, Any]
    provenance: dict[str, Any]
    links: dict[str, str]


class ExplanationMeta(_StrictResponse):
    request_id: str
    schema_version: int
    workspace_id: str


class ExplanationResponse(_StrictResponse):
    data: ExplanationData
    meta: ExplanationMeta
