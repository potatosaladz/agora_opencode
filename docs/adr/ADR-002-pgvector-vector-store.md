# ADR-002: pgvector as the initial vector store

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 5
**Requirements:** FR-401 … FR-409, NFR-010, NFR-014

## Context

Retrieval needs similarity search over document chunks, filtered by namespace and permission
before scoring (FR-404). A dedicated vector database would add a second consistency domain, a
second backup story and a second place where tenancy can leak. Corpus size at MVP scale is
millions of chunks, not billions.

## Decision

Use `pgvector` inside the system-of-record database, behind the `VectorStore` port
([PORTS.md §9](../PORTS.md)). The implemented adapter uses a cosine IVFFlat index on derived
`vector_items`. Phase 5 UUID columns resolve each typed row to its namespace, chunk, document and source,
so provenance validation and permission filtering remain SQL predicates under forced RLS. This physical
name/index choice records D-037 and supersedes the pre-implementation `chunk_embeddings`/HNSW sketch.

## Consequences

**Positive.** Permission pre-filtering is structural rather than a two-step dance that leaks
existence through ranking. One transaction covers chunk, embedding and provenance. Re-indexing is a
SQL operation with a shadow table and an alias swap
([RAG_ARCHITECTURE.md §8](../RAG_ARCHITECTURE.md)).

**Negative.** IVFFlat needs representative training data and probe tuning; recall under changing data
can degrade until index maintenance. Vector search competes for the same resources as the ledger.

**Neutral.** Because the port exists, a dedicated store (Qdrant, Weaviate) becomes an adapter, not a
migration. The trigger to revisit is measured, not guessed: index build time > 30 min or recall
degradation above the tolerance set in the experiment config.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Qdrant / Weaviate / Milvus | second source of truth for permission state; dual-write hazard; more ops than the team can carry |
| Elasticsearch dense vectors | a whole additional cluster for a capability Postgres already has; lexical arm already covered by `pg_trgm` |
| In-process FAISS | no multi-service consistency, no tenancy boundary, restart cost |

## Links

[ADR-001](ADR-001-postgres-source-of-truth.md) · [RAG_ARCHITECTURE.md](../RAG_ARCHITECTURE.md) ·
[PORTS.md §9](../PORTS.md)
