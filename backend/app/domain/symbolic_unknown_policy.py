"""Application-owned policy for consuming symbolic evaluation outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.ports.symbolic import SymbolicReasoningResult, SymbolicStatus

__all__ = [
    "SymbolicAssuranceAction",
    "SymbolicUnknownKind",
    "SymbolicUnknownPolicy",
    "SymbolicUnknownPolicyDecision",
]


class SymbolicAssuranceAction(StrEnum):
    PROCEED = "PROCEED"
    BLOCK = "BLOCK"
    DEFER = "DEFER"


class SymbolicUnknownKind(StrEnum):
    TIMEOUT = "TIMEOUT"
    INCOMPLETE = "INCOMPLETE"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class SymbolicUnknownPolicyDecision:
    symbolic_status: SymbolicStatus
    action: SymbolicAssuranceAction
    reason_code: str
    explanation: str
    unknown_kind: SymbolicUnknownKind | None = None
    solver_reason_code: str | None = None

    @property
    def provides_affirmative_assurance(self) -> bool:
        return self.action is SymbolicAssuranceAction.PROCEED


_TIMEOUT_REASONS = frozenset({"timeout", "canceled", "cancelled", "resource limit"})
_INCOMPLETE_REASONS = frozenset({"incomplete", "unknown", "solver returned no reason"})


def _solver_reason_code(reason: str) -> str:
    """Return a safe, bounded code without carrying arbitrary solver text downstream."""
    normalized = reason.strip().upper()
    cleaned = "".join(character if character.isalnum() else "_" for character in normalized)
    collapsed = "_".join(part for part in cleaned.split("_") if part)
    return collapsed[:64] or "UNSPECIFIED"


def _classify_unknown_reason(reason: str) -> SymbolicUnknownKind:
    normalized = " ".join(reason.casefold().split())
    if normalized in _TIMEOUT_REASONS:
        return SymbolicUnknownKind.TIMEOUT
    if normalized in _INCOMPLETE_REASONS:
        return SymbolicUnknownKind.INCOMPLETE
    return SymbolicUnknownKind.OTHER


# trace: FR-708, NFR-020
class SymbolicUnknownPolicy:
    """Require positive SAT assurance; keep UNKNOWN distinct from contradiction."""

    def decide(self, result: SymbolicReasoningResult) -> SymbolicUnknownPolicyDecision:
        return self.decide_status(result.status, reason_unknown=result.reason_unknown)

    def decide_status(
        self, status: SymbolicStatus, *, reason_unknown: str | None = None
    ) -> SymbolicUnknownPolicyDecision:
        """Apply the same policy to a downstream solver-neutral feasibility projection."""
        if status is SymbolicStatus.SAT:
            return SymbolicUnknownPolicyDecision(
                symbolic_status=status,
                action=SymbolicAssuranceAction.PROCEED,
                reason_code="SYMBOLIC_ASSURANCE_ESTABLISHED",
                explanation="The symbolic constraints are satisfiable under the encoded premises.",
            )
        if status is SymbolicStatus.UNSAT:
            return SymbolicUnknownPolicyDecision(
                symbolic_status=status,
                action=SymbolicAssuranceAction.BLOCK,
                reason_code="SYMBOLIC_CONTRADICTION_ESTABLISHED",
                explanation="A contradiction was established under the encoded premises.",
            )
        if status is SymbolicStatus.UNKNOWN:
            if reason_unknown is None or not reason_unknown.strip():
                raise ValueError("UNKNOWN symbolic status requires a solver reason")
            return SymbolicUnknownPolicyDecision(
                symbolic_status=status,
                action=SymbolicAssuranceAction.DEFER,
                reason_code="SYMBOLIC_ASSURANCE_UNAVAILABLE",
                explanation=(
                    "Symbolic certainty is unavailable; actions requiring positive symbolic "
                    "assurance must be deferred."
                ),
                unknown_kind=_classify_unknown_reason(reason_unknown),
                solver_reason_code=_solver_reason_code(reason_unknown),
            )
        raise AssertionError(f"unhandled symbolic status: {status!r}")
