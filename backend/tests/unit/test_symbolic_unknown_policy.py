"""T11-04 deterministic UNKNOWN handling policy tests."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from app.domain.symbolic_unknown_policy import (
    SymbolicAssuranceAction,
    SymbolicUnknownKind,
    SymbolicUnknownPolicy,
)
from app.ports.symbolic import SymbolicCoreMember, SymbolicReasoningResult, SymbolicStatus
from tests.traceability import req
from tests.unit.test_z3_symbolic_reasoner import U


def _result(status: SymbolicStatus, *, reason: str | None = None) -> SymbolicReasoningResult:
    return SymbolicReasoningResult(
        status=status,
        formalization_revision_id=U[0],
        ast_hash="sha256:" + "1" * 64,
        solver="test",
        solver_version="1",
        timeout_ms=10,
        configuration_id="test:10",
        reason_unknown=reason,
        unsat_core=(SymbolicCoreMember("ast"),) if status is SymbolicStatus.UNSAT else (),
    )


@req("FR-708", "NFR-020")
@pytest.mark.parametrize(
    ("result", "action", "unknown_kind", "assured"),
    [
        (_result(SymbolicStatus.SAT), SymbolicAssuranceAction.PROCEED, None, True),
        (_result(SymbolicStatus.UNSAT), SymbolicAssuranceAction.BLOCK, None, False),
        (
            _result(SymbolicStatus.UNKNOWN, reason="timeout"),
            SymbolicAssuranceAction.DEFER,
            SymbolicUnknownKind.TIMEOUT,
            False,
        ),
        (
            _result(SymbolicStatus.UNKNOWN, reason="incomplete"),
            SymbolicAssuranceAction.DEFER,
            SymbolicUnknownKind.INCOMPLETE,
            False,
        ),
        (
            _result(SymbolicStatus.UNKNOWN, reason="theory limitation"),
            SymbolicAssuranceAction.DEFER,
            SymbolicUnknownKind.OTHER,
            False,
        ),
    ],
)
def test_policy_handles_every_symbolic_status_explicitly(
    result: SymbolicReasoningResult,
    action: SymbolicAssuranceAction,
    unknown_kind: SymbolicUnknownKind | None,
    assured: bool,
) -> None:
    decision = SymbolicUnknownPolicy().decide(result)

    assert decision.symbolic_status is result.status
    assert decision.action is action
    assert decision.unknown_kind is unknown_kind
    assert decision.provides_affirmative_assurance is assured
    if result.status is SymbolicStatus.UNKNOWN:
        assert decision.solver_reason_code is not None


@req("FR-708")
def test_unknown_decision_is_deterministic_and_preserves_solver_fact() -> None:
    result = _result(SymbolicStatus.UNKNOWN, reason="timeout")
    policy = SymbolicUnknownPolicy()

    assert policy.decide(result) == policy.decide(result)
    assert result.status is SymbolicStatus.UNKNOWN
    assert result.reason_unknown == "timeout"
    assert result.witness == ()
    assert result.unsat_core == ()


@req("FR-708")
def test_future_symbolic_status_cannot_fall_through_as_success() -> None:
    result = replace(_result(SymbolicStatus.SAT), status=cast(SymbolicStatus, "FUTURE"))

    with pytest.raises(AssertionError, match="unhandled symbolic status"):
        SymbolicUnknownPolicy().decide(result)
