# Explainability

**Version:** 1.0 · **Status:** design
**Port:** `explain()` on `ConsensusStrategy` ([PORTS.md §6](PORTS.md)) ·
**Requirements:** FR-503 … FR-506, FR-609, FR-901, NFR-019

## 1. The standard

An explanation is adequate when a skeptical reviewer, given only the explanation and the
artifacts it links to, can find the weakest point in the reasoning. Not "understand" —
**find the weakest point**. Comprehension is the by-product; interrogability is the target.

Consequences:

- An explanation is a **structure with links**, never a paragraph. A paragraph can be fluent and
  empty; a structure cannot hide.
- Generated prose may accompany a structure but may never replace it, and is labelled as
  generated wherever it appears.
- The explanation must include the material that *undermines* the conclusion. An explanation that
  only supports is marketing.

## 2. The five explanation types

| Subject | Must include |
| --- | --- |
| **Claim** | author, epistemic status, supporting and opposing evidence with verification state, inference rule and premises, assumption closure, live defeaters, provenance completeness |
| **Position** | the agent and its role, the proposition and polarity, declared confidence with its basis, what changed since the previous round and why (`RESPONDS_TO`), dissent target |
| **Consensus** | outcome class, strategy id + version + parameters, `input_hash`, feasibility status, ranking with support values labelled as support, flip distance, unresolved blocking critiques |
| **Recommendation** | the above plus the full minority report, evidence gaps, conditions and caveats, what would change the answer, override status |
| **Metric** | formula, inputs, sample size, version, direction, caveats, and the peer metrics it must be read with |

## 3. Explanation object

```jsonc
{ "subject": { "type": "CONSENSUS_RESULT", "id": "cns_01H…" },
  "outcome": "CONDITIONAL_CONSENSUS",
  "drivers": [ { "artifact_id": "art_01H…", "contribution": "+0.21",
                 "kind": "EVIDENCE", "verification": "CROSS_CHECKED" } ],
  "inhibitors": [ { "artifact_id": "crt_01H…", "kind": "CRITIQUE",
                    "type": "CAUSAL_OVERCLAIM", "state": "UNRESOLVED" } ],
  "conditions": [ { "assumption_id": "asm_01H…", "dependents": 7 } ],
  "counterfactuals": [ { "change": "drop asm_01H…", "effect": "ranking flips" } ],
  "absent": [ "no source on regional grid headroom" ],
  "minority": [ { "agent": "ag_critic_v4", "warrant": ["art_01H…"] } ],
  "trace": "/api/v1/consensus/cns_01H…/explain",
  "generated_prose": { "text": "…", "model": "…", "label": "generated summary" } }
```

`drivers`, `inhibitors`, `conditions`, `counterfactuals` and `absent` are required keys. A key
with nothing to report contains `[]` plus a `reason_for_empty`, never a missing key — the
difference between "no evidence gaps" and "we did not look" must be visible.

## 4. Rendering rules

| Rule | Detail |
| --- | --- |
| X-1 | Every number is rendered with its unit, kind and caveats on first appearance (NFR-019) |
| X-2 | Support is labelled "support", never "confidence", "probability" or "likelihood" |
| X-3 | No composite. No radar chart that implies one. No colour encoding a hidden aggregate |
| X-4 | Dissent is rendered inline in the recommendation view, not behind a tab |
| X-5 | `UNKNOWN` solver results render as "not determined — symbolic assurance unavailable" with policy action `DEFER`, never as green, satisfied, violated, or rejected |
| X-6 | Generated prose carries a visible marker and never appears as a tooltip on a structural field |
| X-7 | Every artifact id is a link that opens the same explanation shape recursively |
| X-8 | Empty sections say why they are empty |

## 5. The "why" affordance

One interaction, everywhere: click any assertion, number, ranking row or status badge and the
platform shows the structure behind it. There is exactly one "why" path, it is present in the
payload as `meta.trace` ([API_CONTRACTS.md §3](API_CONTRACTS.md)), and it works at every depth —
including "why this weight", "why this trust level" and "why this metric moved".

A UI element that cannot answer "why" must not be rendered. This is a build-time rule in the
component contract, not a review convention.

## 6. Counterfactuals

The most interrogative question is not "why" but "what if". Every consensus explanation carries
at least one counterfactual, computed by re-running the strategy on perturbed inputs:

| Counterfactual | Method |
| --- | --- |
| Drop an assumption | remove from the soft-constraint set and re-evaluate (later Phase 11 work) |
| Remove one agent | recompute without that principal's positions |
| Remove one evidence item | recompute; shows citation load-bearing |
| Change a threshold | sweep the agreement threshold, report flip distance (CQ-03) |
| Change the strategy | run the registered alternatives (CQ-06) |

Counterfactuals are cheap because strategies are pure functions of `ConsensusContext` (S-4). A
strategy that cannot be re-run in isolation is not admissible.

## 7. Anti-patterns

| # | Pattern | Why it fails |
| --- | --- | --- |
| XP-1 | A one-line LLM summary as the whole explanation | fluent, unfalsifiable, and the reviewer cannot locate the weak point |
| XP-2 | Attention or similarity shown as "importance" | explains the model, not the reasoning |
| XP-3 | A confidence percentage with no basis | violates CF-1 and invites the probability reading |
| XP-4 | Green/red feasibility colour while the solver said `UNKNOWN` | violates X-5 |
| XP-5 | "Consensus reached: 87 %" as a headline | collapses an outcome class into a number (FR-901) |
| XP-6 | Dissent reachable only by expanding a collapsed panel | violates X-4 and, in practice, FR-506 |
| XP-7 | Prompt text exposed as the explanation | explains the plumbing, not the argument |
| XP-8 | Averaging several strategies into one "final" score | destroys the disagreement signal that is the contribution |

## 8. Tests

- **Structural:** every required key present; empty arrays carry `reason_for_empty`.
- **Recursive:** a crawl test follows `meta.trace` from the recommendation to leaf sources and
  asserts termination and no orphan links.
- **Completeness:** for a fixture session, the explanation names every unresolved blocking
  critique (CQ-05) and every dissenting agent (FR-505).
- **Determinism:** the same `input_hash` renders byte-identical structure, including ordering.
- **Counterfactual:** each §6 method returns at least one row for the fixture.
- **Labelling:** a lint over UI strings forbids "confidence", "probability" and "score" adjacent
  to a support value (X-2, XP-3).

## 9. Related

[CONSENSUS_MODEL.md](CONSENSUS_MODEL.md) · [EPISTEMIC_MODEL.md](EPISTEMIC_MODEL.md) ·
[METRICS.md](METRICS.md) · [REASONING_GRAPH.md](REASONING_GRAPH.md) ·
[API_CONTRACTS.md](API_CONTRACTS.md) · [AUDITABILITY.md](AUDITABILITY.md)

