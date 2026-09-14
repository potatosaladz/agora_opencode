<!-- trace: FR-201 -->
# ADR-003: Temporal for durable workflow

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 1
**Requirements:** FR-201 … FR-212, NFR-004, NFR-013

## Context

A deliberation session runs for minutes to hours across many LLM calls, tool calls and human
pauses. Providers fail mid-round, workers restart during deploys, and a human intervention can
pause a session for days. The workflow must survive all of it without losing or duplicating a
committed step, because the ledger's total order is the basis of every audit claim.

## Decision

Use Temporal. The session is a workflow; each round is a sequence of activities (assemble context,
invoke agent, parse envelope, commit artifacts, evaluate constraints, run consensus). Retries,
timeouts, heartbeats and compensation are declared per activity. Human pauses are signals, not
polling loops.

## Consequences

**Positive.** Crash-proof execution with deterministic replay of the workflow code, which matches
the platform's own reproducibility requirement. Long-lived waits are cheap. Versioning of workflow
code is built in, so a deploy does not orphan running sessions
([DEPLOYMENT.md §7](../DEPLOYMENT.md)).

**Negative.** A new stateful service with its own database and operational learning curve.
Workflow determinism rules constrain the code (no wall clock, no random, no direct I/O in the
workflow body) and are a common source of first-time bugs. Local development needs the Temporal
dev server.

**Neutral.** The determinism discipline is a benefit in disguise: it is the same discipline
[REPRODUCIBILITY.md](../REPRODUCIBILITY.md) requires anyway.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Celery / task queue chains | no durable state, no replay; a failed chain leaves an orphaned half-round |
| Step Functions / cloud-native | couples the deployment to one cloud; Swarm is the target (ADR-011) |
| Airflow | batch-oriented DAG scheduling, not long-running interactive sessions |
| Hand-rolled state machine | we would rebuild Temporal badly, and the ledger would be the loser |

## Links

[ARCHITECTURE.md §3](../ARCHITECTURE.md) · [AGENT_PROTOCOLS.md](../AGENT_PROTOCOLS.md) ·
[ADR-020](ADR-020-stateful-ha-boundary.md)
