# Strategy: `deliberative`  *(research)*

**Status:** research, Phase 16 · **Class:** position revision with judgement aggregation ·
**Port:** `ConsensusStrategy` + `ConvergenceStrategy` · **Parent:** [README](README.md)

## Idea

Unlike the MVP strategies, which aggregate positions as given, `deliberative` models the *change* of
positions across rounds and asks whether the final state is the product of persuasion or of pressure.
It is the strategy that makes the project's central question measurable.

## Inputs

Round-indexed positions `p_t(a,i)`, the `RESPONDS_TO` edges linking a revision to the critique that
triggered it, new evidence committed between rounds, and unresolved critiques.

## Parameters

| Name | Default | Effect |
| --- | --- | --- |
| `require_warrant_for_revision` | `true` | a flip with no `RESPONDS_TO` edge is counted, not prevented |
| `anchoring_penalty` | `0.3` | discount applied to support that emerged only after the majority was visible |
| `min_rounds_sealed` | `1` | rounds in which positions are sealed (FR-209) |
| `oscillation_limit` | `2` | reversals before `DEADLOCK` is considered |

## Mathematics

```text
warranted_revision(i, a, t) = 1 iff p_t ≠ p_{t−1} and ∃ RESPONDS_TO edge to a critique or evidence

support(a, T) = Σ_i s(p_T(a,i)) · (1 − anchoring_penalty · (1 − warranted_revision(i, a, ·))) / |N|

herding(a)    = share of agents whose final position matches the round-1 majority
                with warranted_revision = 0
```

`herding` is not a penalty applied to the ranking; it is a **disclosed property of the outcome**. The
strategy refuses to correct the social process it is measuring, because correcting it would hide it.

## Outcome mapping

As [`weighted`](weighted.md), plus: `DEADLOCK` when oscillation exceeds `oscillation_limit`;
`NO_CONSENSUS` when a proposition is disputed by agents whose positions are both warranted; and a
mandatory `herding` field in every explanation.

## Invariants

Preserves C-1 … C-8. **Risk to C-4:** a strategy that *models* revision is one step from one that
*induces* it. The implementation must never write or reshape a position; the coordinator owns round
mechanics, and this strategy reads them.

## Failure modes

| Case | Behaviour |
| --- | --- |
| Single round | degenerates to `weighted`; `degenerate_input: true` |
| Positions flip with no stated reason | counted as unwarranted, disclosed, and DH-05 rises |
| A critique exists but no agent responds | attack coverage (DH-03) reports it; the strategy stays silent |
| Anchoring penalty tuned to hide herding | the parameter is recorded and diffed across experiments |

## Research questions

Q-1, Q-3, Q-5 in [RESEARCH_NOTES.md](../RESEARCH_NOTES.md). The comparison against
`constraint_aware` on identical inputs is the experiment; CQ-06 divergence is the headline result.

## Related

[README](README.md) · [weighted.md](weighted.md) · [EPISTEMIC_MODEL.md §9](../EPISTEMIC_MODEL.md) ·
[METRICS.md §4.3](../METRICS.md)
