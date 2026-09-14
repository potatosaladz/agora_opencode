# ADR-004: NATS as the event transport

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 1
**Requirements:** FR-301, FR-302, NFR-007, NFR-013

## Context

Committed events must fan out to the realtime gateway, the metric engine, the graph projection and
any workspace webhook, without the coordinator calling each of them. The platform needs at-least-once
delivery, subject-based routing, and consumer isolation so one slow subscriber cannot stall a round.

## Decision

NATS with JetStream for durable subjects. The coordinator publishes to
`session.{workspace}.{session_id}.committed` after the database transaction commits; subscribers use
durable consumers with their own acknowledgement state.

## Consequences

**Positive.** Small operational footprint (one binary, in-cluster), subject routing that maps cleanly
to tenancy, and per-consumer acknowledgement so a stalled webhook does not backpressure the
deliberation loop. JetStream retention gives a short replay window without becoming the ledger.

**Negative.** Another stateful service. JetStream configuration (retention, ack windows) is a
learning curve. Not a streaming platform — no long-horizon replay, which is deliberate.

**Neutral.** The database ledger remains the source of truth; NATS is transport. A lost message is a
delivery problem, never a correctness problem, because consumers can re-read from `ledger_seq`
([API_CONTRACTS.md §6](../API_CONTRACTS.md)).

## Alternatives considered

| Option | Why not |
| --- | --- |
| Kafka | durability and ordering guarantees we do not need at this scale, at a much higher ops cost |
| Redis Streams | Redis is explicitly ephemeral here (ADR-009); a transport that can lose data invites it as a store |
| PostgreSQL `LISTEN/NOTIFY` | no acknowledgement or replay, payload limits, and it couples fan-out to the primary |
| Direct in-process calls | couples the coordinator to every consumer's failure mode |

## Links

[ARCHITECTURE.md §2, §9](../ARCHITECTURE.md) · [ADR-016](ADR-016-realtime-gateway-sse-first.md) ·
[ADR-009](ADR-009-redis-ephemeral-only.md)
