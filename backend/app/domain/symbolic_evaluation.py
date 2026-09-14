"""Immutable exact-revision symbolic evaluation evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.reasoning import content_hash
from app.ports.symbolic import SymbolicReasoningResult

__all__ = [
    "SymbolicEvaluation",
    "SymbolicEvaluationConflict",
    "SymbolicEvaluationRepository",
    "symbolic_evaluation_hash",
]


def _evidence_payload(result: SymbolicReasoningResult) -> dict[str, Any]:
    return {
        "formalization_revision_id": str(result.formalization_revision_id),
        "ast_hash": result.ast_hash,
        "status": result.status.value,
        "solver": result.solver,
        "solver_version": result.solver_version,
        "timeout_ms": result.timeout_ms,
        "configuration_id": result.configuration_id,
        "reason_unknown": result.reason_unknown,
        "witness": [
            {
                "name": binding.name,
                "value": {
                    "kind": binding.value.kind.value,
                    "boolean": binding.value.boolean,
                    "numerator": binding.value.numerator,
                    "denominator": binding.value.denominator,
                    "polynomial": list(binding.value.polynomial),
                    "root_index": binding.value.root_index,
                },
            }
            for binding in result.witness
        ],
        "unsat_core": [{"ast_path": member.ast_path} for member in result.unsat_core],
    }


def symbolic_evaluation_hash(result: SymbolicReasoningResult) -> str:
    return content_hash(_evidence_payload(result))


class SymbolicEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: UUID
    workspace_id: UUID
    session_id: UUID
    result: SymbolicReasoningResult
    evidence_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evaluated_at: datetime
    actor_id: UUID
    correlation_id: UUID

    @field_validator("evaluated_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def coherent_hash(self) -> SymbolicEvaluation:
        if self.evidence_hash != symbolic_evaluation_hash(self.result):
            raise ValueError("evidence_hash does not match symbolic result")
        return self


class SymbolicEvaluationConflict(ValueError):
    """The same exact evaluation identity produced different immutable evidence."""


@runtime_checkable
class SymbolicEvaluationRepository(Protocol):
    async def persist(self, evaluation: SymbolicEvaluation) -> SymbolicEvaluation: ...

    async def get(self, workspace_id: UUID, evaluation_id: UUID) -> SymbolicEvaluation | None: ...
