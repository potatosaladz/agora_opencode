"""Strict HTTP contracts for T11-01 formalization resources."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.application.formalization import FormalizationResult
from app.common.ids import parse_id, public_id
from app.domain.formalization import ASTNode, SymbolDeclaration

__all__ = [
    "FormalizationCreate",
    "FormalizationDecisionCreate",
    "FormalizationRevisionCreate",
    "FormalizationValidationCreate",
    "formalization_response",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FormalizationCreate(_Strict):
    source_artifact_id: str
    ast: ASTNode
    symbols: tuple[SymbolDeclaration, ...]
    canonical_rendering: str
    premise_artifact_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...]
    fidelity_notes: str

    @field_validator("ast", mode="before")
    @classmethod
    def decode_ast(cls, value: Any) -> Any:
        from app.domain.formalization import _AST

        return _AST.validate_json(json.dumps(value))

    @field_validator("symbols", mode="before")
    @classmethod
    def decode_symbols(cls, values: Any) -> tuple[SymbolDeclaration, ...]:
        return tuple(SymbolDeclaration.model_validate_json(json.dumps(value)) for value in values)

    @field_validator("source_artifact_id")
    @classmethod
    def source_id(cls, value: str) -> str:
        parse_id("artifact", value)
        return value

    @field_validator("premise_artifact_ids")
    @classmethod
    def premise_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            parse_id("artifact", value)
        if len(values) != len(set(values)):
            raise ValueError("premise artifact ids must be unique")
        return values


class FormalizationRevisionCreate(FormalizationCreate):
    pass


class FormalizationValidationCreate(_Strict):
    pass


class FormalizationDecisionCreate(_Strict):
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value


def formalization_response(result: FormalizationResult, *, request_id: str) -> dict[str, Any]:
    revision = result.revision
    return {
        "data": {
            "id": public_id("formalization", revision.logical_id),
            "revision_id": public_id("formalization", revision.id),
            "revision": revision.revision,
            "supersedes_id": (
                public_id("formalization", revision.supersedes_id)
                if revision.supersedes_id is not None
                else None
            ),
            "session_id": public_id("session", revision.session_id),
            "source_artifact_id": public_id("artifact", revision.source_artifact_id),
            "source_artifact_logical_id": public_id(
                "artifact", revision.source_artifact_logical_id
            ),
            "source_artifact_version": revision.source_artifact_version,
            "ast": revision.ast.model_dump(mode="json"),
            "ast_hash": revision.ast_hash,
            "symbols": [item.model_dump(mode="json") for item in revision.symbols],
            "canonical_rendering": revision.canonical_rendering,
            "premise_artifact_ids": [
                public_id("artifact", value) for value in revision.premise_artifact_ids
            ],
            "limitations": list(revision.limitations),
            "fidelity_notes": revision.fidelity_notes,
            "validation_status": result.status.value,
            "enforceable": result.enforceable,
            "validation": (
                {
                    "validator_ruleset": result.validation.validator_ruleset,
                    "success": result.validation.success,
                    "issues": [item.model_dump(mode="json") for item in result.validation.issues],
                    "validated_at": result.validation.validated_at.isoformat().replace(
                        "+00:00", "Z"
                    ),
                }
                if result.validation is not None
                else None
            ),
            "decision": (
                {
                    "kind": result.decision.kind.value,
                    "reason": result.decision.reason,
                    "actor_id": public_id("user", result.decision.actor_id),
                    "decided_at": result.decision.decided_at.isoformat().replace("+00:00", "Z"),
                }
                if result.decision is not None
                else None
            ),
        },
        "meta": {
            "request_id": request_id,
            "schema_version": 1,
            "version": revision.revision,
            "workspace_id": public_id("workspace", revision.workspace_id),
            "created_at": revision.created_at.isoformat().replace("+00:00", "Z"),
        },
    }
