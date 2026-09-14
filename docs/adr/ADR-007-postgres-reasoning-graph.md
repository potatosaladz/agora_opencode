# ADR-007: PostgreSQL property graph for the reasoning graph

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 3
**Requirements:** FR-301 … FR-308, FR-408, NFR-003

## Context

The reasoning graph is typed, small-per-session (hundreds to low thousands of nodes), and must be
transactionally consistent with the artifacts it connects. Impact analysis is a recursive traversal
with edge-type filters, not a centrality computation over billions of edges.

## Decision

Model the graph as relational tables — `graph_nodes`, `graph_edges` with `(src, dst, type, basis,
created_by, created_at)` — plus recursive CTEs for traversal, indexed on `(src, type)` and
`(dst, type)`. Path queries use a bounded-depth CTE with cycle detection. No graph database.

## Consequences

**Positive.** Edges commit in the same transaction as their endpoints, so a provenance edge can never
point at a nonexistent artifact. RLS applies to edges automatically. Impact traversal is one query
and one plan, testable with fixtures.

**Negative.** Multi-hop queries beyond depth ~6 get expensive; graph analytics (community detection,
centrality) are awkward in SQL.

**Neutral.** If analytics become a requirement, a graph projection is built *from* the ledger as a
derived store — never as a second source of truth (AP-14).

## Alternatives considered

| Option | Why not |
| --- | --- |
| Neo4j | a second consistency domain for a graph that must be transactionally identical to its nodes |
| Apache AGE | adds an extension dependency; recursive CTEs already cover the query shapes we need |
| In-memory NetworkX per request | no persistence, no tenancy, rebuild cost on every call |
| Adjacency JSON on the artifact row | unqueryable in both directions; impact analysis becomes a scan |

## Links

[REASONING_GRAPH.md](../REASONING_GRAPH.md) · [DATA_MODEL.md §9](../DATA_MODEL.md) ·
[ADR-001](ADR-001-postgres-source-of-truth.md)
