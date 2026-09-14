<!-- trace: FR-705, FR-706, FR-707, FR-708 -->
# ADR-015: Z3 as the symbolic reasoner

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 11
**Requirements:** FR-705 … FR-708, NFR-003

## Context

The platform needs three things from a symbolic engine: decide satisfiability of a constraint set,
produce a **contradiction-sufficient unsat core** when it fails, and produce a **witness model** when it succeeds. It
must be deterministic, embeddable in a Python service, and free of licence encumbrance. The
expressible fragment is deliberately narrow: linear arithmetic plus uninterpreted functions.

## Decision

Use Z3 through the `SymbolicReasoner` port, over a two-sorted fragment (LRA + UF + boolean
structure). Every evaluation records `solver_version` and `timeout_ms`; `UNKNOWN` is a first-class
result that is never treated as satisfaction (FR-708, C-8).

## Consequences

**Positive.** Unsat cores come from the solver rather than from a heuristic search, which is what makes
the `INFEASIBLE` explanation actionable ([NEURO_SYMBOLIC.md §6](../NEURO_SYMBOLIC.md)). Mature, fast,
well documented, MIT-licensed, and available in every CI image without a service dependency.

**Negative.** Non-linear arithmetic, quantifier alternation and induction are out; a policy question
that genuinely needs them must be modelled differently or sent to a simulation. Z3's `UNKNOWN` is
common enough that `RR-07` needs a threshold and a design response.

**Neutral.** The port allows a second engine (CVC5) for cross-checking; disagreement between engines is
reported, not averaged (NS-4).

Z3 does not guarantee a minimum-cardinality core. T11-03 therefore records the returned
contradiction-sufficient subset using AGORA-owned deterministic AST paths and does not label it minimal.

## Alternatives considered

| Option | Why not |
| --- | --- |
| CVC5 | comparable capability; chosen as the cross-check engine rather than the primary |
| Answer-set programming (clingo) | better for combinatorial search, worse for arithmetic and unsat cores |
| Interval arithmetic / numeric checking only | cannot prove infeasibility, only fail to find a solution |
| Asking the LLM to check consistency | AP-5, and it is precisely the error the phase exists to prevent |

## Links

[NEURO_SYMBOLIC.md](../NEURO_SYMBOLIC.md) · [PORTS.md §7](../PORTS.md) ·
[REPRODUCIBILITY.md §7](../REPRODUCIBILITY.md) · [ADR-014](ADR-014-pluggable-consensus-feasibility-gate.md)
