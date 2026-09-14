# Strategy: `<strategy_id>`  *(mvp | research)*

**Status:** · **Class:** · **Port:** `ConsensusStrategy` · **Parent:** [README](README.md)

> Copy this file to `<strategy_id>.md` — the id registered in the strategy registry, not a prose
> title. The loader refuses to register a strategy with no document here (FR-608), and the CI check
> requires the sections below to be present and non-empty. Write the mathematics before the code:
> a strategy whose behaviour cannot be written down cannot be audited when it is wrong.

## Inputs

Which fields of `ConsensusContext` are read, and what happens when one is absent. Name the fields that
are deliberately **ignored** and say why — an undocumented omission is where a strategy's real
assumptions hide.

| Field | Used | Absent ⇒ |
| --- | --- | --- |
| `alternatives` | yes | error |

## Parameters

| Name | Type | Range | Default | Effect when moved |
| --- | --- | --- | --- | --- |

Every parameter must be recorded per session and diffed across experiments. A parameter with no stated
effect is a knob nobody will understand in six months.

## Mathematics

The computation in notation a reviewer can check by hand. Pseudocode is acceptable; a reference to a
library function is not, because the library will be upgraded and the reasoning will not.

## Outcome mapping

How numbers become one of the eight outcome classes. State explicitly which classes this strategy
**cannot** produce and what it emits instead — a strategy that can only ever return
`FULL_CONSENSUS`/`NO_CONSENSUS` is a coin flip with extra steps.

| Condition | Outcome |
| --- | --- |

## Invariants

Which of C-1 … C-8 ([CONSENSUS_MODEL.md](../CONSENSUS_MODEL.md)) it preserves, and — mandatory — **how
it could violate them**. A section that lists only preserved invariants is not a review, it is marketing.

## Worked example

A small input set with the arithmetic shown end to end. This becomes a unit test verbatim (T9-04). If
the example cannot be computed by hand, the strategy is too complex for the platform's audit promise.

## Failure modes

| Case | Behaviour |
| --- | --- |

Must include: no agents, one agent, all abstain, no evidence, contradictory evidence, all alternatives
infeasible, and every parameter at each extreme.

## Related

Links to the metrics it is expected to move, the anti-patterns it flirts with, and the sibling
strategies it is compared against.
