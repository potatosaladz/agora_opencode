<!-- trace: FR-608 -->
# Consensus Strategy Formalisms

Every strategy registered in the platform has a document here, and the loader refuses to register one
that does not (FR-608, rule S-1 in [CONSENSUS_MODEL.md](../CONSENSUS_MODEL.md)). The point is not
paperwork: a strategy whose behaviour cannot be written down cannot be audited when it produces a bad
recommendation. Start from [TEMPLATE.md](TEMPLATE.md); name the file after the registered strategy id.

## Required structure

| Section | Content |
| --- | --- |
| Inputs | exactly which fields of `ConsensusContext` are read, and what happens when one is absent |
| Parameters | name, type, range, default, and what moving it does |
| Mathematics | the computation, in notation a reviewer can check by hand |
| Outcome mapping | how numbers become one of the eight outcome classes |
| Invariants | which of C-1 … C-8 it preserves, and **how it could violate them** |
| Worked example | a small input set with the arithmetic shown |
| Failure modes | degenerate inputs, pathologies, and what the explanation must disclose |
| Status | `mvp` or `research`, plus the phase that implements it |

## Index

| Strategy | Status | Document |
| --- | --- | --- |
| `weighted` | MVP, Phase 9 | [weighted.md](weighted.md) |
| `evidence_weighted` | MVP, Phase 9 | [evidence_weighted.md](evidence_weighted.md) |
| `constraint_aware` | MVP default, Phase 9 | [constraint_aware.md](constraint_aware.md) |
| `deliberative` | research, Phase 16 | [deliberative.md](deliberative.md) |
| `bayesian` | research, Phase 16 | [bayesian.md](bayesian.md) |
| `prediction_market` | research, Phase 16 | [prediction_market.md](prediction_market.md) |

<!-- trace: FR-602 -->
## Shared definitions

All documents use the same symbols:

| Symbol | Meaning |
| --- | --- |
| `A` | the set of alternatives, `a ∈ A` |
| `N` | the set of active agents (a principal with a position in this round), `i ∈ N` |
| `p(a, i)` | agent `i`'s position on `a`: `SUPPORT`, `OPPOSE`, `UNCERTAIN`, `ABSTAIN` |
| `c(a, i)` | agent `i`'s declared confidence on `a`, in `[0, 1]`, used only as declared (C-5) |
| `F(a)` | feasibility: `SAT`, `UNSAT`, `UNKNOWN` from the symbolic evaluation of `a`'s constraint set |
| `E(a)` | verified evidence strength supporting `a` (§ of [evidence_weighted.md](evidence_weighted.md)) |
| `v_k(a)` | normalised value of `a` on objective `k` |
| `w_k` | objective weight, `Σ w_k = 1` |
| `H(a)` | hard-constraint violation set for `a` |

**Feasibility gate (shared, not optional).** Before any formula below runs:

```text
if ∃ a with F(a) = UNSAT  →  a is removed from ranking, H(a) recorded
if all a have F(a) = UNSAT →  outcome = INFEASIBLE with the unsat cores; stop
if ∃ a with F(a) = UNKNOWN →  a may be ranked as unresolved, and selection is capped at
                                CONDITIONAL_CONSENSUS (C-8); it is never symbolically assured
```

This gate is implemented once, in the coordinator, and cannot be disabled by a strategy. C-1 is
enforced by construction, not by each strategy remembering to do it.
