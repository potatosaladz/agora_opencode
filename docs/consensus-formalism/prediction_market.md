# Strategy: `prediction_market`  *(research)*

**Status:** research, Phase 16 · **Class:** price as an aggregation mechanism ·
**Port:** `ConsensusStrategy` · **Parent:** [README](README.md)

## Idea

Agents hold positions in a bounded-liquidity market over decision-relevant propositions. The price is
the aggregate. The mechanism is included in the research track because it aggregates *dispersed*
information differently from any voting rule — and because it fails in ways worth measuring next to the
others.

## Inputs

Propositions with resolution criteria, agent budgets (play credits, never money), orders per round, and
the LMSR market state.

## Parameters

| Name | Default | Effect |
| --- | --- | --- |
| `market_mechanism` | `lmsr` | logarithmic market scoring rule; `cpmm` for comparison |
| `liquidity_b` | task-dependent | larger `b` ⇒ flatter prices, more resistance to a single whale |
| `budget_per_agent` | equal | equal endowment is the default; unequal endowment is a deliberate, recorded choice |
| `resolution_required` | `true` | a proposition with no resolution criterion cannot be traded |

## Mathematics

LMSR cost function over outcome vector `q`:

```text
C(q) = b · ln Σ_o exp(q_o / b)
price(o) = exp(q_o / b) / Σ_{o'} exp(q_{o'} / b)
```

A market clears to a price vector; the strategy maps `price(SUPPORT)` to support for ranking, with the
same feasibility gate as every other strategy ([README](README.md)).

## Outcome mapping

| Condition | Outcome |
| --- | --- |
| price spread across the top two alternatives > threshold and feasible | `FULL_CONSENSUS` equivalent |
| thin volume (total trades < `min_volume`) | `INSUFFICIENT_EVIDENCE` — a market with no trades knows nothing |
| prices move against every warrant introduced | `DEADLOCK` and a flag for manipulation review |

## Invariants

Preserves C-1, C-3, C-7. **Tension with C-4:** a market does not "drop" a position, but it *drowns*
one — an agent with no budget has no voice, which is a change in the social fact being measured. Equal
endowment is therefore not a parameter to tune but a commitment, and any deviation must appear in the
explanation headline.

## Failure modes

| Case | Behaviour |
| --- | --- |
| Thin market | prices are noise; `min_volume` gate forces `INSUFFICIENT_EVIDENCE` |
| Manipulation / pump | volume-weighted anomaly detection, flagged for audit |
| Unresolvable proposition | cannot be traded (`resolution_required`), so it cannot launder a vibe into a price |
| Herding into a cascade | DH-05 applies to trades as well as positions |
| Agents trading on shared evidence | correlated information, not independent — the classic overconfidence result |

## Research questions

Q-5, and the market-versus-deliberation comparison in
[RESEARCH_NOTES.md](../RESEARCH_NOTES.md). Included in the research track precisely because it is the
mechanism most likely to look impressive and mislead.

## Related

[README](README.md) · [bayesian.md](bayesian.md) · [deliberative.md](deliberative.md) ·
[EPISTEMIC_MODEL.md §9](../EPISTEMIC_MODEL.md)
