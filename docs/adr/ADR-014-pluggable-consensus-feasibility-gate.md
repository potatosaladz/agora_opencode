<!-- trace: FR-602, FR-603 -->
# ADR-014: Pluggable consensus strategies behind a feasibility gate

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 9
**Requirements:** FR-601 … FR-609, FR-701

## Context

There is no correct aggregation rule. Social choice theory is largely a catalogue of impossibility
results, and each plausible rule fails in a different, interesting way. Picking one consensus algorithm
would either freeze the research or bake a single set of failures into the product. Meanwhile one
requirement is not negotiable: a violated hard constraint must never be outvoted.

## Decision

Consensus is a registry of `ConsensusStrategy` implementations behind one port, each with a formal
document in [consensus-formalism/](../consensus-formalism/) (FR-608, S-1). A **feasibility gate** runs
before any strategy: constraint sets are evaluated symbolically, `UNSAT` yields `INFEASIBLE` with an
unsat core, and no strategy may rank an infeasible alternative (C-1). A session may run several
strategies and store the results side by side.

## Consequences

**Positive.** The comparison *is* a research instrument: CQ-06 strategy divergence measures how much
the answer depends on the aggregation rule, which is a finding no fixed-algorithm system can produce.
The gate makes the one non-negotiable rule structural rather than a parameter.

**Negative.** A registry invites casual additions, so the formal-document requirement is a real cost
and must be enforced by the loader, not by review. Multiple strategies can confuse users who expect
one answer; the UI must present them as comparisons, never average them (S-3, XP-8).

**Neutral.** The default is `constraint_aware`; the others are opt-in, and the default is recorded
explicitly rather than left implicit.

## Alternatives considered

| Option | Why not |
| --- | --- |
| One fixed weighted vote | bakes in a known-bad rule and destroys the research question |
| LLM-as-judge consensus | AP-5: unverifiable, unauditable, and optimises fluency |
| Soft constraints only, no gate | violates FR-602; a high score must not buy past a hard limit |
| Learned aggregation | deferred to the research track; it would optimise the record it is graded on |

## Links

[CONSENSUS_MODEL.md](../CONSENSUS_MODEL.md) · [consensus-formalism/](../consensus-formalism/) ·
[NEURO_SYMBOLIC.md §6](../NEURO_SYMBOLIC.md) · [METRICS.md §4.4](../METRICS.md)
