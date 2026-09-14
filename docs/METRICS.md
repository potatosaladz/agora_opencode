# Metrics

**Version:** 1.0 · **Status:** design · catalogue implemented (T13-01)
**Port:** `MetricPlugin` ([PORTS.md §10](PORTS.md)) · **Storage:** `metric_values`
([DATA_MODEL.md §11](DATA_MODEL.md)) · **Requirements:** FR-901, FR-902, NFR-019, NFR-005

<!-- trace: FR-901 -->
## 1. The no-single-score rule

**FR-901:** a single aggregate quality score MUST NOT exist. There is no "session score", no
"reasoning index", no composite trust number. The unit of reporting is a **profile**: a set of
named, typed, individually interpretable measurements grouped by dimension.

The reason is structural, not stylistic. The platform's object is *defensibility under
interrogation*, and every useful signal here is in tension with at least one other: agreement
rises when agents herd, evidence coverage rises when agents attach weak citations, contradiction
density falls when dissent is suppressed. A composite would hide exactly the trade-offs that
constitute the research contribution.

<!-- trace: FR-902, NFR-019 -->
## 2. Admission rules for a metric

A metric is admissible only if its `MetricDefinition` states all six, and the definition is
versioned:

| Field | Requirement |
| --- | --- |
| `formula` | computable expression over named inputs; no prose |
| `inputs` | artifact types and fields consumed, with their own versions |
| `range` | including whether it is bounded, and what the bounds mean |
| `direction` | `HIGHER_BETTER`, `LOWER_BETTER`, or `NO_DIRECTION` (descriptive only) |
| `interpretation` | one sentence a non-specialist can act on |
| `caveats` | at least one; a metric with no known failure mode is not understood well enough |

Additional rules:

- **M-1** `NO_DIRECTION` is a legitimate and common answer. Most metrics here are descriptive.
- **M-2** Every `MetricValue` carries `sample_size`, `inputs_hash`, `code_version` and
  `computation_trace`. A number without them may not be rendered (NFR-019).
- **M-3** Metrics are computed from committed artifacts only. Never from prompt text, model
  internals or chain-of-thought (NFR-011).
- **M-4** A metric that cannot be computed emits `NOT_APPLICABLE` with a reason, never `0`.
- **M-5** Thresholds are configuration, not constants, and are recorded per experiment.

## 3. Profile dimensions

```text
Evidence & provenance   →  is the reasoning anchored in anything?
Reasoning rigour        →  do the steps hold up?
Disagreement health     →  was the adversarial part actually working?
Consensus quality       →  how much agreement, and how fragile?
Robustness              →  does the answer survive perturbation?
Cost & efficiency       →  what did it take?
Human oversight         →  who was watching, and did it matter?
Calibration             →  did the stated confidence track reality?
```

A profile is rendered as a radar-free table plus per-dimension sparklines; the UI MUST NOT
compute a mean across dimensions ([EXPLAINABILITY.md](EXPLAINABILITY.md) §4).

## 4. Catalogue

Identifier pattern: `<dimension>-<nn>`. `dir` = direction. All formulas are over the artifact
sets of a single session unless stated.

> **Executable authority.** The catalogue is shipped as `MetricDefinition`s in
> `backend/app/application/metrics.py`, registered immutably via `MetricCatalogue`
> (`backend/app/domain/metrics.py`). Each definition carries `inputs` and `interpretation`
> in full — the two fields the tables below abbreviate — and the registered definitions are
> checked field-by-field against this catalogue by `backend/tests/unit/test_metric_catalogue.py`
> (T13-01). Computation and storage remain design (METRICS.md §6).

### 4.1 Evidence and provenance

| ID | Metric | Formula | Range | dir | Caveats |
| --- | --- | --- | --- | --- | --- |
| EP-01 | evidence coverage | claims with ≥ 1 `SUPPORTS` / total claims | [0,1] | HIGHER | rises trivially if agents attach weak evidence; read with EP-03 |
| EP-02 | provenance completeness | artifacts with an unbroken chain to `SOURCE` / total artifacts | [0,1] | HIGHER | a chain to an `UNATTRIBUTED` source is still a chain |
| EP-03 | verified evidence ratio | evidence in `SOURCE_VERIFIED`/`CROSS_CHECKED` / all evidence | [0,1] | HIGHER | low values are normal early in a session |
| EP-04 | source independence | mean distinct publishers per claim's support set | ≥ 0 | HIGHER | citation laundering defeats it; see EP-05 |
| EP-05 | hallucinated source rate | sustained `HALLUCINATED_SOURCE` critiques / cited sources | [0,1] | LOWER | per-agent breakdown is the useful view |
| EP-06 | evidence gap count | open `EVIDENCE_GAP` critiques at terminal round | ≥ 0 | LOWER | count weighted by the materiality of the blocked claim |

### 4.2 Reasoning rigour

| ID | Metric | Formula | Range | dir | Caveats |
| --- | --- | --- | --- | --- | --- |
| RR-01 | unsupported claim ratio | claims with empty support and empty opposition / total claims | [0,1] | LOWER | some unsupported claims are honest hypotheses; check `kind` |
| RR-02 | assumption depth | mean `assumption_closure` size over alternatives | ≥ 0 | LOWER | deep closures mean fragile conclusions, not wrong ones |
| RR-03 | inference validity rate | inferences whose recorded rule passes the structural check / total inferences | [0,1] | HIGHER | structural validity ≠ soundness |
| RR-04 | contradiction density | `CONTRADICTS` edges / claim pairs | [0,1] | NO_DIRECTION | low density can mean groupthink |
| RR-05 | formalization rate | constraints with authoritative `validation_status = VALIDATED` / hard constraints | [0,1] | HIGHER | only meaningful where formalization is possible |
| RR-06 | feasibility pass rate | alternatives `SAT` / evaluated alternatives | [0,1] | NO_DIRECTION | a low rate may mean honest constraints |
| RR-07 | solver unknown rate | `UNKNOWN` evaluations / hard-constraint evaluations | [0,1] | LOWER | rising values signal over-ambitious rule sets |

### 4.3 Disagreement health

| ID | Metric | Formula | Range | dir | Caveats |
| --- | --- | --- | --- | --- | --- |
| DH-01 | initial disagreement | propositions with a non-degenerate position vector after round 1 | [0,1] | HIGHER | zero disagreement across five agents is suspicious, not reassuring |
| DH-02 | disagreement retention | dissenting positions present in the final result / dissenting positions at round 2 | [0,1] | NO_DIRECTION | collapse to zero suggests herding; read with DH-05 |
| DH-03 | attack coverage | claims with ≥ 1 `ATTACKS` edge / total claims | [0,1] | HIGHER | the Critic's own recall metric; a Critic that attacks nothing fails its purpose |
| DH-04 | critique resolution rate | critiques in a resolved state / total critiques | [0,1] | HIGHER | `REJECT_WITH_JUSTIFICATION` counts as resolved only with a warrant |
| DH-05 | herding index | share of round-1 positions that flip toward the majority with no new evidence edge | [0,1] | LOWER | the most important anti-sycophancy signal |
| DH-06 | revision quality | flips accompanied by a `RESPONDS_TO` edge / all flips | [0,1] | HIGHER | distinguishes persuasion from capitulation |
| DH-07 | minority report substance | distinct warrants offered by dissenters | ≥ 1 | NO_DIRECTION | descriptive; rendered verbatim |

### 4.4 Consensus quality

| ID | Metric | Formula | Range | dir | Caveats |
| --- | --- | --- | --- | --- | --- |
| CQ-01 | support margin | top alternative support − runner-up support | ≥ 0 | HIGHER | meaningless when the outcome is `PARETO_SET` |
| CQ-02 | outcome class | `ConsensusResult.outcome` | enum | NO_DIRECTION | the headline; never reduced to a number |
| CQ-03 | flip distance | smallest input perturbation that changes the ranking | ≥ 0 | HIGHER | computed by sensitivity sweep; the honesty metric of the ranking |
| CQ-04 | abstention rate | `ABSTAIN` turns / expected turns | [0,1] | NO_DIRECTION | high abstention with high consensus means an under-informed room |
| CQ-05 | blocking critique carry-over | unresolved blocking critiques at terminal round | ≥ 0 | LOWER | each must appear in the explanation (FR-504) |
| CQ-06 | strategy divergence | pairwise rank correlation across strategies run on the same inputs | [−1,1] | NO_DIRECTION | low correlation is a finding, not an error |

### 4.5 Robustness

| ID | Metric | Formula | Range | dir | Caveats |
| --- | --- | --- | --- | --- | --- |
| RB-01 | ranking stability | Kendall τ of the ranking across ≥ 3 seeds or replay modes | [−1,1] | HIGHER | requires the experiment harness |
| RB-02 | assumption sensitivity | share of the recommendation's support that depends on one assumption | [0,1] | LOWER | single-point-of-failure detector |
| RB-03 | model divergence | spread of simulated outcomes across engines | ≥ 0 | LOWER | large spread with narrow intervals means over-confidence |
| RB-04 | retrieval robustness | share of cited chunks still retrieved under paraphrased queries | [0,1] | HIGHER | proxy for recall without ground truth |
| RB-05 | degraded-state frequency | count of `RAG_FAILED`, provider outage and solver timeout events | ≥ 0 | LOWER | a session that never degraded was probably not stressed |

### 4.6 Cost and efficiency

| ID | Metric | Formula | Range | dir | Caveats |
| --- | --- | --- | --- | --- | --- |
| CE-01 | tokens per committed artifact | total tokens / artifacts committed | ≥ 0 | LOWER | cheap artifacts are easy to produce; read with RR-01 |
| CE-02 | rounds to terminal | rounds consumed | ≥ 1 | NO_DIRECTION | budget exhaustion is a termination reason, not efficiency |
| CE-03 | cost per session | sum of provider cost estimates | ≥ 0 | LOWER | compare only within a fixed configuration |
| CE-04 | p95 read latency | API read latency excluding LLM time | ms | LOWER | NFR-007 target 300 ms |
| CE-05 | event delivery lag | SSE delivery time − ledger commit time | ms | LOWER | NFR-007 target 1 s |

### 4.7 Human oversight

| ID | Metric | Formula | Range | dir | Caveats |
| --- | --- | --- | --- | --- | --- |
| HO-01 | intervention rate | human events / total events | [0,1] | NO_DIRECTION | both extremes are worth explaining |
| HO-02 | override rate | overridden recommendations / recommendations | [0,1] | NO_DIRECTION | every override stays visible downstream (FR-803) |
| HO-03 | explanation engagement | drill-downs per recommendation view | ≥ 0 | NO_DIRECTION | a usage signal, not a quality signal |
| HO-04 | unexamined acceptance | recommendations accepted with zero provenance traversal | [0,1] | LOWER | the rubber-stamp detector |

### 4.8 Calibration

| ID | Metric | Formula | Range | dir | Caveats |
| --- | --- | --- | --- | --- | --- |
| CA-01 | calibration error | mean signed gap between declared confidence and outcome frequency, per agent | [−1,1] | LOWER | needs checkable outcomes; `NOT_APPLICABLE` in most MVP sessions |
| CA-02 | Brier score | mean squared error between declared probability and realized outcome | [0,2] | LOWER | applies only where a genuine probability was declared, never to confidence (CF-2) |
| CA-03 | overreach rate | high-confidence claims with `provenance_completeness = 0` | [0,1] | LOWER | the practical MVP proxy for CA-01 |

## 5. Thresholds and alerting

Thresholds are per-profile configuration, versioned with the experiment, never hard-coded. MVP
defaults exist to catch regressions, not to certify quality.

| Metric | Warn | Block gate | Basis |
| --- | --- | --- | --- |
| EP-05 | > 0.05 | > 0.15 | hallucinated citations lose trust fastest |
| DH-03 | < 0.5 | < 0.25 | a Critic that attacks little is decorative |
| DH-05 | > 0.3 | > 0.5 | herding above this level invalidates the consensus claim |
| CQ-05 | ≥ 1 | ≥ 3 | unresolved blocking critiques must be surfaced |
| RR-07 | > 0.2 | > 0.5 | the solver giving up is a design signal |
| CE-04 | > 300 ms | > 1 s | NFR-007 |

A blocked gate is recorded in [../project/ERRORS.md](../project/ERRORS.md) with the metric
version and `inputs_hash`.

## 6. Computation and storage

- Computed by `MetricPlugin` implementations invoked by the coordinator at round boundaries and
  at session termination, and on demand by the experiment harness.
- Persisted to `metric_values` with `metric_id`, `metric_version`, `subject` (session, agent,
  alternative or claim), `value`, `interval`, `sample_size`, `inputs_hash`, `code_version` and
  `computation_trace`.
- Recomputation is idempotent: the same `inputs_hash` plus `metric_version` yields the same
  value, so a re-run is a diff rather than a replacement (NFR-003).
- Profiles are assembled by query, not stored as a blob, so a new metric can appear in the view
  of an old session without touching that session's data.

## 7. Gaming

Every metric here can be improved by behaviour that makes the platform worse. This table is a
required part of the design review for each addition.

| Metric | Cheap way to game it | Counter-measure |
| --- | --- | --- |
| EP-01 | attach one weak citation to every claim | always shown next to EP-03 and RR-01 |
| DH-03 | Critic attacks only trivial claims | severity weighting plus target distribution |
| DH-04 | resolve critiques by rejecting them | DH-06 requires a warrant for a rejection |
| CQ-01 | raise the agreement threshold | thresholds are recorded and diffed across experiments |
| CE-01 | produce fewer, shorter artifacts | read with RR-01 and EP-01 |
| HO-04 | train users to click through | never a target, only a warning sign |

## 8. Adding or retiring a metric

1. Write the `MetricDefinition` with all six fields and at least one caveat.
2. Add it to this catalogue under the next free ID in its dimension, and fill the gaming row.
3. Implement the plugin and register it in the composition root (NFR-014).
4. Add a unit test with a hand-computed expected value, plus a property test asserting M-4.
5. Retire by marking `deprecated` with the successor's ID. Deprecated values stay queryable;
   they are never silently removed, because old experiment reports cite them.

## 9. Related

[EXPERIMENTATION.md](EXPERIMENTATION.md) · [REPRODUCIBILITY.md](REPRODUCIBILITY.md) ·
[REASONING_GRAPH.md §9](REASONING_GRAPH.md) · [EPISTEMIC_MODEL.md](EPISTEMIC_MODEL.md) ·
[PORTS.md §10](PORTS.md) · [TESTING.md](TESTING.md)



