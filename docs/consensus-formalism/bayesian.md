# Strategy: `bayesian`  *(research)*

**Status:** research, Phase 16 · **Class:** opinion pooling over proposition posteriors ·
**Port:** `ConsensusStrategy` · **Parent:** [README](README.md)

## Idea

Treat each agent's position on a normalized proposition as a posterior over that proposition, pool the
posteriors, and report the pooled distribution rather than a winner. The interesting part is not the
pooling — it is what the platform must refuse to do in order to pool honestly.

## Inputs

`propositions`, per-agent posteriors over each proposition, evidence with verification state (used to
set likelihood weights), and per-agent calibration history (`CA-01`) where it exists.

## Parameters

| Name | Default | Effect |
| --- | --- | --- |
| `pooling` | `geometric` | `geometric` (Cooke) or `linear` |
| `weight_source` | `calibration` | `equal`, `calibration`, or `trust` — **must be declared** |
| `prior_floor` | `0.01` | no posterior is ever 0, so no single agent can veto by assertion |
| `report` | `distribution` | `distribution` is the only admissible value in the UI |

## Mathematics

Geometric (loglinear) pooling with weights `λ_i`, `Σ λ_i = 1`:

```text
P_pool(φ) ∝ Π_i P_i(φ)^{λ_i}          normalised over {φ, ¬φ}
odds_pool = Π_i odds_i^{λ_i}
```

Geometric pooling is **externally Bayesian** — it commutes with conditioning on new evidence, which
linear pooling does not. Linear pooling is retained for comparison because the difference between the
two is itself a finding about how much the answer depends on the aggregation rule.

## Outcome mapping

| Condition | Outcome |
| --- | --- |
| `P_pool(φ) > 0.9` for the decision-relevant propositions and feasible | `FULL_CONSENSUS` |
| `0.6 – 0.9` | `PARTIAL_CONSENSUS` |
| pooled odds within a factor of 1.2 of even | `NO_CONSENSUS` |
| any agent at `prior_floor` with a warranted defeater | capped at `CONDITIONAL_CONSENSUS` |

## Invariants

Preserves C-1, C-3, C-7. **Tension with C-5:** an agent's declared `confidence` is *not* a posterior
(CF-1, CF-2), so this strategy may only run where agents have produced genuine calibrated posteriors —
which, today, is nowhere. Until `CA-01` exists for the agents in a session, the strategy is
`NOT_APPLICABLE`, and that is the honest answer rather than a failure.

**How it can violate C-2.** A pooled posterior of 0.51 rendered as a winner is the single worst
possible output of this design; the `report = distribution` rule exists to make it unrepresentable.

## Failure modes

| Case | Behaviour |
| --- | --- |
| Confidence treated as probability | forbidden by CF-2; registration refuses to bind `weight_source` to raw confidence |
| One agent at the prior floor | geometric pooling lets a single confident dissenter dominate the log-odds product — the floor bounds it, and the effect is disclosed |
| Duplicate evidence across agents | double counting; independence is assumed and is false. Requires the `independence_cap` idea from [evidence_weighted.md](evidence_weighted.md) |
| No calibration history | `NOT_APPLICABLE` with the reason |

## Research questions

Q-4, Q-7. The comparison against `weighted` on identical inputs tests whether probabilistic aggregation
beats ordinal aggregation when the inputs are not genuinely probabilistic — a question worth answering
precisely because the intuitive answer is "no".

## Related

[README](README.md) · [EPISTEMIC_MODEL.md §4](../EPISTEMIC_MODEL.md) ·
[deliberative.md](deliberative.md) · [METRICS.md §4.8](../METRICS.md)
