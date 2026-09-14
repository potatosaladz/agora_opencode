# Epistemic Model

**Version:** 1.0 · **Status:** design
**Companion:** [STRUCTURED_REASONING.md](STRUCTURED_REASONING.md) (taxonomy, terminology),
[DATA_MODEL.md §6, §8](DATA_MODEL.md), [CONSENSUS_MODEL.md](CONSENSUS_MODEL.md)
**Requirements:** FR-303, FR-309 … FR-312, FR-403, FR-406, NFR-019

## 1. The claim this document bounds

The platform does not know whether a recommendation is true. It knows, and can show, *what
each agent asserted, on what basis, with what evidence, under which assumptions, and what
would defeat it.* Everything below exists to keep that claim honest and to stop the system
from quietly upgrading assertion into knowledge.

Terminology for the six statuses (`FACT`, `CLAIM`, `ASSUMPTION`, `INFERENCE`, `OPINION`,
`HYPOTHESIS`) is defined once, in
[STRUCTURED_REASONING.md §3](STRUCTURED_REASONING.md), and is not redefined here. This
document covers **warrant, verification, trust, confidence and defeat**.

<!-- trace: FR-309 -->
## 2. Warrant

An artifact is *warranted* to the extent that its justification can be reconstructed. Warrant
is a structure, not a score:

```text
warrant(claim) =
    evidence set            (SUPPORTS / OPPOSES edges, each with provenance)
  + inference rules         (how the conclusion was drawn, and their validity)
  + assumption closure      (what must hold for the inference to go through)
  + defeat status           (unanswered attacks, contested sources)
  + provenance completeness (does every input resolve to a SOURCE?)
```

Each component is reported separately. They are **never** combined into a single "warrant
score": a claim can be fully sourced and still rest on one fragile assumption, and a single
number cannot express that (FR-901). `provenance_completeness` and `assumption_depth` in
[METRICS.md](METRICS.md) quantify individual components; neither is a measure of truth.

<!-- trace: FR-311 -->
## 3. Verification lifecycle

Applies to `evidence.verification` and, by extension, to any artifact that cites it.

| State | Meaning | Who may set it | Evidence required |
| --- | --- | --- | --- |
| `UNVERIFIED` | initial state for every new artifact | default | — |
| `SOURCE_VERIFIED` | the cited locator was fetched and says what is claimed | human, or a gateway fetch tool with recorded result | fetch digest + locator |
| `CROSS_CHECKED` | ≥ 2 independent sources agree | human or validated retrieval/symbolic check | the source pair, independence test |
| `DISPUTED` | a live, unanswered defeater exists | Critic, or impact analysis after retraction | the `ATTACKS` edge |
| `REJECTED` | defeater sustained | human decision, or a refutation of the cited content | the defeating artifact |

Rules:

- **V-1** Transitions are events. A state with no event that produced it is a defect (NFR-006).
- **V-2** An LLM may *propose* a transition; only a human action, a retrieval that fetched the
  source, or a symbolic evaluation may *commit* one (FR-403).
- **V-3** `REJECTED` never deletes. The artifact stays, flagged, because the record that the
  platform once believed it is itself data (FR-303).
- **V-4** Absence of evidence is not evidence of absence: the response is an `EVIDENCE_GAP`
  critique, never a refutation.

## 4. Confidence semantics

`confidence` on a position is an agent's **declared subjective strength**, on a bounded scale,
with a stated meaning. It is not a probability and is never treated as one.

- **CF-1** Every confidence value is accompanied by its basis: which evidence, which assumption
  set, which model. A bare number is rejected by the envelope schema.
- **CF-2** Cross-agent comparison of raw confidence is invalid. Different models, prompts and
  calibration histories produce non-comparable numbers. An aggregation strategy that consumes
  confidence must state how it handles this
  ([consensus-formalism/](consensus-formalism/)).
- **CF-3** Calibration is measured, not assumed: sessions with checkable outcomes feed the
  `calibration_error` metric. Until that metric exists for an agent, its confidence is used
  only ordinally.
- **CF-4** Confidence in a *conclusion* and confidence in the *reasoning* are separate fields;
  an agent may be sure of a position and unsure that its argument supports it.
- **CF-5** Averaging confidences into one group number is prohibited (P-1).

<!-- trace: FR-403 -->
## 5. Trust

Trust attaches to **sources and agents**, never to conclusions, and it is not a proxy for
correctness.

| Trust level (source) | Definition | Effect on weighting |
| --- | --- | --- |
| `PRIMARY` | original record, dataset or instrument output | full weight, still needs `SOURCE_VERIFIED` |
| `AUTHORITATIVE` | recognised expert or official publication | high weight |
| `SECONDARY` | reporting on a primary source | weight only as far as its own citation resolves |
| `COMMERCIAL` | interested-party publication | weight reduced, interest disclosed in the explanation |
| `UNATTRIBUTED` | no resolvable origin | may not be `EVIDENCE`; may be a `CLAIM` flagged unsupported |
| `SYNTHETIC` | model-generated | never evidence (FR-403); `AGENT_PRIOR` at best |

Agent trust state (`agent_trust`) is derived from recorded history: critique acceptance rate,
hallucinated-source count, calibration error, budget discipline. It is **advisory**: it may
weight an aggregation only when the strategy's formal document declares that it does, and the
explanation must then name the weighting. Trust is never inherited by an artifact silently.

## 6. Uncertainty

Six types, defined in [STRUCTURED_REASONING.md §6](STRUCTURED_REASONING.md), kept distinct
because the remedy differs:

| Type | Reducible by | Platform response |
| --- | --- | --- |
| `EPISTEMIC` | more evidence or better models | `EVIDENCE_GAP`, retrieval or simulation request |
| `ALEATORIC` | nothing — it is the world | distribution carried into scoring, never collapsed to a point |
| `MODEL` | a better or different model | validity domain recorded, alternative engine run |
| `MEASUREMENT` | better instruments | interval widened, sensitivity reported |
| `SEMANTIC` | disambiguation | proposition re-normalized, disagreement re-measured |
| `STRATEGIC` | nothing — it is a value conflict | Pareto analysis, minority report, human decision |

- **U-1** `STRATEGIC` uncertainty must never be aggregated away. Conflicting objectives produce
  `PARETO_SET`, not a weighted compromise (FR-607).
- **U-2** Where a distribution exists it is stored as a distribution. Point estimates carry
  their interval or a `MEASUREMENT` uncertainty.
- **U-3** Solver `UNKNOWN` is an uncertainty about the *formal* claim and is surfaced as such
  (FR-708).

## 7. Defeat

A defeater is an artifact that, if sustained, removes warrant. Three kinds:

1. **Rebutting** — evidence or a critique that opposes the claim directly (`OPPOSES`,
   `CONTRADICTS`).
2. **Undermining** — an attack on the inference rule or the assumption closure (`ATTACKS` with
   `LOGICAL_FALLACY`, `MODEL_MISUSE`, `CAUSAL_OVERCLAIM`).
3. **Source defeat** — retraction or rejection of a source, propagated by `impact_of(source)`
   ([REASONING_GRAPH.md §6](REASONING_GRAPH.md), FR-408).

Rules: **D-1** a sustained defeater sets dependents to `CONTESTED`, never to `REJECTED`
automatically. **D-2** rebuttal is not resolution: a claim that survives an attack is stronger
for it, and the exchange is part of the explanation. **D-3** an unanswered rebutting defeater on
a blocking artifact caps consensus at `PARTIAL_CONSENSUS` (C-6).

## 8. Promotion to knowledge

Session output becomes durable knowledge only through an explicit, recorded validation step
(FR-406, FR-907). Promotion copies nothing: it creates a new `knowledge_entry` that *cites* the
validated artifacts, so the provenance chain stays intact and the promotion itself is
auditable. Consensus strength is never, by itself, sufficient grounds for promotion — a
unanimous session that rested on one unverified assumption promotes nothing.

## 9. Group epistemics and their limits

The platform deliberately uses mechanisms with known failure modes, and names them:

| Mechanism | Use | Known failure | Mitigation |
| --- | --- | --- | --- |
| Sealed first assessment (FR-209) | independent judgement | costs cross-agent learning | round 1 is always `sealed: true` |
| Testimony from evidence | reach beyond an agent's weights | citation laundering, hallucinated sources | provenance required, `HALLUCINATED_SOURCE` critique |
| Expertise weighting | better than equal weights when expertise is real | entrenches wrong experts | trust advisory, calibration measured, dissent preserved |
| Deliberation across rounds | genuine persuasion | herding, sycophancy drift | disagreement-rate monitor, immutable position history |
| Prediction markets (research) | aggregate dispersed information | thin markets, manipulation | research track only, never MVP default |

## 10. Invariants

- **E-1** No artifact's epistemic status may change without an event naming the actor and the
  warrant that changed.
- **E-2** `FACT` is reachable only by human assertion or a validated symbolic evaluation; no
  LLM path writes it.
- **E-3** Every displayed number carries its type, version, inputs and caveats (NFR-019).
- **E-4** Confidence, trust, support and probability are four different things and are never
  conflated in a field name, a column or a UI label.
- **E-5** The platform must always answer "why do you believe this?" with a structure, not a
  paragraph.

## 11. Related

[RESEARCH_NOTES.md](RESEARCH_NOTES.md) (open questions) · [METRICS.md](METRICS.md) ·
[TRACEABILITY.md](TRACEABILITY.md) · [NEURO_SYMBOLIC.md](NEURO_SYMBOLIC.md) ·
[STRUCTURED_REASONING.md](STRUCTURED_REASONING.md)

