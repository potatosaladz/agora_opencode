# Strategy: `evidence_weighted`

**Status:** MVP, Phase 9 · **Class:** support weighted by verified evidence strength ·
**Port:** `ConsensusStrategy` · **Parent:** [README](README.md)

## Inputs

As [`weighted`](weighted.md), plus `evidence` (with `verification` and `trust_level`), the
`SUPPORTS`/`OPPOSES` edges each position cites, and `propositions`.

## Parameters

| Name | Range | Default | Effect |
| --- | --- | --- | --- |
| `verification_weights` | per verification state | `UNVERIFIED 0.3, SOURCE_VERIFIED 0.8, CROSS_CHECKED 1.0, DISPUTED 0.1, REJECTED 0.0` | how much a citation counts |
| `trust_multiplier` | `[0,1]` per trust level | `PRIMARY 1.0, AUTHORITATIVE 0.9, SECONDARY 0.6, COMMERCIAL 0.4, UNATTRIBUTED 0.0, SYNTHETIC 0.0` | source-quality scaling |
| `evidence_weight` `β` | `[0,1]` | `0.4` | blend between raw support and evidence-weighted support |
| `independence_cap` | int ≥ 1 | `2` | max citations counted from one publisher |
| others | as in `weighted` | | |

`UNATTRIBUTED` and `SYNTHETIC` are `0.0` because model-generated text is never evidence (FR-403).

## Mathematics

```text
w(e) = verification_weights[verif(e)] · trust_multiplier[trust(e)]

E(i, a) = Σ_{e ∈ cites(i, a), polarity = SUPPORT} w(e)   capped per publisher at independence_cap
D(i, a) = Σ_{e ∈ cites(i, a), polarity = OPPOSE}  w(e)

evid(i, a) = clamp( (E − D) / (E + D + 1), −1, 1 )        # −1 = contradicted, +1 = strongly backed
             # the +1 Laplace term means "no citations" ⇒ 0, not −1

support_ev(a) = Σ_i [ s(p(a,i)) · (1 + λ·max(0, evid(i,a))) ] / |N_a|
                λ ∈ [0,1], default 0.5 — how much backing may raise a position

support(a) = (1 − β) · support_weighted(a) + β · support_ev(a)
```

Ranking, objective blend and outcome mapping are identical to
[`weighted`](weighted.md), with one addition: if `Σ_i E(i, a*) = 0` — the leading alternative has no
verified backing at all — the outcome is `INSUFFICIENT_EVIDENCE` regardless of the arithmetic. This is
the property that distinguishes the strategy.

## Invariants

Preserves C-1, C-3, C-4, C-7. Adds a genuine implementation of `INSUFFICIENT_EVIDENCE` (C-2).

**How it can violate them.** `independence_cap` is the only defence against citation laundering; set
it high and EP-04 collapses while support rises. `verification_weights[UNVERIFIED]` above `0.0` lets a
session reach consensus on citations nobody checked — the default is deliberately low, and raising it
is a configuration change that must appear in the explanation.

## Worked example

```text
a1: 3 agents SUPPORT, citations: 1 CROSS_CHECKED/PRIMARY (w=1.0), 2 UNVERIFIED/SECONDARY (w=0.18 each)
    E = 1.0 + 0.18 + 0.18 = 1.36 → evid = 1.36/2.36 = 0.576
    per-agent multiplier = 1 + 0.5·0.576 = 1.288 → support_ev(a1) = 1.0·1.288/3 … capped at 1.0
a2: 3 agents SUPPORT, no citations at all
    E = 0 → evid = 0 → support_ev(a2) = 1.0

β = 0.4 → support(a1) = 0.6·1.0 + 0.4·1.0 = 1.0 ; support(a2) = 1.0
```

Raw support ties. The tie-break is **not** in this strategy's ranking — it is in the explanation, which
reports `E(a1) = 1.36` against `E(a2) = 0` and marks `a2` as unevidenced. A cap at `1.0` is deliberate:
evidence may rescue a position from a tie, it may not buy an override of the agents' stated positions.

## Failure modes

| Case | Behaviour |
| --- | --- |
| Zero citations anywhere | `INSUFFICIENT_EVIDENCE`, with the specific gap named |
| All citations `REJECTED` | `E = 0`, `D` excluded from the numerator; the alternative is flagged, not silently dropped |
| Same publisher cited 20 times | `independence_cap` truncates; the truncation is disclosed |
| Evidence cited against its own content | invisible to this strategy; caught by `HALLUCINATED_SOURCE` critiques, not by arithmetic |
| `trust_multiplier` all 1.0 | the strategy degenerates to `weighted`; CQ-06 will show it |

## Related

[README](README.md) · [weighted.md](weighted.md) · [constraint_aware.md](constraint_aware.md) ·
[EPISTEMIC_MODEL.md §3, §5](../EPISTEMIC_MODEL.md) · [METRICS.md §4.1](../METRICS.md)
