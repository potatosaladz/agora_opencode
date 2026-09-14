"""Explicit, bounded AGORA formalization AST to Z3 translation."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

import z3

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
    validate_revision,
)
from app.ports.symbolic import (
    SymbolicCoreMember,
    SymbolicErrorKind,
    SymbolicInputError,
    SymbolicReasoningError,
    SymbolicReasoningResult,
    SymbolicSolverError,
    SymbolicStatus,
    SymbolicValue,
    SymbolicValueKind,
    SymbolicWitnessBinding,
)

__all__ = ["SUPPORTED_OPERATORS", "Z3SymbolicReasoner"]

SUPPORTED_OPERATORS = frozenset(
    {
        Operator.NOT,
        Operator.AND,
        Operator.OR,
        Operator.NEG,
        Operator.ADD,
        Operator.SUB,
        Operator.MUL,
        Operator.DIV,
        Operator.EQ,
        Operator.NE,
        Operator.LT,
        Operator.LE,
        Operator.GT,
        Operator.GE,
    }
)
_UNARY_OPERATORS = frozenset({Operator.NOT, Operator.NEG})
_NUMERIC_SORTS = frozenset({Sort.INTEGER, Sort.REAL})
_SAFE_REASON = re.compile(r"[^A-Za-z0-9 _.,:;()'/-]")
type Expression = z3.ExprRef


class _Solver(Protocol):
    def set(self, *args: object, **kwargs: object) -> None: ...
    def add(self, *args: z3.BoolRef) -> None: ...
    def check(self, *assumptions: z3.BoolRef) -> z3.CheckSatResult: ...
    def reason_unknown(self) -> str: ...
    def model(self) -> z3.ModelRef: ...
    def unsat_core(self) -> z3.AstVector: ...


type SolverFactory = Callable[[z3.Context], _Solver]


@dataclass(frozen=True, slots=True)
class _Translated:
    expression: Expression
    sort: Sort


def _input_error(message: str, *, unsupported: bool = False) -> SymbolicInputError:
    return SymbolicInputError(
        message,
        kind=(
            SymbolicErrorKind.UNSUPPORTED_INPUT if unsupported else SymbolicErrorKind.INVALID_INPUT
        ),
    )


def _safe_reason(value: str) -> str:
    cleaned = _SAFE_REASON.sub("?", value).strip()
    return cleaned[:200] or "solver returned no reason"


# trace: FR-705, FR-708
class Z3SymbolicReasoner:
    """Per-invocation Z3 contexts with no shared assertions or leaked SDK values."""

    implementation = "z3"

    def __init__(
        self,
        *,
        timeout_ms: int,
        solver_factory: SolverFactory | None = None,
    ) -> None:
        if isinstance(timeout_ms, bool) or not 1 <= timeout_ms <= 60_000:
            raise ValueError("symbolic timeout_ms must be between 1 and 60000")
        self._timeout_ms = timeout_ms
        self._solver_factory = solver_factory or (lambda context: z3.Solver(ctx=context))

    async def evaluate(self, model: FormalizationRevision) -> SymbolicReasoningResult:
        return await asyncio.to_thread(self._evaluate_sync, model)

    def _evaluate_sync(self, model: FormalizationRevision) -> SymbolicReasoningResult:
        try:
            self._validate_boundary(model)
            context = z3.Context()
            symbols = self._translate_declarations(model.symbols, context)
            translated = self._translate_node(model.ast, symbols, context, path="ast")
            self._require_boolean_root(translated)
            status, reason, witness, core = self._solve(
                context, translated.expression, symbols, model.ast
            )
            return SymbolicReasoningResult(
                status=status,
                formalization_revision_id=model.id,
                ast_hash=model.ast_hash,
                solver=self.implementation,
                solver_version=z3.get_version_string(),
                timeout_ms=self._timeout_ms,
                configuration_id=f"z3:timeout_ms={self._timeout_ms}",
                reason_unknown=reason,
                witness=witness,
                unsat_core=core,
            )
        except SymbolicReasoningError:
            raise
        except z3.Z3Exception:
            raise SymbolicSolverError(
                "symbolic solver failed", kind=SymbolicErrorKind.SOLVER_FAILURE
            ) from None
        except Exception as exc:
            raise SymbolicInputError(
                "invalid symbolic input", kind=SymbolicErrorKind.INVALID_INPUT
            ) from exc

    def _solve(
        self,
        context: z3.Context,
        expression: Expression,
        symbols: dict[str, _Translated],
        ast: ASTNode,
    ) -> tuple[
        SymbolicStatus,
        str | None,
        tuple[SymbolicWitnessBinding, ...],
        tuple[SymbolicCoreMember, ...],
    ]:
        try:
            solver = self._solver_factory(context)
            solver.set(timeout=self._timeout_ms)
            assertions = self._tracked_assertions(ast, cast(z3.BoolRef, expression))
            labels = {
                path: z3.Bool(f"agora_assertion_{index}", ctx=context)
                for index, (path, _) in enumerate(assertions)
            }
            for path, assertion in assertions:
                solver.add(z3.Implies(labels[path], assertion))
            outcome = solver.check(*labels.values())
            status, reason = self._map_outcome(outcome, solver)
            witness = self._witness(solver.model(), symbols) if status is SymbolicStatus.SAT else ()
            core = self._core(solver.unsat_core(), labels) if status is SymbolicStatus.UNSAT else ()
            return status, reason, witness, core
        except SymbolicReasoningError:
            raise
        except Exception:
            raise SymbolicSolverError(
                "symbolic solver failed", kind=SymbolicErrorKind.SOLVER_FAILURE
            ) from None

    @staticmethod
    def _tracked_assertions(
        ast: ASTNode, expression: z3.BoolRef
    ) -> tuple[tuple[str, z3.BoolRef], ...]:
        def flatten(
            node: ASTNode, translated: z3.BoolRef, path: str
        ) -> tuple[tuple[str, z3.BoolRef], ...]:
            if isinstance(node, Operation) and node.operator is Operator.AND:
                return tuple(
                    member
                    for index, argument in enumerate(node.arguments)
                    for member in flatten(
                        argument,
                        cast(z3.BoolRef, translated.arg(index)),
                        f"{path}.arguments[{index}]",
                    )
                )
            return ((path, translated),)

        return flatten(ast, expression, "ast")

    @staticmethod
    def _witness(
        model: z3.ModelRef, symbols: dict[str, _Translated]
    ) -> tuple[SymbolicWitnessBinding, ...]:
        values: list[SymbolicWitnessBinding] = []
        for name in sorted(symbols):
            symbol = symbols[name]
            value = model.eval(symbol.expression, model_completion=True)
            if symbol.sort is Sort.BOOLEAN:
                encoded = SymbolicValue(SymbolicValueKind.BOOLEAN, boolean=z3.is_true(value))
            elif z3.is_int_value(value):
                encoded = SymbolicValue(
                    SymbolicValueKind.INTEGER,
                    numerator=str(cast(z3.IntNumRef, value).as_long()),
                    denominator="1",
                )
            elif z3.is_rational_value(value):
                rational = cast(z3.RatNumRef, value)
                encoded = SymbolicValue(
                    SymbolicValueKind.RATIONAL,
                    numerator=str(rational.numerator_as_long()),
                    denominator=str(rational.denominator_as_long()),
                )
            elif isinstance(value, z3.AlgebraicNumRef):
                root = re.fullmatch(r"\(root-obj .+ ([1-9][0-9]*)\)", value.sexpr(), re.DOTALL)
                if root is None:
                    raise SymbolicSolverError(
                        "symbolic solver produced an unsupported algebraic witness",
                        kind=SymbolicErrorKind.SOLVER_FAILURE,
                    )
                encoded = SymbolicValue(
                    SymbolicValueKind.ALGEBRAIC,
                    polynomial=tuple(str(coefficient) for coefficient in value.poly()),
                    root_index=int(root.group(1)),
                )
            else:
                raise SymbolicSolverError(
                    "symbolic solver produced a non-rational witness",
                    kind=SymbolicErrorKind.SOLVER_FAILURE,
                )
            values.append(SymbolicWitnessBinding(name, encoded))
        return tuple(values)

    @staticmethod
    def _core(core: z3.AstVector, labels: dict[str, z3.BoolRef]) -> tuple[SymbolicCoreMember, ...]:
        selected = {label.decl().name() for label in core}
        paths = sorted(path for path, label in labels.items() if label.decl().name() in selected)
        if not paths:
            raise SymbolicSolverError(
                "symbolic solver returned an empty unsat core",
                kind=SymbolicErrorKind.SOLVER_FAILURE,
            )
        return tuple(SymbolicCoreMember(path) for path in paths)

    @staticmethod
    def _require_boolean_root(translated: _Translated) -> None:
        if translated.sort is not Sort.BOOLEAN:
            raise _input_error("formalization root must be BOOLEAN")

    @staticmethod
    def _map_outcome(
        outcome: z3.CheckSatResult, solver: _Solver
    ) -> tuple[SymbolicStatus, str | None]:
        if outcome == z3.sat:
            return SymbolicStatus.SAT, None
        if outcome == z3.unsat:
            return SymbolicStatus.UNSAT, None
        if outcome == z3.unknown:
            return SymbolicStatus.UNKNOWN, _safe_reason(solver.reason_unknown())
        raise SymbolicSolverError(
            "symbolic solver returned an unrecognized result",
            kind=SymbolicErrorKind.SOLVER_FAILURE,
        )

    @staticmethod
    def _validate_boundary(model: FormalizationRevision) -> None:
        if model.ast_hash != ast_hash(model.ast):
            raise _input_error("ast_hash does not match canonical AST")
        if model.canonical_rendering != render_ast(model.ast):
            raise _input_error("canonical rendering does not match AST")
        validation = validate_revision(model)
        if not validation.success:
            codes = ", ".join(sorted({issue.code for issue in validation.issues}))
            raise _input_error(f"formalization failed structural validation: {codes}")

    @staticmethod
    def _translate_declarations(
        declarations: tuple[SymbolDeclaration, ...], context: z3.Context
    ) -> dict[str, _Translated]:
        symbols: dict[str, _Translated] = {}
        for declaration in declarations:
            if declaration.name in symbols:
                raise _input_error(f"duplicate symbol declaration: {declaration.name}")
            if declaration.sort is Sort.BOOLEAN:
                expression: Expression = z3.Bool(declaration.name, ctx=context)
            elif declaration.sort is Sort.INTEGER:
                expression = z3.Int(declaration.name, ctx=context)
            elif declaration.sort is Sort.REAL:
                expression = z3.Real(declaration.name, ctx=context)
            else:
                raise _input_error(
                    f"unsupported symbol sort: {declaration.sort!s}", unsupported=True
                )
            symbols[declaration.name] = _Translated(expression, declaration.sort)
        return symbols

    def _translate_node(
        self,
        node: ASTNode,
        symbols: dict[str, _Translated],
        context: z3.Context,
        *,
        path: str,
    ) -> _Translated:
        if isinstance(node, BooleanLiteral):
            return _Translated(z3.BoolVal(node.value, ctx=context), Sort.BOOLEAN)
        if isinstance(node, IntegerLiteral):
            return _Translated(z3.IntVal(node.value, ctx=context), Sort.INTEGER)
        if isinstance(node, RealLiteral):
            return _Translated(z3.RealVal(node.value, ctx=context), Sort.REAL)
        if isinstance(node, SymbolReference):
            try:
                return symbols[node.name]
            except KeyError as exc:
                raise _input_error(f"undeclared symbol at {path}: {node.name}") from exc
        if not isinstance(node, Operation):
            raise _input_error(f"unsupported AST node at {path}", unsupported=True)
        if node.operator not in SUPPORTED_OPERATORS:
            raise _input_error(
                f"unsupported operator at {path}: {node.operator!s}", unsupported=True
            )
        expected_arity = 1 if node.operator in _UNARY_OPERATORS else 2
        if len(node.arguments) != expected_arity:
            raise _input_error(
                f"invalid arity at {path}: {node.operator} requires {expected_arity} arguments"
            )
        arguments = tuple(
            self._translate_node(item, symbols, context, path=f"{path}.arguments[{index}]")
            for index, item in enumerate(node.arguments)
        )
        return self._translate_operation(node.operator, arguments, path=path)

    @staticmethod
    def _translate_operation(
        operator: Operator, arguments: tuple[_Translated, ...], *, path: str
    ) -> _Translated:
        expressions = tuple(argument.expression for argument in arguments)
        sorts = tuple(argument.sort for argument in arguments)
        if operator is Operator.NOT:
            if sorts != (Sort.BOOLEAN,):
                raise _input_error(f"NOT requires BOOLEAN at {path}")
            return _Translated(z3.Not(expressions[0]), Sort.BOOLEAN)
        if operator in {Operator.AND, Operator.OR}:
            if sorts != (Sort.BOOLEAN, Sort.BOOLEAN):
                raise _input_error(f"{operator} requires BOOLEAN operands at {path}")
            expression = z3.And(*expressions) if operator is Operator.AND else z3.Or(*expressions)
            return _Translated(expression, Sort.BOOLEAN)
        if operator is Operator.NEG:
            if sorts[0] not in _NUMERIC_SORTS:
                raise _input_error(f"NEG requires a numeric operand at {path}")
            return _Translated(-expressions[0], sorts[0])
        if operator in {Operator.ADD, Operator.SUB, Operator.MUL, Operator.DIV}:
            if not all(sort in _NUMERIC_SORTS for sort in sorts):
                raise _input_error(f"{operator} requires numeric operands at {path}")
            if operator is Operator.ADD:
                expression = expressions[0] + expressions[1]
            elif operator is Operator.SUB:
                expression = expressions[0] - expressions[1]
            elif operator is Operator.MUL:
                expression = expressions[0] * expressions[1]
            else:
                dividend = z3.ToReal(expressions[0]) if sorts[0] is Sort.INTEGER else expressions[0]
                divisor = z3.ToReal(expressions[1]) if sorts[1] is Sort.INTEGER else expressions[1]
                expression = dividend / divisor
            result_sort = (
                Sort.REAL if operator is Operator.DIV or Sort.REAL in sorts else Sort.INTEGER
            )
            return _Translated(expression, result_sort)
        if operator in {Operator.EQ, Operator.NE}:
            compatible = sorts[0] is sorts[1] or all(sort in _NUMERIC_SORTS for sort in sorts)
            if not compatible:
                raise _input_error(f"{operator} operands have incompatible sorts at {path}")
            expression = expressions[0] == expressions[1]
            return _Translated(
                expression if operator is Operator.EQ else z3.Not(expression), Sort.BOOLEAN
            )
        if operator in {Operator.LT, Operator.LE, Operator.GT, Operator.GE}:
            if not all(sort in _NUMERIC_SORTS for sort in sorts):
                raise _input_error(f"{operator} requires numeric operands at {path}")
            if operator is Operator.LT:
                expression = expressions[0] < expressions[1]
            elif operator is Operator.LE:
                expression = expressions[0] <= expressions[1]
            elif operator is Operator.GT:
                expression = expressions[0] > expressions[1]
            else:
                expression = expressions[0] >= expressions[1]
            return _Translated(expression, Sort.BOOLEAN)
        raise _input_error(f"unsupported operator at {path}: {operator!s}", unsupported=True)
