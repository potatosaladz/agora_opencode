<!-- trace: NFR-003 -->
# ADR-001: PostgreSQL as the system of record

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 1
**Requirements:** NFR-003, NFR-004, FR-301 … FR-305, FR-109

## Context

The platform must store durable reasoning state — artifacts, provenance edges, the event ledger,
consensus results, knowledge entries — and must be able to reproduce any past answer exactly.
Options included a document store, an event store plus projections, a graph database, and
PostgreSQL. The workload is relational and transactional (tenancy, RLS, foreign keys, append-only
ledger with sequence numbers), the graph is traversed but not enormous per session, and the team is
one to three people who must operate what they choose.

## Decision

PostgreSQL 16 is the single system of record. Sessions and their lifecycle status, artifacts,
graph edges, the event ledger, consensus results, metrics and knowledge all live in one database,
in one transaction boundary. Temporal execution status is operational durability/diagnostic state,
not a second authority for the session lifecycle. Extensions
in use: `pgvector` (vectors), `pg_trgm` and `tsvector` (lexical search), `ltree` where hierarchy is
needed.

## Consequences

**Positive.** One consistency model; an artifact, its edges and its event commit atomically, which
is what makes the ledger trustworthy. RLS gives tenancy isolation below the application layer
(FR-109). Backups, PITR and replication are solved problems. Graph queries are recursive CTEs —
slower than a native engine at large depth, adequate at session scale.

**Negative.** Deep graph traversals (impact analysis over tens of thousands of nodes) will be
slower than Neo4j. Vector and relational data share one scaling story. No built-in horizontal
shard, so growth is vertical until a partitioning plan is executed.

**Neutral.** A graph engine may later be added as a *derived* projection, never as a second source
of truth (AP-14).

## Alternatives considered

| Option | Why not |
| --- | --- |
| Neo4j / graph DB | weak transactional fit with the ledger; a second consistency domain to operate; tenancy is manual |
| Event store (Kafka) as truth | ordering per session is what we need, not global throughput; query patterns are ad hoc |
| Document store (Mongo) | provenance is relational by nature; joins and RLS matter more than schema flexibility |
| SQLite | single-writer ceiling with concurrent sessions; no RLS |

## Links

[ARCHITECTURE.md §2](../ARCHITECTURE.md) · [DATA_MODEL.md](../DATA_MODEL.md) ·
[ADR-007](ADR-007-postgres-reasoning-graph.md) · [ADR-019](ADR-019-append-only-event-ledger.md)
