# Strategy: `constraint_aware`  *(MVP default)*

**Status:** MVP, Phase 9 · **Class:** feasibility-gated lexicographic ·
**Port:** `ConsensusStrategy` · **Parent:** [README](README.md)

## Inputs

Everything in [`evidence_weighted`](evidence_weighted.md), plus `symbolic_evaluations` (per-alternative
`SAT`/`UNSAT`/`UNKNOWN` with unsat cores and witness models), `assumptions` with their materiality, and
`objectives` with declared conflicts.

## Parameters

| Name | Range | Default | Effect |
| --- | --- | --- | --- |
| `hard_modality_only` | bool | `true` | only `modality = HARD` constraints gate; soft constraints score |
| `pareto_epsilon` | `[0,1]` | `0.05` | objective difference below which alternatives are treated as tied |
| `min_flip_distance` | `[0,1]` | `0.02` | below this, the ranking is reported as threshold-bound |
| others | as in `evidence_weighted` | | |

<!-- trace: FR-607 -->
## Mathematics

Lexicographic: each stage filters or orders, and no later stage can undo an earlier one.

```text
Stage 1  Feasibility      keep a iff F(a) ≠ UNSAT
                           keep F(a) = UNKNOWN explicitly unresolved
                          if nothing remains → INFEASIBLE (with unsat cores), stop
Stage 2  Evidence floor   keep a iff Σ_i E(i,a) > 0 unless allow_unevidenced
                          if nothing remains → INSUFFICIENT_EVIDENCE, stop
Stage 3  Dominance        a ≺ b iff (∀k: v_k(b) ≥ v_k(a)) ∧ (∃k: v_k(b) > v_k(a) + ε)
                          undominated set P = {a : ¬∃b, a ≺ b}
Stage 4  Conflict test    if objectives are declared conflicting AND
                          argmax_k over P differs for ≥ 2 objectives → PARETO_SET, stop
Stage 5  Support order    rank P by support_ev(a) from evidence_weighted
Stage 6  Robustness       flip distance δ = min perturbation changing the Stage-5 order
                          δ < min_flip_distance → report threshold-bound
Stage 7  Classify         as evidence_weighted, capped by:
                            any F(a*) = UNKNOWN      → CONDITIONAL_CONSENSUS
                            unresolved blocking crit → ≤ PARTIAL_CONSENSUS
```

The essential difference from the other strategies: **Stage 4 can refuse to produce a winner.** When
objectives genuinely conflict, returning a single ranked answer is the wrong behaviour, and the Pareto
frontier is the honest one (FR-607, U-1).

## Invariants

Preserves C-1 … C-8. It is the only MVP strategy that implements C-1 as a *stage* rather than relying
on the external gate alone, and the only one that can emit `PARETO_SET` and `INFEASIBLE` natively
(C-2).

**How it can violate them.** Omitting the unresolved census could present an `UNKNOWN` alternative as
symbolically assured. The shared gate therefore retains the status in every score and forces a selected
unknown to `CONDITIONAL_CONSENSUS`. `allow_unevidenced = true` collapses Stage 2 and must be recorded as a
deliberate weakening. A `pareto_epsilon` of 0 makes almost nothing a tie, which manufactures a frontier
out of noise.

<!-- trace: FR-704 -->
## Worked example

```text
Alternatives: subsidy, tariff, do-nothing
Hard constraints: budget ≤ ceiling ; no regressive incidence
F(subsidy)      = UNSAT  core = {budget ≤ ceiling, cost_subsidy > ceiling}
F(tariff)       = SAT    witness = {rate = 0.11, cost = 0.9·ceiling}
F(do-nothing)   = SAT
Stage 1 → subsidy removed, its unsat core recorded and rendered
Stage 2 → both remaining have E > 0
Stage 3 → emissions: tariff ≻ do-nothing ; cost: do-nothing ≻ tariff → neither dominates
Stage 4 → objectives declared conflicting → outcome PARETO_SET, frontier = {tariff, do-nothing}
```

The recommendation is a frontier of two, each with the trade-off it represents, plus the reason
`subsidy` is absent — the unsat core, quoted with the artifacts that asserted each constraint. No
support number appears in the headline, because support was never the deciding quantity.

## Failure modes

| Case | Behaviour |
| --- | --- |
| Constraint set too weak to exclude anything | Stage 1 is a no-op; `FORMAL_UNDERCONSTRAINED` warning from the witness model |
| Every alternative UNSAT | `INFEASIBLE` with all cores; the session's next question is which constraint to relax |
| Solver `UNKNOWN` on all | outcome `CONDITIONAL_CONSENSUS` at best, with `RR-07` raised |
| Objectives not declared conflicting but demonstrably are | Stage 4 misses it; the Pareto plot in the explanation still shows the tension |
| Frontier of size 1 | reported as a single winner with `frontier_size: 1`, not as a Pareto result |

## Related

[README](README.md) · [evidence_weighted.md](evidence_weighted.md) · [weighted.md](weighted.md) ·
[NEURO_SYMBOLIC.md §6](../NEURO_SYMBOLIC.md) · [CONSENSUS_MODEL.md](../CONSENSUS_MODEL.md)
