"""Solver-neutral symbolic reasoning contract — PORTS.md §7.

The model type is generic so this outward-facing port does not import the domain layer.
Concrete composition binds it to the immutable formalization revision type.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeVar, runtime_checkable
from uuid import UUID

_SYMBOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_AST_PATH = re.compile(r"^ast(?:\.arguments\[[01]\])*$")

__all__ = [
    "SymbolicCoreMember",
    "SymbolicErrorKind",
    "SymbolicInputError",
    "SymbolicReasoner",
    "SymbolicReasoningError",
    "SymbolicReasoningResult",
    "SymbolicSolverError",
    "SymbolicStatus",
    "SymbolicValue",
    "SymbolicValueKind",
    "SymbolicWitnessBinding",
]


class SymbolicStatus(StrEnum):
    SAT = "SAT"
    UNSAT = "UNSAT"
    UNKNOWN = "UNKNOWN"


class SymbolicValueKind(StrEnum):
    BOOLEAN = "BOOLEAN"
    INTEGER = "INTEGER"
    RATIONAL = "RATIONAL"
    ALGEBRAIC = "ALGEBRAIC"


@dataclass(frozen=True, slots=True)
class SymbolicValue:
    """Exact solver-neutral value; rational values use reduced numerator/denominator text."""

    kind: SymbolicValueKind
    boolean: bool | None = None
    numerator: str | None = None
    denominator: str | None = None
    polynomial: tuple[str, ...] = ()
    root_index: int | None = None

    def __post_init__(self) -> None:
        if self.kind is SymbolicValueKind.BOOLEAN:
            if (
                self.boolean is None
                or self.numerator is not None
                or self.denominator is not None
                or self.polynomial
                or self.root_index is not None
            ):
                raise ValueError("BOOLEAN requires only boolean")
            return
        if self.kind is SymbolicValueKind.ALGEBRAIC:
            if (
                self.boolean is not None
                or self.numerator is not None
                or self.denominator is not None
                or len(self.polynomial) < 2
                or self.root_index is None
                or self.root_index < 1
            ):
                raise ValueError("ALGEBRAIC requires polynomial coefficients and root index")
            if any(str(int(value)) != value for value in self.polynomial):
                raise ValueError("polynomial coefficients must be canonical base-10 integers")
            if self.polynomial[-1] == "0":
                raise ValueError("algebraic polynomial leading coefficient must be non-zero")
            return
        if self.boolean is not None or self.numerator is None or self.denominator is None:
            raise ValueError("numeric values require numerator and denominator")
        if self.polynomial or self.root_index is not None:
            raise ValueError("rational values cannot contain algebraic fields")
        numerator, denominator = int(self.numerator), int(self.denominator)
        if denominator <= 0:
            raise ValueError("denominator must be positive")
        if self.kind is SymbolicValueKind.INTEGER and denominator != 1:
            raise ValueError("INTEGER denominator must be 1")
        if str(numerator) != self.numerator or str(denominator) != self.denominator:
            raise ValueError("numeric value must use canonical base-10 integers")
        if math.gcd(numerator, denominator) != 1:
            raise ValueError("numeric value must be reduced")


@dataclass(frozen=True, slots=True)
class SymbolicWitnessBinding:
    name: str
    value: SymbolicValue

    def __post_init__(self) -> None:
        if not _SYMBOL_NAME.fullmatch(self.name):
            raise ValueError("witness name must be a valid declared symbol name")


@dataclass(frozen=True, slots=True)
class SymbolicCoreMember:
    """AGORA-owned identity for a contradiction-sufficient tracked assertion."""

    ast_path: str

    def __post_init__(self) -> None:
        if not _AST_PATH.fullmatch(self.ast_path):
            raise ValueError("unsat core member must use a canonical AST path")


class SymbolicErrorKind(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    UNSUPPORTED_INPUT = "UNSUPPORTED_INPUT"
    SOLVER_FAILURE = "SOLVER_FAILURE"


class SymbolicReasoningError(Exception):
    """Safe, AGORA-owned failure crossing the symbolic reasoner boundary."""

    def __init__(self, message: str, *, kind: SymbolicErrorKind) -> None:
        super().__init__(message)
        self.kind = kind


class SymbolicInputError(SymbolicReasoningError):
    """The formalization cannot safely be translated."""


class SymbolicSolverError(SymbolicReasoningError):
    """The configured solver failed independently of satisfiability."""


@dataclass(frozen=True, slots=True)
class SymbolicReasoningResult:
    """Solver-neutral, immutable satisfiability result for one exact revision."""

    status: SymbolicStatus
    formalization_revision_id: UUID
    ast_hash: str
    solver: str
    solver_version: str
    timeout_ms: int
    configuration_id: str
    reason_unknown: str | None = None
    witness: tuple[SymbolicWitnessBinding, ...] = ()
    unsat_core: tuple[SymbolicCoreMember, ...] = ()

    def __post_init__(self) -> None:
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        if self.status is SymbolicStatus.UNKNOWN:
            if self.reason_unknown is None or not self.reason_unknown.strip():
                raise ValueError("UNKNOWN requires reason_unknown")
        elif self.reason_unknown is not None:
            raise ValueError("reason_unknown is valid only for UNKNOWN")
        if self.status is SymbolicStatus.SAT:
            if self.unsat_core:
                raise ValueError("SAT cannot contain an unsat core")
        elif self.witness:
            raise ValueError("only SAT can contain a witness")
        if self.status is SymbolicStatus.UNSAT:
            if not self.unsat_core:
                raise ValueError("UNSAT requires a contradiction-sufficient core")
        elif self.unsat_core:
            raise ValueError("only UNSAT can contain an unsat core")
        if tuple(sorted(self.witness, key=lambda item: item.name)) != self.witness:
            raise ValueError("witness bindings must be sorted by name")
        if len({item.name for item in self.witness}) != len(self.witness):
            raise ValueError("witness binding names must be unique")
        if tuple(sorted(self.unsat_core, key=lambda item: item.ast_path)) != self.unsat_core:
            raise ValueError("unsat core members must be sorted by AST path")
        if len({item.ast_path for item in self.unsat_core}) != len(self.unsat_core):
            raise ValueError("unsat core AST paths must be unique")


ModelT_contra = TypeVar("ModelT_contra", contravariant=True)


@runtime_checkable
class SymbolicReasoner(Protocol[ModelT_contra]):
    async def evaluate(self, model: ModelT_contra) -> SymbolicReasoningResult: ...
