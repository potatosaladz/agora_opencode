# ADR-009: Redis is ephemeral state only

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 1
**Requirements:** NFR-003, NFR-004, FR-303

## Context

Redis is the easiest place to put something that must not be lost, because the loss is silent and the
failure surfaces much later, in an answer nobody can reproduce.

## Decision

Redis holds only working state rebuildable from the ledger: retrieval caches, rate counters, locks,
in-flight turn scratch, SSE subscription state. TTL ≤ 24 h, persistence disabled, and no Redis key is
the sole record of anything.

## Consequences

**Positive.** A Redis outage costs latency and money, never correctness
([MEMORY_ARCHITECTURE.md §8](../MEMORY_ARCHITECTURE.md)). Backups reduce to one store. The rule is
testable: flush Redis during the chaos drill and the session must still replay.

**Negative.** Anything genuinely hot must be served from Postgres or an in-process cache, which is
slower than the Redis answer would have been.

**Neutral.** The temptation to relax this is strongest exactly when it is most dangerous.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Redis as session store | violates single source of truth (AP-13, AP-14) |
| Redis Streams as the event bus | a transport that can lose data invites it to become a store (ADR-004) |
| No Redis at all | counters and locks would contend with the ledger on Postgres |

## Links

[ARCHITECTURE.md §9](../ARCHITECTURE.md) · [MEMORY_ARCHITECTURE.md](../MEMORY_ARCHITECTURE.md) ·
[ADR-004](ADR-004-nats-event-transport.md)
