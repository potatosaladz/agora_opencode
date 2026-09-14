"""Immutable, deterministic T11-01 formalization domain.

This module validates syntax, sorts, and units only.  It deliberately contains no
solver, satisfiability, implication, or policy-evaluation behavior.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from app.domain.reasoning import ActorClass, content_hash

__all__ = [
    "VALIDATOR_RULESET",
    "ASTNode",
    "BooleanLiteral",
    "FormalizationDecision",
    "FormalizationDecisionKind",
    "FormalizationError",
    "FormalizationRepository",
    "FormalizationRevision",
    "FormalizationStatus",
    "FormalizationValidation",
    "IntegerLiteral",
    "Operation",
    "Operator",
    "RealLiteral",
    "Sort",
    "SymbolDeclaration",
    "SymbolReference",
    "ValidationIssue",
    "ast_hash",
    "derive_status",
    "parse_ast",
    "render_ast",
    "validate_revision",
]

VALIDATOR_RULESET = "agora-formalization-structural-v1"
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_UNIT = re.compile(
    r"^(?:1|[A-Za-z][A-Za-z0-9_]*(?:\^-?[1-9][0-9]*)?"
    r"(?:\*[A-Za-z][A-Za-z0-9_]*(?:\^-?[1-9][0-9]*)?)*)$"
)
_INTEGER = re.compile(r"^(?:0|-?[1-9][0-9]*)$")
_REAL = re.compile(r"^(?:0|-?[1-9][0-9]*)(?:\.[0-9]*[1-9])?$")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


class Sort(StrEnum):
    BOOLEAN = "BOOLEAN"
    INTEGER = "INTEGER"
    REAL = "REAL"


class Operator(StrEnum):
    NOT = "NOT"
    AND = "AND"
    OR = "OR"
    NEG = "NEG"
    ADD = "ADD"
    SUB = "SUB"
    MUL = "MUL"
    DIV = "DIV"
    EQ = "EQ"
    NE = "NE"
    LT = "LT"
    LE = "LE"
    GT = "GT"
    GE = "GE"


class BooleanLiteral(_Frozen):
    kind: Literal["boolean"] = "boolean"
    value: bool


class IntegerLiteral(_Frozen):
    kind: Literal["integer"] = "integer"
    value: str

    @field_validator("value")
    @classmethod
    def canonical_integer(cls, value: str) -> str:
        if not _INTEGER.fullmatch(value):
            raise ValueError("integer must use canonical base-10 representation")
        return value


class RealLiteral(_Frozen):
    kind: Literal["real"] = "real"
    value: str

    @field_validator("value")
    @classmethod
    def canonical_real(cls, value: str) -> str:
        if not _REAL.fullmatch(value) or value == "-0":
            raise ValueError("real must use canonical decimal representation")
        return value


class SymbolReference(_Frozen):
    kind: Literal["symbol"] = "symbol"
    name: str

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not _NAME.fullmatch(value):
            raise ValueError("symbol name is invalid")
        return value


class Operation(_Frozen):
    kind: Literal["operation"] = "operation"
    operator: Operator
    arguments: tuple[ASTNode, ...]


ASTNode = Annotated[
    BooleanLiteral | IntegerLiteral | RealLiteral | SymbolReference | Operation,
    Field(discriminator="kind"),
]
_AST: TypeAdapter[ASTNode] = TypeAdapter(ASTNode)


class SymbolDeclaration(_Frozen):
    name: str
    sort: Sort
    meaning: str
    unit: str | None = None

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not _NAME.fullmatch(value):
            raise ValueError("symbol name is invalid")
        return value

    @field_validator("meaning")
    @classmethod
    def meaning_not_blank(cls, value: str) -> str:
        return _not_blank(value)

    @model_validator(mode="after")
    def valid_unit(self) -> SymbolDeclaration:
        if self.sort is Sort.BOOLEAN and self.unit is not None:
            raise ValueError("BOOLEAN symbols cannot have units")
        if self.sort is not Sort.BOOLEAN and (self.unit is None or not _UNIT.fullmatch(self.unit)):
            raise ValueError("numeric symbols require a canonical unit")
        return self


class ValidationIssue(_Frozen):
    code: str
    path: str
    message: str


class FormalizationStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class FormalizationDecisionKind(StrEnum):
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class FormalizationRevision(_Frozen):
    """One immutable content revision pinned to exact artifact revisions."""

    id: UUID
    logical_id: UUID
    revision: int = Field(ge=1)
    supersedes_id: UUID | None
    workspace_id: UUID
    session_id: UUID
    source_artifact_id: UUID
    source_artifact_logical_id: UUID
    source_artifact_version: int = Field(ge=1)
    ast: ASTNode
    ast_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    symbols: tuple[SymbolDeclaration, ...]
    canonical_rendering: str
    premise_artifact_ids: tuple[UUID, ...]
    limitations: tuple[str, ...]
    fidelity_notes: str
    created_at: datetime
    actor_class: ActorClass
    actor_id: UUID
    correlation_id: UUID

    @field_validator("canonical_rendering", "fidelity_notes")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        return _not_blank(value)

    @field_validator("limitations")
    @classmethod
    def limitations_not_blank(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("at least one limitation is required")
        for value in values:
            _not_blank(value)
        return values

    @field_validator("created_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def coherent_revision(self) -> FormalizationRevision:
        if (self.revision == 1) != (self.supersedes_id is None):
            raise ValueError("revision 1 alone has no predecessor")
        if self.ast_hash != ast_hash(self.ast):
            raise ValueError("ast_hash does not match canonical AST")
        if len(self.premise_artifact_ids) != len(set(self.premise_artifact_ids)):
            raise ValueError("premise artifact ids must be unique")
        return self


class FormalizationValidation(_Frozen):
    id: UUID
    workspace_id: UUID
    formalization_revision_id: UUID
    ast_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    validator_ruleset: str
    success: bool
    issues: tuple[ValidationIssue, ...]
    validated_at: datetime
    actor_class: ActorClass
    actor_id: UUID
    correlation_id: UUID

    @model_validator(mode="after")
    def coherent_result(self) -> FormalizationValidation:
        if self.success == bool(self.issues):
            raise ValueError("success requires no issues and failure requires issues")
        return self


class FormalizationDecision(_Frozen):
    id: UUID
    workspace_id: UUID
    formalization_revision_id: UUID
    ast_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    kind: FormalizationDecisionKind
    reason: str
    decided_at: datetime
    actor_id: UUID
    correlation_id: UUID

    _reason_not_blank = field_validator("reason")(_not_blank)


class FormalizationError(ValueError):
    """A lifecycle operation conflicts with authoritative formalization facts."""


def parse_ast(value: Any) -> ASTNode:
    """Parse the closed AST; unknown nodes/operators fail closed."""
    if isinstance(value, str | bytes):
        return _AST.validate_json(value)
    return _AST.validate_json(json.dumps(value, separators=(",", ":")))


def ast_hash(ast: ASTNode) -> str:
    return content_hash(_AST.dump_python(ast, mode="json"))


_TOKEN = {
    Operator.NOT: "not",
    Operator.AND: "and",
    Operator.OR: "or",
    Operator.NEG: "-",
    Operator.ADD: "+",
    Operator.SUB: "-",
    Operator.MUL: "*",
    Operator.DIV: "/",
    Operator.EQ: "=",
    Operator.NE: "!=",
    Operator.LT: "<",
    Operator.LE: "<=",
    Operator.GT: ">",
    Operator.GE: ">=",
}


def render_ast(node: ASTNode) -> str:
    if isinstance(node, BooleanLiteral):
        return "true" if node.value else "false"
    if isinstance(node, IntegerLiteral | RealLiteral):
        return node.value
    if isinstance(node, SymbolReference):
        return node.name
    rendered = tuple(render_ast(item) for item in node.arguments)
    if node.operator is Operator.NOT:
        return f"(not {rendered[0]})" if rendered else "(not)"
    if node.operator is Operator.NEG:
        return f"(-{rendered[0]})" if rendered else "(-)"
    return "(" + f" {_TOKEN[node.operator]} ".join(rendered) + ")"


def _unit_multiply(left: str, right: str) -> str:
    if left == "1":
        return right
    if right == "1":
        return left
    return "*".join(sorted((*left.split("*"), *right.split("*"))))


def _issue(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, path=path, message=message)


def validate_revision(revision: FormalizationRevision) -> FormalizationValidation:
    """Run deterministic structural/sort/unit checks without evaluating the expression."""
    issues: list[ValidationIssue] = []
    declarations: dict[str, SymbolDeclaration] = {}
    for index, symbol in enumerate(revision.symbols):
        if symbol.name in declarations:
            issues.append(_issue("DUPLICATE_SYMBOL", f"symbols[{index}]", symbol.name))
        else:
            declarations[symbol.name] = symbol

    def walk(node: ASTNode, path: str) -> tuple[Sort | None, str | None]:
        if isinstance(node, BooleanLiteral):
            return Sort.BOOLEAN, None
        if isinstance(node, IntegerLiteral):
            return Sort.INTEGER, None
        if isinstance(node, RealLiteral):
            return Sort.REAL, None
        if isinstance(node, SymbolReference):
            declaration = declarations.get(node.name)
            if declaration is None:
                issues.append(_issue("UNDECLARED_SYMBOL", path, node.name))
                return None, None
            return declaration.sort, declaration.unit
        arity = 1 if node.operator in {Operator.NOT, Operator.NEG} else 2
        if len(node.arguments) != arity:
            issues.append(
                _issue("WRONG_ARITY", path, f"{node.operator.value} requires {arity} arguments")
            )
        inferred = [
            walk(item, f"{path}.arguments[{index}]") for index, item in enumerate(node.arguments)
        ]
        if len(inferred) != arity or any(sort is None for sort, _ in inferred):
            return None, None
        sorts = [item[0] for item in inferred]
        units = [item[1] for item in inferred]
        if node.operator is Operator.NOT:
            if sorts[0] is not Sort.BOOLEAN:
                issues.append(_issue("SORT_MISMATCH", path, "NOT requires BOOLEAN"))
            return Sort.BOOLEAN, None
        if node.operator in {Operator.AND, Operator.OR}:
            if sorts != [Sort.BOOLEAN, Sort.BOOLEAN]:
                issues.append(
                    _issue("SORT_MISMATCH", path, f"{node.operator.value} requires BOOLEAN")
                )
            return Sort.BOOLEAN, None
        numeric = {Sort.INTEGER, Sort.REAL}
        if node.operator is Operator.NEG:
            if sorts[0] not in numeric:
                issues.append(_issue("SORT_MISMATCH", path, "NEG requires a numeric operand"))
            return sorts[0], units[0]
        if node.operator in {Operator.ADD, Operator.SUB}:
            if not all(sort in numeric for sort in sorts):
                issues.append(_issue("SORT_MISMATCH", path, "arithmetic requires numeric operands"))
            effective_units = [unit for unit in units if unit not in {None, "1"}]
            if len(set(effective_units)) > 1:
                issues.append(_issue("UNIT_MISMATCH", path, "ADD/SUB operands require equal units"))
            return (
                Sort.REAL if Sort.REAL in sorts else Sort.INTEGER,
                effective_units[0] if effective_units else "1",
            )
        if node.operator in {Operator.MUL, Operator.DIV}:
            if not all(sort in numeric for sort in sorts):
                issues.append(_issue("SORT_MISMATCH", path, "arithmetic requires numeric operands"))
            if node.operator is Operator.DIV and units[1] != "1":
                issues.append(
                    _issue("UNSUPPORTED_UNIT_OPERATION", path, "DIV divisor must be dimensionless")
                )
            unit = (
                _unit_multiply(units[0] or "1", units[1] or "1")
                if node.operator is Operator.MUL
                else units[0]
            )
            return Sort.REAL, unit
        if node.operator in {Operator.EQ, Operator.NE}:
            if sorts[0] != sorts[1] and not all(sort in numeric for sort in sorts):
                issues.append(
                    _issue("SORT_MISMATCH", path, "equality operands have incompatible sorts")
                )
            effective_units = [unit for unit in units if unit not in {None, "1"}]
            if all(sort in numeric for sort in sorts) and len(set(effective_units)) > 1:
                issues.append(
                    _issue("UNIT_MISMATCH", path, "equality operands require equal units")
                )
            return Sort.BOOLEAN, None
        if not all(sort in numeric for sort in sorts):
            issues.append(_issue("SORT_MISMATCH", path, "ordering requires numeric operands"))
        effective_units = [unit for unit in units if unit not in {None, "1"}]
        if len(set(effective_units)) > 1:
            issues.append(_issue("UNIT_MISMATCH", path, "ordering operands require equal units"))
        return Sort.BOOLEAN, None

    root_sort, _ = walk(revision.ast, "ast")
    if root_sort is not None and root_sort is not Sort.BOOLEAN:
        issues.append(_issue("NON_BOOLEAN_ROOT", "ast", "formalization root must be BOOLEAN"))
    if revision.canonical_rendering != render_ast(revision.ast):
        issues.append(_issue("NONCANONICAL_RENDERING", "canonical_rendering", "rendering differs"))
    ordered = tuple(sorted(issues, key=lambda item: (item.path, item.code, item.message)))
    return FormalizationValidation(
        id=UUID(int=0),
        workspace_id=revision.workspace_id,
        formalization_revision_id=revision.id,
        ast_hash=revision.ast_hash,
        validator_ruleset=VALIDATOR_RULESET,
        success=not ordered,
        issues=ordered,
        validated_at=revision.created_at,
        actor_class=ActorClass.SERVICE,
        actor_id=revision.actor_id,
        correlation_id=revision.correlation_id,
    )


def derive_status(
    validation: FormalizationValidation | None, decision: FormalizationDecision | None
) -> FormalizationStatus:
    if validation is not None and not validation.success:
        return FormalizationStatus.REJECTED
    if decision is not None and decision.kind is FormalizationDecisionKind.REJECTED:
        return FormalizationStatus.REJECTED
    if (
        validation is not None
        and validation.success
        and decision is not None
        and decision.kind is FormalizationDecisionKind.CONFIRMED
    ):
        return FormalizationStatus.VALIDATED
    return FormalizationStatus.CANDIDATE


@runtime_checkable
class FormalizationRepository(Protocol):
    async def add_revision(self, revision: FormalizationRevision) -> None: ...

    async def head(
        self, workspace_id: UUID, logical_id: UUID, *, for_update: bool = False
    ) -> FormalizationRevision | None: ...

    async def revision(
        self, workspace_id: UUID, logical_id: UUID, revision: int | None = None
    ) -> FormalizationRevision | None: ...

    async def validation(
        self, workspace_id: UUID, revision_id: UUID
    ) -> FormalizationValidation | None: ...

    async def decision(
        self, workspace_id: UUID, revision_id: UUID
    ) -> FormalizationDecision | None: ...

    async def add_validation(self, validation: FormalizationValidation) -> None: ...
    async def add_decision(self, decision: FormalizationDecision) -> None: ...
    async def verify_artifacts(self, revision: FormalizationRevision) -> None: ...

    async def add_event(
        self,
        *,
        event_id: UUID,
        event_type: str,
        revision: FormalizationRevision,
        status: FormalizationStatus,
        actor_id: UUID,
        correlation_id: UUID,
        recorded_at: datetime,
    ) -> None: ...


# Ensure recursive Operation references are resolved once at import time.
Operation.model_rebuild()
