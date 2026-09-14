# Strategy: `weighted`

**Status:** MVP, Phase 9 · **Class:** deterministic linear aggregation ·
**Port:** `ConsensusStrategy` · **Parent:** [README](README.md)

## Inputs

Reads `alternatives`, `agent_positions` (`p`, `c`), `objectives` (`v_k`, `w_k`), `constraints`
(through `F` and `H` from the gate), `critiques`. Ignores `evidence` (see
[evidence_weighted.md](evidence_weighted.md)) and `agent_trust` — it must not be used implicitly.

## Parameters

| Name | Type | Range | Default | Effect |
| --- | --- | --- | --- | --- |
| `position_weights` | map | each in `[0,1]`, sum 1 | `SUPPORT 1.0, UNCERTAIN 0.5, OPPOSE 0.0, ABSTAIN —` | maps a position to a score |
| `use_confidence` | bool | — | `false` | whether `c(a,i)` scales the position score |
| `abstain_policy` | enum | `EXCLUDE`, `HALF` | `EXCLUDE` | how abstentions enter the denominator |
| `agreement_threshold` | float | `[0.5, 1.0]` | `0.66` | upper bound for `FULL_CONSENSUS` |
| `partial_threshold` | float | `[0, agreement_threshold)` | `0.5` | lower bound for any consensus claim |

`abstain_policy = EXCLUDE` is the default because counting abstention as half-support silently
rewards non-participation.

## Mathematics

Position score, with `s(p)` from `position_weights`:

```text
score(a, i) = s(p(a, i)) · (use_confidence ? c(a, i) : 1)

support(a)  = Σ_{i ∈ N_a} score(a, i) / |N_a|          N_a = active, non-excluded agents

value(a)    = Σ_k w_k · v_k(a)                          objectives, v_k ∈ [0,1] normalised

rank_score(a) = α · support(a) + (1 − α) · value(a)     α ∈ [0,1], default 0.5
```

`α` is the honest knob: it states how much the platform weighs *what the agents think* against *what
the objectives say*. It is recorded per session and never left implicit.

## Outcome mapping

Let `a*` be the top feasible alternative by `rank_score`, `a†` the runner-up.

| Condition | Outcome |
| --- | --- |
| `support(a*) ≥ agreement_threshold` and every agent's `p(·)` is `SUPPORT`/`ABSTAIN` and no unresolved blocking critique | `FULL_CONSENSUS` |
| `partial_threshold ≤ support(a*) < agreement_threshold` | `PARTIAL_CONSENSUS` |
| `support(a*) < partial_threshold` | `NO_CONSENSUS` |
| any `F(a) = UNKNOWN` bearing on `a*` | capped at `CONDITIONAL_CONSENSUS`; never symbolically assured |
| objectives conflict (`value` ranking contradicts `support` ranking beyond ε) | `PARETO_SET` preferred over a single winner |

## Invariants

Preserves C-1 (gate is external), C-4 (positions are read, never rewritten), C-7 (pure and
deterministic), C-3 (`explain` returns the term-by-term arithmetic above).

**How it can violate them.** With `use_confidence = true` it compares raw confidences across agents,
which CF-2 forbids — so the parameter is documented as **discouraged** and the explanation must print
CF-2's caveat whenever it is enabled. It cannot express `INSUFFICIENT_EVIDENCE` on its own: it has no
notion of evidence, which is the main reason `evidence_weighted` exists.

## Worked example

Three agents, two alternatives, `α = 0.5`, `use_confidence = false`, `abstain_policy = EXCLUDE`.

```text
a1: SUPPORT, SUPPORT, OPPOSE      → support = (1 + 1 + 0)/3 = 0.667
a2: OPPOSE,  ABSTAIN, SUPPORT     → N_a2 = {1,3} → support = (0 + 1)/2 = 0.500

objectives: a1 value = 0.40, a2 value = 0.75
rank_score: a1 = 0.5(0.667) + 0.5(0.40) = 0.533
            a2 = 0.5(0.500) + 0.5(0.75) = 0.625   → a2 leads on rank_score
```

`support(a2) = 0.500 < agreement_threshold`, so the outcome is `PARTIAL_CONSENSUS`, and the
explanation must state that the leader on `rank_score` is **not** the leader on support — the
divergence is the finding, and `α` is what produced it.

## Failure modes

| Case | Behaviour |
| --- | --- |
| All agents abstain | `|N_a| = 0` → `INSUFFICIENT_EVIDENCE`, never a division by zero or a default 0 |
| One agent active | result emitted with `degenerate_input: true` |
| Weights do not sum to 1 | rejected at registration, not renormalised silently |
| `v_k` missing for an objective | `NOT_APPLICABLE` for that objective and disclosed, not scored as 0 |
| Threshold set so high that nothing can pass | sensitivity sweep shows the ranking is threshold-bound; disclosed |

## Related

[CONSENSUS_MODEL.md](../CONSENSUS_MODEL.md) · [evidence_weighted.md](evidence_weighted.md) ·
[constraint_aware.md](constraint_aware.md) · [METRICS.md §4.4](../METRICS.md)
