# Architecture Decision Records

An ADR records a decision that is expensive to reverse, the alternatives that were rejected, and the
consequences accepted. **Accepted ADRs are immutable.** To change a decision, write a new ADR that
supersedes it and update the status line of the old one.

## Format

```markdown
# ADR-NNN: <title>
**Status:** proposed | accepted | superseded by ADR-MMM · **Date:** · **Phase:**
**Requirements:** FR-/NFR- ids
## Context        what forces the decision, in facts not preferences
## Decision       the choice, stated so a reader could implement it from this section alone
## Consequences   positive / negative / neutral — the negative section is mandatory
## Alternatives   each option with the reason it lost
## Links
```

Rules: an ADR that names no rejected alternative was not a decision. An ADR whose negative
consequences section is empty has not been read critically. An ADR that changes who may commit an
artifact, adds a stateful service, or moves a trust boundary must be cross-linked from
[THREAT_MODEL.md](../THREAT_MODEL.md).

## Index

| # | Decision | Status | Phase |
| --- | --- | --- | --- |
| [001](ADR-001-postgres-source-of-truth.md) | PostgreSQL as the system of record | accepted | 1 |
| [002](ADR-002-pgvector-vector-store.md) | pgvector as the initial vector store | accepted | 5 |
| [003](ADR-003-temporal-durable-workflow.md) | Temporal for durable workflow | accepted | 1 |
| [004](ADR-004-nats-event-transport.md) | NATS as the event transport | accepted | 1 |
| [005](ADR-005-logical-agent-worker-pool.md) | Logical agent pool with a fixed worker fleet | accepted | 1 |
| [006](ADR-006-openai-compatible-llm-abstraction.md) | OpenAI-compatible LLM abstraction | accepted | 1 |
| [007](ADR-007-postgres-reasoning-graph.md) | Postgres property graph for the reasoning graph | accepted | 3 |
| [008](ADR-008-minio-object-storage.md) | MinIO for object storage | accepted | 1 |
| [009](ADR-009-redis-ephemeral-only.md) | Redis is ephemeral state only | accepted | 1 |
| [010](ADR-010-react-vite-frontend.md) | React + Vite single-page frontend | accepted | 14 |
| [011](ADR-011-docker-swarm-deployment.md) | Docker Swarm deployment | accepted | 1 |
| [012](ADR-012-clean-architecture-ports-adapters.md) | Clean architecture, ports and adapters | accepted | 1 |
| [013](ADR-013-coordinator-vs-orchestrator-authority.md) | Coordinator holds authority; orchestrator proposes | accepted | 4 |
| [014](ADR-014-pluggable-consensus-feasibility-gate.md) | Pluggable consensus behind a feasibility gate | accepted | 9 |
| [015](ADR-015-z3-symbolic-reasoner.md) | Z3 as the symbolic reasoner | accepted | 11 |
| [016](ADR-016-realtime-gateway-sse-first.md) | SSE-first realtime gateway | accepted | 4 |
| [017](ADR-017-secret-provider-docker-secrets.md) | Docker/Swarm secrets as the secret provider | accepted | 1 |
| [018](ADR-018-sandbox-execution-boundary.md) | Sandbox execution boundary | accepted | 8 |
| [019](ADR-019-append-only-event-ledger.md) | Append-only hash-chained event ledger | accepted | 3 |
| [020](ADR-020-stateful-ha-boundary.md) | Manual HA boundary for stateful services | accepted | 1 |

## Decision dependencies

```text
001 postgres system of record
 ├── 002 pgvector          (same consistency domain as chunks)
 ├── 007 graph in postgres (edges commit with nodes)
 └── 019 append-only ledger (transactions assign ledger_seq)
003 temporal ── 013 coordinator authority ── 014 consensus gate ── 015 z3
011 swarm ── 017 secrets ── 018 sandbox ── 020 manual HA
012 ports/adapters ── 005 logical agents ── 006 llm abstraction
010 react/vite ── 016 sse-first
```

If 001, 012, 013 or 019 is revisited, every dependent must be re-read: they are load-bearing.
