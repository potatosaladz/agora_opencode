"""T11-02 bounded Z3 adapter tests over the closed formalization AST."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest
import z3
from pydantic import ValidationError

from app.adapters.z3_symbolic.reasoner import SUPPORTED_OPERATORS, Z3SymbolicReasoner
from app.domain.formalization import (
    ASTNode,
    BooleanLiteral,
    FormalizationRevision,
    IntegerLiteral,
    Operation,
    Operator,
    RealLiteral,
    Sort,
    SymbolDeclaration,
    SymbolReference,
    ast_hash,
    render_ast,
)
from app.domain.reasoning import ActorClass
from app.ports.symbolic import (
    SymbolicErrorKind,
    SymbolicInputError,
    SymbolicSolverError,
    SymbolicStatus,
    SymbolicValue,
    SymbolicValueKind,
)
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{index:012d}") for index in range(1, 9))
NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)


def op(operator: Operator, *arguments: ASTNode) -> Operation:
    return Operation(operator=operator, arguments=arguments)


def revision(
    node: ASTNode,
    *symbols: SymbolDeclaration,
    identity: UUID = U[0],
) -> FormalizationRevision:
    return FormalizationRevision(
        id=identity,
        logical_id=U[0],
        revision=1,
        supersedes_id=None,
        workspace_id=U[1],
        session_id=U[2],
        source_artifact_id=U[3],
        source_artifact_logical_id=U[4],
        source_artifact_version=1,
        ast=node,
        ast_hash=ast_hash(node),
        symbols=symbols,
        canonical_rendering=render_ast(node),
        premise_artifact_ids=(),
        limitations=("Only the encoded constraint is evaluated",),
        fidelity_notes="Exact test formalization",
        created_at=NOW,
        actor_class=ActorClass.HUMAN,
        actor_id=U[5],
        correlation_id=U[6],
    )


def symbol(name: str, sort: Sort) -> SymbolDeclaration:
    return SymbolDeclaration(
        name=name,
        sort=sort,
        meaning=f"test {name}",
        unit=None if sort is Sort.BOOLEAN else "1",
    )


async def evaluate(
    node: ASTNode, *symbols: SymbolDeclaration, reasoner: Z3SymbolicReasoner | None = None
) -> SymbolicStatus:
    result = await (reasoner or Z3SymbolicReasoner(timeout_ms=500)).evaluate(
        revision(node, *symbols)
    )
    return result.status


@req("FR-705")
async def test_sat_and_unsat_integer_constraint_sets_are_distinct() -> None:
    x = SymbolReference(name="x")
    sat_formula = op(
        Operator.AND,
        op(Operator.GT, x, IntegerLiteral(value="0")),
        op(Operator.LT, x, IntegerLiteral(value="10")),
    )
    unsat_formula = op(
        Operator.AND,
        op(Operator.GT, x, IntegerLiteral(value="10")),
        op(Operator.LT, x, IntegerLiteral(value="5")),
    )

    assert await evaluate(sat_formula, symbol("x", Sort.INTEGER)) is SymbolicStatus.SAT
    assert await evaluate(unsat_formula, symbol("x", Sort.INTEGER)) is SymbolicStatus.UNSAT


@req("FR-705", "FR-706")
async def test_sat_witness_preserves_typed_exact_values_in_symbol_order() -> None:
    x = SymbolReference(name="x")
    r = SymbolReference(name="r")
    enabled = SymbolReference(name="enabled")
    formula = op(
        Operator.AND,
        op(Operator.EQ, x, IntegerLiteral(value="7")),
        op(Operator.AND, op(Operator.EQ, r, RealLiteral(value="0.25")), enabled),
    )

    result = await Z3SymbolicReasoner(timeout_ms=500).evaluate(
        revision(
            formula,
            symbol("x", Sort.INTEGER),
            symbol("r", Sort.REAL),
            symbol("enabled", Sort.BOOLEAN),
        )
    )

    assert tuple(binding.name for binding in result.witness) == ("enabled", "r", "x")
    assert result.witness[0].value.boolean is True
    assert result.witness[1].value.kind is SymbolicValueKind.RATIONAL
    assert (result.witness[1].value.numerator, result.witness[1].value.denominator) == ("1", "4")
    assert result.witness[2].value.kind is SymbolicValueKind.INTEGER
    assert (result.witness[2].value.numerator, result.witness[2].value.denominator) == ("7", "1")
    assert result.unsat_core == ()


@req("FR-705", "FR-706")
async def test_unsat_core_uses_deterministic_top_level_ast_paths() -> None:
    x = SymbolReference(name="x")
    formula = op(
        Operator.AND,
        op(Operator.GT, x, IntegerLiteral(value="10")),
        op(Operator.LT, x, IntegerLiteral(value="5")),
    )

    result = await Z3SymbolicReasoner(timeout_ms=500).evaluate(
        revision(formula, symbol("x", Sort.INTEGER))
    )

    assert result.status is SymbolicStatus.UNSAT
    assert tuple(member.ast_path for member in result.unsat_core) == (
        "ast.arguments[0]",
        "ast.arguments[1]",
    )
    assert result.witness == ()


@req("FR-705", "FR-706")
async def test_witness_model_completes_unconstrained_symbols_exactly() -> None:
    result = await Z3SymbolicReasoner(timeout_ms=500).evaluate(
        revision(
            BooleanLiteral(value=True),
            symbol("flag", Sort.BOOLEAN),
            symbol("count", Sort.INTEGER),
            symbol("ratio", Sort.REAL),
        )
    )

    assert tuple(binding.name for binding in result.witness) == ("count", "flag", "ratio")
    assert result.witness[0].value == SymbolicValue(
        SymbolicValueKind.INTEGER, numerator="0", denominator="1"
    )
    assert result.witness[1].value == SymbolicValue(SymbolicValueKind.BOOLEAN, boolean=False)
    assert result.witness[2].value == SymbolicValue(
        SymbolicValueKind.RATIONAL, numerator="0", denominator="1"
    )


@req("FR-705", "FR-706")
async def test_algebraic_witness_is_exact_polynomial_root_not_decimal_approximation() -> None:
    x = SymbolReference(name="x")
    result = await Z3SymbolicReasoner(timeout_ms=500).evaluate(
        revision(
            op(
                Operator.EQ,
                op(Operator.MUL, x, x),
                IntegerLiteral(value="2"),
            ),
            symbol("x", Sort.REAL),
        )
    )

    value = result.witness[0].value
    assert value.kind is SymbolicValueKind.ALGEBRAIC
    assert value.polynomial == ("-2", "0", "1")
    assert value.root_index in {1, 2}
    assert value.numerator is value.denominator is None


@req("FR-705")
async def test_boolean_contradiction_tautology_and_implication_encoding() -> None:
    a = SymbolReference(name="A")
    b = SymbolReference(name="B")
    declarations = (symbol("A", Sort.BOOLEAN), symbol("B", Sort.BOOLEAN))
    contradiction = op(Operator.AND, a, op(Operator.NOT, a))
    tautology = op(Operator.OR, a, op(Operator.NOT, a))
    implication = op(
        Operator.OR,
        op(Operator.NOT, a),
        b,
    )
    implication_counterexample = op(
        Operator.AND,
        implication,
        op(Operator.AND, a, op(Operator.NOT, b)),
    )

    assert await evaluate(contradiction, *declarations) is SymbolicStatus.UNSAT
    assert await evaluate(tautology, *declarations) is SymbolicStatus.SAT
    assert await evaluate(implication_counterexample, *declarations) is SymbolicStatus.UNSAT


@req("FR-705")
@pytest.mark.parametrize(
    ("operator", "left", "right", "expected"),
    [
        (Operator.EQ, "2", "2", SymbolicStatus.SAT),
        (Operator.NE, "2", "3", SymbolicStatus.SAT),
        (Operator.LT, "2", "3", SymbolicStatus.SAT),
        (Operator.LE, "2", "2", SymbolicStatus.SAT),
        (Operator.GT, "3", "2", SymbolicStatus.SAT),
        (Operator.GE, "2", "2", SymbolicStatus.SAT),
    ],
)
async def test_all_comparison_operators(
    operator: Operator, left: str, right: str, expected: SymbolicStatus
) -> None:
    assert (
        await evaluate(op(operator, IntegerLiteral(value=left), IntegerLiteral(value=right)))
        is expected
    )


@req("FR-705")
@pytest.mark.parametrize(
    ("arithmetic", "expected"),
    [
        (op(Operator.NEG, IntegerLiteral(value="5")), "-5"),
        (op(Operator.ADD, IntegerLiteral(value="2"), IntegerLiteral(value="3")), "5"),
        (op(Operator.SUB, IntegerLiteral(value="7"), IntegerLiteral(value="2")), "5"),
        (op(Operator.MUL, IntegerLiteral(value="2"), IntegerLiteral(value="3")), "6"),
        (op(Operator.DIV, IntegerLiteral(value="1"), IntegerLiteral(value="2")), "0.5"),
    ],
)
async def test_all_arithmetic_operators(arithmetic: ASTNode, expected: str) -> None:
    if isinstance(arithmetic, Operation) and arithmetic.operator is Operator.DIV:
        divisor = SymbolReference(name="divisor")
        arithmetic = op(Operator.DIV, IntegerLiteral(value="1"), divisor)
        formula = op(
            Operator.AND,
            op(Operator.EQ, divisor, IntegerLiteral(value="2")),
            op(Operator.EQ, arithmetic, RealLiteral(value=expected)),
        )
        assert await evaluate(formula, symbol("divisor", Sort.INTEGER)) is SymbolicStatus.SAT
        return
    expected_node: ASTNode = (
        RealLiteral(value=expected) if "." in expected else IntegerLiteral(value=expected)
    )
    assert await evaluate(op(Operator.EQ, arithmetic, expected_node)) is SymbolicStatus.SAT


@req("FR-705")
async def test_reals_are_exact_and_integer_real_arithmetic_is_supported() -> None:
    exact_tenth = op(
        Operator.EQ,
        op(Operator.MUL, RealLiteral(value="0.1"), IntegerLiteral(value="10")),
        IntegerLiteral(value="1"),
    )
    exact_negative = op(
        Operator.EQ,
        op(
            Operator.ADD,
            op(Operator.NEG, RealLiteral(value="0.2")),
            RealLiteral(value="1.2"),
        ),
        IntegerLiteral(value="1"),
    )
    repeating = op(
        Operator.AND,
        op(Operator.EQ, SymbolReference(name="divisor"), IntegerLiteral(value="3")),
        op(
            Operator.EQ,
            op(
                Operator.DIV,
                IntegerLiteral(value="1"),
                SymbolReference(name="divisor"),
            ),
            RealLiteral(value="0.3333333333333333"),
        ),
    )

    assert await evaluate(exact_tenth) is SymbolicStatus.SAT
    assert await evaluate(exact_negative) is SymbolicStatus.SAT
    assert await evaluate(repeating, symbol("divisor", Sort.INTEGER)) is SymbolicStatus.UNSAT


@req("FR-705")
def test_operator_translation_is_exhaustive() -> None:
    assert frozenset(Operator) == SUPPORTED_OPERATORS


@req("FR-705")
@pytest.mark.parametrize(
    "node",
    [
        SymbolReference(name="missing"),
        op(Operator.ADD, BooleanLiteral(value=True), IntegerLiteral(value="5")),
        op(Operator.LT, BooleanLiteral(value=True), IntegerLiteral(value="1")),
        op(Operator.NOT, IntegerLiteral(value="10")),
        op(Operator.AND, BooleanLiteral(value=True)),
    ],
)
async def test_invalid_symbolic_inputs_fail_closed(node: ASTNode) -> None:
    with pytest.raises(SymbolicInputError) as caught:
        await Z3SymbolicReasoner(timeout_ms=500).evaluate(revision(node))
    assert caught.value.kind is SymbolicErrorKind.INVALID_INPUT


@req("FR-705")
async def test_duplicate_declarations_fail_closed() -> None:
    declaration = symbol("x", Sort.INTEGER)
    with pytest.raises(SymbolicInputError, match="DUPLICATE_SYMBOL"):
        await Z3SymbolicReasoner(timeout_ms=500).evaluate(
            revision(
                op(Operator.EQ, SymbolReference(name="x"), IntegerLiteral(value="1")),
                declaration,
                declaration,
            )
        )


@req("FR-705")
async def test_unknown_node_operator_and_unsupported_sort_fail_closed() -> None:
    reasoner = Z3SymbolicReasoner(timeout_ms=500)
    invalid_node = cast(Any, object())
    with pytest.raises(SymbolicInputError) as node_error:
        reasoner._translate_node(invalid_node, {}, z3.Context(), path="ast")
    assert node_error.value.kind is SymbolicErrorKind.UNSUPPORTED_INPUT

    with pytest.raises(SymbolicInputError) as operator_error:
        reasoner._translate_operation(cast(Any, "FUTURE"), (), path="ast")
    assert operator_error.value.kind is SymbolicErrorKind.UNSUPPORTED_INPUT

    declaration = symbol("x", Sort.INTEGER).model_copy(update={"sort": cast(Any, "DATE")})
    with pytest.raises(SymbolicInputError) as sort_error:
        reasoner._translate_declarations((declaration,), z3.Context())
    assert sort_error.value.kind is SymbolicErrorKind.UNSUPPORTED_INPUT


@req("FR-708", "NFR-020")
async def test_unknown_and_timeout_are_first_class_and_bounded() -> None:
    class UnknownSolver:
        timeout: int | None = None

        def set(self, *args: object, **kwargs: object) -> None:
            self.timeout = cast(int, kwargs["timeout"])

        def add(self, *args: z3.BoolRef) -> None:
            pass

        def check(self, *assumptions: z3.BoolRef) -> z3.CheckSatResult:
            return z3.unknown

        def reason_unknown(self) -> str:
            return "timeout"

        def model(self) -> z3.ModelRef:
            raise AssertionError("UNKNOWN must not request a model")

        def unsat_core(self) -> z3.AstVector:
            raise AssertionError("UNKNOWN must not request an unsat core")

    solver = UnknownSolver()
    result = await Z3SymbolicReasoner(
        timeout_ms=17, solver_factory=lambda _context: solver
    ).evaluate(revision(BooleanLiteral(value=True)))

    assert result.status is SymbolicStatus.UNKNOWN
    assert result.reason_unknown == "timeout"
    assert result.timeout_ms == solver.timeout == 17
    assert result.configuration_id == "z3:timeout_ms=17"


@req("FR-705", "NFR-020")
async def test_solver_failure_is_contained_and_never_becomes_unsat() -> None:
    class BrokenSolver:
        def set(self, *args: object, **kwargs: object) -> None:
            pass

        def add(self, *args: z3.BoolRef) -> None:
            pass

        def check(self, *assumptions: z3.BoolRef) -> z3.CheckSatResult:
            raise z3.Z3Exception("sensitive internal failure")

        def reason_unknown(self) -> str:
            return ""

        def model(self) -> z3.ModelRef:
            raise AssertionError

        def unsat_core(self) -> z3.AstVector:
            raise AssertionError

    with pytest.raises(SymbolicSolverError, match="symbolic solver failed") as caught:
        await Z3SymbolicReasoner(
            timeout_ms=500, solver_factory=lambda _context: BrokenSolver()
        ).evaluate(revision(BooleanLiteral(value=True)))
    assert caught.value.kind is SymbolicErrorKind.SOLVER_FAILURE
    assert "sensitive" not in str(caught.value)


@req("FR-705")
async def test_repeated_execution_is_deterministic_and_solver_state_is_isolated() -> None:
    reasoner = Z3SymbolicReasoner(timeout_ms=500)
    false_revision = revision(BooleanLiteral(value=False))
    true_revision = revision(BooleanLiteral(value=True), identity=U[7])

    first = await reasoner.evaluate(false_revision)
    second = await reasoner.evaluate(true_revision)
    third = await reasoner.evaluate(false_revision)

    assert (first.status, second.status, third.status) == (
        SymbolicStatus.UNSAT,
        SymbolicStatus.SAT,
        SymbolicStatus.UNSAT,
    )
    assert first.solver_version == third.solver_version
    assert first.formalization_revision_id == false_revision.id
    assert first.ast_hash == false_revision.ast_hash
    assert first.solver == "z3"
    assert first.timeout_ms == 500
    assert first.configuration_id == "z3:timeout_ms=500"


@req("NFR-020")
def test_timeout_configuration_is_validated() -> None:
    for value in (0, -1, 60_001, True):
        with pytest.raises(ValueError, match="between 1 and 60000"):
            Z3SymbolicReasoner(timeout_ms=cast(Any, value))

    from app.config.settings import Settings

    with pytest.raises(ValidationError):
        Settings(symbolic_timeout_ms=0)
