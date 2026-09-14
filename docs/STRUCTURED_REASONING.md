# Structured Reasoning Model

**Version:** 1.0 · **Status:** design · the terms defined here are used by every other document
**Companions:** [REASONING_GRAPH.md](REASONING_GRAPH.md), [DATA_MODEL.md](DATA_MODEL.md),
[CONSENSUS_MODEL.md](CONSENSUS_MODEL.md), [EPISTEMIC_MODEL.md](EPISTEMIC_MODEL.md)

## 1. The core commitment

Reasoning is stored as **typed, attributable, linkable artifacts** — never as chat
transcript. Prose is a *rendering* of artifacts, produced on demand. If a statement cannot
be typed, it is not part of the reasoning record.

Three consequences:

1. Disagreement is machine-readable, because positions attach to the same proposition.
2. Consensus is computable, because support is a function over typed inputs.
3. Errors are local, because a retracted source propagates along explicit edges.

## 2. Artifact taxonomy

| Artifact | What it is | Must carry | Never carries |
| --- | --- | --- | --- |
| **Fact** | a verified statement about the world | source, locator, verification status, retrieved_at | model confidence |
| **Claim** | an assertion that may be supported or attacked | author, type, direction, strength, evidence refs | the status "fact" by default |
| **Assumption** | a statement accepted without proof to proceed | basis, materiality, challengeable flag | — |
| **Inference** | a derivation from premises to conclusion | premise ids, rule kind, rule text, validity | — |
| **Proposition** | the normalized, testable content of a statement | natural-language **and** normalized form, kind, modality | — |
| **Evidence** | a provenanced item bearing on a claim | provenance kind, quote, locator, trust, verification, weight | auto-verified status |
| **Uncertainty** | a qualified gap attached to a target | type, representation, interval/distribution, drivers | a single scalar |
| **Risk** | an adverse possibility with probability and impact | probability, impact, unit, timescale, affected objectives | — |
| **Impact** | a modelled effect of an alternative on an objective | magnitude, unit, timeframe, source | — |
| **Objective** | a valued direction of improvement | kind, direction, weight, rationale, horizon | — |
| **Constraint** | a limit an acceptable answer must respect | constraint type (HARD/SOFT/NON_NEGOTIABLE), category, NL statement, formal status | enforcement before validation |
| **Alternative** | a candidate course of action | components, origin, feasibility status | selection without feasibility |
| **Position** | an agent's stance on a target | stance, confidence, rationale, evidence ids, conditions | silence |
| **Critique** | an attack on an artifact | type, severity, argument, response, resolution | deletion of the target |

This table is the complete Phase 3 set of 14 persisted artifact kinds. `Position` is the persisted
name for opinion. A hypothesis is a `Claim` whose `claim_type` is `HYPOTHESIS`; neither is a fifteenth
artifact kind. `Assessment`, `CounterArgument`, `SimulationResult`, `Recommendation` and `Decision`
are later-phase composites or artifacts and are not part of Phase 3 storage.

<!-- trace: FR-103, FR-301, FR-304, FR-306 -->
## 3. Fact / claim / assumption / inference / opinion / hypothesis

These six are frequently conflated. The distinctions are load-bearing.

| | Truth status | Justification | Attributable to | Can it be evidence? |
| --- | --- | --- | --- | --- |
| **Fact** | verified against a source | source + locator | the source | yes, with provenance |
| **Claim** | asserted | may be none yet | an author | no — it is what evidence bears on |
| **Assumption** | stipulated | pragmatic, declared | an author | no |
| **Inference** | derived | premises + rule | the derivation | no, unless premises are facts and the rule is valid |
| **Opinion** | preferred | values, not evidence | an author or stakeholder | no, but it *is* a Position input to consensus |
| **Hypothesis** | untested | explanatory promise | an author | no — it generates tests |

Rules the implementation must enforce:

- **F-1** An artifact's kind is immutable across its version chain. A semantic reclassification
  creates a new logical artifact linked by `DERIVED_FROM`; `SUPERSEDES` is same-kind revision only.
- **F-2** `Fact` requires `verification IN ('SOURCE_VERIFIED','CROSS_CHECKED')` and at least one
  envelope `source_references[]` entry containing non-empty `reference`, `locator`, `content_hash`
  and `retrieved_at`. These are opaque, immutable provenance values in Phase 3. Phase 5 may resolve
  them to source/document/chunk rows; no Phase 5 foreign key is required. No source reference, no fact.
- **F-3** LLM output defaults to `Claim`. A human or verified service may create a distinct `Fact`
  derived from it; the action is audited. An agent or policy actor may not own a `Fact`.
- **F-4** An `Inference` with `validity = 'INVALID'` stays in the graph — it is evidence
  *about the reasoning*, not support for its conclusion.
- **F-5** Opinions are represented as `Position` artifacts, never as `Evidence`.
- **F-6** Hypotheses are represented as `Claim` artifacts with `claim_type = 'HYPOTHESIS'`.

## 4. Proposition normalization

A proposition is the unit that disagreement is measured on. Normalization is
**subject–predicate–object–modifier–qualifier**, not free text:

```json
{ "statement_nl":   "Unemployment falls by roughly 1.5pp within 3 years",
  "statement_norm": "delta(unemployment, 3y) ~= -1.5pp",
  "kind":           "PREDICTIVE",
  "modality":       "ASSERTED",
  "qualifiers":     { "horizon": "3y", "population": "national",
                      "confidence_band": [-2.4, -0.6] } }
```

- **P-1** Two propositions are *the same* for consensus purposes iff their normalized forms
  match after canonicalization (units, ranges, scope, modality).
- **P-2** Canonicalization is deterministic and versioned; the canonicalizer version is
  recorded, because it changes results.
- **P-3** If canonicalization is ambiguous, the artifact is `AMBIGUOUS` and MUST NOT enter
  consensus until resolved.
- **P-4** Normalization is proposed by an LLM and **validated by a human or a symbolic
  check** before it becomes the basis of an enforceable constraint.

## 5. Evidence discipline

- **E-1** Evidence is *candidate*, not established. `verification` starts `UNVERIFIED`.
- **E-2** Every evidence row answers: where, when, who retrieved it, how much it counts.
- **E-3** Weight is a function of trust level, recency, directness and relevance — never of
  how much the claim likes it. Weight assignment is deterministic and versioned.
- **E-4** A claim with zero evidence is legal and MUST render as unsupported.
- **E-5** Contradicting evidence is never dropped. Omission is a `BLOCKING` critique
  (`EVIDENCE_GAP`, `ALTERNATIVE_OMITTED`).
- **E-6** Simulation output is evidence about the model, not the world
  ([SIMULATION_ARCHITECTURE.md](SIMULATION_ARCHITECTURE.md)).
- **E-7** Historical consensus is not evidence. Prior sessions may inform an `Assumption` whose
  provenance origin is `HISTORICAL_SESSION`; they MUST NOT produce an `Evidence` artifact.

## 6. Uncertainty semantics

Six types, because collapsing them destroys the useful part.

| Type | Reducible by | Reporting |
| --- | --- | --- |
| `EPISTEMIC` | more evidence | interval + what would narrow it |
| `ALEATORIC` | nothing (intrinsic) | distribution |
| `MODEL` | a better model | which model, sensitivity |
| `MEASUREMENT` | better instruments | error band on the input |
| `SEMANTIC` | agreement on definitions | the disputed definition |
| `STRATEGIC` | — (other agents act) | scenario set |

- **U-1** A scalar confidence is a display convenience; the record keeps the representation.
- **U-2** Propagation through `Inference` is explicit: deductive preserves, inductive
  attenuates, abductive is defeasible. The attenuator is versioned, not vibes.
- **U-3** `UNKNOWN` from a solver or a failed simulation is a first-class value and MUST NOT
  be coerced to zero or one.

## 7. Rounds and turns

A **round** is a coordinator-owned epoch:
`ASSESS → DECOMPOSE → ARGUE → CRITIQUE → REVISE → SCORE → CONVERGE?`.
Turns inside a round are agent-scoped and ordered by the coordinator. Round numbers are
monotonic and gapless per session, and a round advances only by a ledger event. Agents never
decide that a round is over.

## 8. Anti-corruption rules

| Temptation | Prohibition |
| --- | --- |
| Store the LLM's prose and parse later | the parse *is* the artifact; store it |
| Use one float for confidence everywhere | typed uncertainty (§6) |
| Let an agent mark its own claim `FACT` | F-2, F-3 |
| Compare positions by string equality | P-1 |
| Average confidences into a single score | no-single-score rule, [METRICS.md](METRICS.md) |
| Delete a refuted claim | set payload `review_status = 'REJECTED'`; lifecycle remains `ACTIVE` |
| Treat absence of evidence as evidence of absence | raise `EVIDENCE_GAP`, do not refute |
| Let consensus strength imply truth | support is a social quantity; see [EPISTEMIC_MODEL.md](EPISTEMIC_MODEL.md) |

