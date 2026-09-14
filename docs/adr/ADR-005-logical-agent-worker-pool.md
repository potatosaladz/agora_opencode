<!-- trace: FR-211 -->
# ADR-005: Logical agent pool with a fixed worker fleet

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 1
**Requirements:** FR-201 … FR-208, NFR-001, NFR-013

## Context

"Agent" could mean a long-lived process with its own memory, or a role instantiated per turn. The
first is evocative and expensive: idle processes, per-agent state that no one can reproduce, and a
scaling story driven by agent count rather than load.

## Decision

Agents are **logical**: an agent definition (role, prompt, model, tools, budget) plus a stateless
`agent-worker` fleet that instantiates an agent for the duration of a turn. Conversation state lives
in the database, assembled into context per turn
([STRUCTURED_REASONING.md §7](../STRUCTURED_REASONING.md)). The fleet scales with queue depth, not
with the number of defined agents.

## Consequences

**Positive.** Worker restarts lose nothing; horizontal scaling is a `docker service scale`. An agent's
behaviour is fully determined by its definition version plus the assembled context, which is exactly
what the reproducibility manifest records. Cost follows turns, not idle processes.

**Negative.** No long-lived agent memory, so anything an agent "remembers" must be an explicit
artifact or a memory read — which is the point, but it forecloses some emergent-behaviour designs.
Context assembly becomes a hot path and needs its own caching and metrics.

**Neutral.** A persistent-agent runtime can be added later behind the same turn contract without
touching the coordinator.

## Alternatives considered

| Option | Why not |
| --- | --- |
| One process per agent | idle cost, unreproducible internal state, restart fragility |
| Actor framework (Erlang/Akka) | solves a scaling problem we do not have at MVP, and hides state in mailboxes |
| Sub-agents inside one LLM call | no independent positions, so no measurable disagreement (FR-203) |

## Links

[ARCHITECTURE.md §2](../ARCHITECTURE.md) · [AGENT_MODEL.md](../AGENT_MODEL.md) ·
[DOCKER_SWARM.md §11](../DOCKER_SWARM.md)
