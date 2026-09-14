<!-- trace: NFR-007 -->
# ADR-016: SSE-first realtime gateway

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 4
**Requirements:** NFR-007, FR-302, FR-501

## Context

Clients need to watch a session as it unfolds: artifacts committed, rounds advancing, consensus
computed. The traffic is one-directional server→client, must survive proxies, and must be resumable
after a dropped connection because a deliberation outlives a laptop's network.

## Decision

Server-Sent Events as the primary contract, backed by the ledger's monotonic `ledger_seq` and
`Last-Event-ID` resumption. WebSocket is offered as an optional transport for the graph view, over the
same event set and the same ordering rules ([API.md §5](../API.md), EV-1 … EV-5).

## Consequences

**Positive.** SSE is plain HTTP: it passes through corporate proxies, works with the existing auth
middleware, and needs no protocol negotiation. Resumption is a `WHERE ledger_seq > ?` query, so a
reconnect cannot miss an event. Clients are simpler, and the event contract is testable with an HTTP
fixture.

**Negative.** One-way only, and the per-connection file-descriptor cost bounds concurrency — acceptable
at MVP scale, and the graph view's bidirectional needs are served by ordinary REST calls plus SSE.

**Neutral.** Making WebSocket a transport over the same events, rather than a second contract, is the
constraint that keeps this decision cheap to revisit.

## Alternatives considered

| Option | Why not |
| --- | --- |
| WebSocket only | a second protocol to authenticate, resume and test, for a one-way feed |
| Long polling | works, but wastes bandwidth and re-implements resumption badly |
| Client polling of `/events` | simplest, and the answer when SSE is blocked — kept as the fallback |
| GraphQL subscriptions | a whole new query layer to solve a delivery problem |

## Links

[ARCHITECTURE.md §2, §9](../ARCHITECTURE.md) · [API.md §5](../API.md) ·
[API_CONTRACTS.md §6](../API_CONTRACTS.md) · [ADR-004](ADR-004-nats-event-transport.md)
