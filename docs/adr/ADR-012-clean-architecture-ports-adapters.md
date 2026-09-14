<!-- trace: NFR-014 -->
# ADR-012: Clean architecture with ports and adapters

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 1
**Requirements:** NFR-014, FR-206, FR-601, FR-608

## Context

Every dependency in this system is expected to change: model providers, the vector index, the solver,
the consensus strategy, the deployment target. A research platform additionally needs to swap a
component *while measuring the effect*, which is impossible if components are entangled with their
adapters.

## Decision

A `core/` domain layer that defines ports and data contracts and imports nothing from the outside
world; `adapters/` that implement them; a composition root that wires them by configuration. The
dependency rule is enforced by an import lint, not by convention
([EXTENDING.md §2](../EXTENDING.md), AP-12).

## Consequences

**Positive.** Swapping a provider, an index or a strategy is a registration change. Every port has a
`Fake*`, which is what makes deterministic CI and `REPLAY_STRICT` possible. The port list doubles as
the architecture's table of contents.

**Negative.** More files and more indirection than a script needs; the mapping between domain types
and adapter payloads is repetitive. New contributors must learn where things live before they can add
anything.

**Neutral.** The discipline pays exactly when a provider changes pricing or a model is deprecated,
which is to say continuously.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Framework-first (LangGraph, CrewAI) | their abstractions are our invariants' opposite: opaque state, uncontrolled termination |
| Hexagonal with fewer ports | the port count is set by the number of things that will change, not by taste |
| Monolith with feature modules | no seam to swap an adapter for an experiment |

## Links

[ARCHITECTURE.md §2](../ARCHITECTURE.md) · [PORTS.md](../PORTS.md) · [EXTENDING.md](../EXTENDING.md)
