# Decisions (memory bank)

**Last updated:** 2026-09-06
Condensed decision register. Full text with options and rejected alternatives lives in
[../docs/adr/](../docs/adr/). New decisions get the next free number; superseded
decisions are marked, never deleted.

---

## Accepted architectural decisions

| # | Decision | Status | ADR |
| --- | --- | --- | --- |
| A-001 | PostgreSQL is the single system-of-record for structured state | Accepted | [ADR-001](../docs/adr/ADR-001-postgres-source-of-truth.md) |
| A-002 | pgvector is the initial `VectorStore` adapter | Accepted | [ADR-002](../docs/adr/ADR-002-pgvector-vector-store.md) |
| A-003 | Temporal provides durable workflow execution behind `WorkflowEngine`; `inmemory` adapter exists for Phase 1 | Accepted | [ADR-003](../docs/adr/ADR-003-temporal-durable-workflow.md) |
| A-004 | NATS JetStream is the production `EventBus`; it is transport, never state | Accepted | [ADR-004](../docs/adr/ADR-004-nats-event-transport.md) |
| A-005 | Logical agents execute in replicated stateless worker pools; no container per agent | Accepted | [ADR-005](../docs/adr/ADR-005-logical-agent-worker-pool.md) |
| A-006 | OpenAI-compatible HTTP API behind `LLMProvider`; `MockLLMProvider` for tests | Accepted | [ADR-006](../docs/adr/ADR-006-openai-compatible-llm-abstraction.md) |
| A-007 | Reasoning graph stored in PostgreSQL behind `ReasoningGraphStore`; no graph DB in MVP | Accepted | [ADR-007](../docs/adr/ADR-007-postgres-reasoning-graph.md) |
| A-008 | MinIO/S3-compatible storage behind `ObjectStore` for blobs | Accepted | [ADR-008](../docs/adr/ADR-008-minio-object-storage.md) |
| A-009 | Redis restricted to cache/rate-limit/ephemeral coordination | Accepted | [ADR-009](../docs/adr/ADR-009-redis-ephemeral-only.md) |
| A-010 | React + TypeScript + Vite (no SSR) with TanStack Query and React Flow | Accepted | [ADR-010](../docs/adr/ADR-010-react-vite-frontend.md) |
| A-011 | Docker Swarm is the deployment target; Compose for local dev | Accepted | [ADR-011](../docs/adr/ADR-011-docker-swarm-deployment.md) |
| A-012 | Clean architecture with ports/adapters; domain imports no infrastructure | Accepted | [ADR-012](../docs/adr/ADR-012-clean-architecture-ports-adapters.md) |
| A-013 | Deterministic Workflow Coordinator holds authority; Orchestrator LLM only proposes | Accepted | [ADR-013](../docs/adr/ADR-013-coordinator-vs-orchestrator-authority.md) |
| A-014 | Consensus is a pluggable deterministic subsystem; hard-constraint feasibility precedes ranking | Accepted | [ADR-014](../docs/adr/ADR-014-pluggable-consensus-feasibility-gate.md) |
| A-015 | Z3 is the initial `SymbolicReasoner`; natural-language rules require validated formalization | Accepted | [ADR-015](../docs/adr/ADR-015-z3-symbolic-reasoner.md) |
| A-016 | SSE-first realtime behind `RealtimeGateway`; WebSocket where bidirectional needed | Accepted | [ADR-016](../docs/adr/ADR-016-realtime-gateway-sse-first.md) |
| A-017 | `SecretProvider` abstraction; Docker Secrets in Swarm; envelope encryption for per-agent keys | Accepted | [ADR-017](../docs/adr/ADR-017-secret-provider-docker-secrets.md) |
| A-018 | `SandboxExecutionProvider` for isolated execution; raw Docker socket never exposed | Accepted | [ADR-018](../docs/adr/ADR-018-sandbox-execution-boundary.md) |
| A-019 | Append-only event ledger with sequence numbers; optional hash chaining, claims limited to what is implemented | Accepted | [ADR-019](../docs/adr/ADR-019-append-only-event-ledger.md) |
| A-020 | Local single-instance stateful services are explicitly **not** HA; production HA documented separately | Accepted | [ADR-020](../docs/adr/ADR-020-stateful-ha-boundary.md) |

## Accepted design decisions (below ADR threshold)

| # | Decision | Rationale |
| --- | --- | --- |
| D-021 | UUIDv7 for entity and event IDs | time-ordered, index-friendly, no coordination |
| D-022 | UTC `timestamptz` everywhere; ISO-8601 on the wire | unambiguous ordering for replay |
| D-023 | `schema_version` on every persisted external contract | forward migration of ledger and artifacts |
| D-024 | Artifact `version` (int) is separate from `schema_version` | revision ≠ contract migration |
| D-025 | Agents never communicate directly; all routing via coordinator | auditability, access control, reproducibility |
| D-026 | Revisions create new rows; `superseded_by` links them | non-destructive history |
| D-027 | Qualitative confidence levels are presentation-layer only | science requires distributions/intervals |
| D-028 | Every metric carries `metric_id`, `version`, `formula`, `inputs`, range, interpretation, limitations; unvalidated ones labelled `EXPERIMENTAL` | prevents invented scientific validity |
| D-029 | Four distinct replay modes named explicitly | avoids false determinism claims |
| D-030 | Chain-of-thought never stored or displayed; only structured artifacts + concise explicit rationale | policy + safety |
| D-031 | `InMemoryEventBus` + `MockLLMProvider` make the suite runnable offline | testability without paid APIs |
| D-032 | Ports are `typing.Protocol`; a registry maps config names → adapters; no bespoke plugin framework until ≥2 implementations exist | avoids premature framework |
| D-033 | Temporal activities use bounded declared policies and stable `{session_id}:{activity_type}:{caller_id}` operation IDs; exhausted bootstrap/control work becomes a durable redacted `ACTIVITY_DEAD_LETTERED` transition; PostgreSQL projection plus ledger remains checkpoint authority | at-least-once execution must not duplicate effects or turn Temporal visibility into domain state; see [ORCHESTRATION_POLICY.md](../docs/ORCHESTRATION_POLICY.md) |
| D-034 | Phase 5 baseline uses a versioned domain-neutral synthetic corpus; it measures retrieval mechanics without selecting experimental domains | Q-1 remains open for real experiments; synthetic labels cannot support scientific domain claims |
| D-035 | Structure-aware chunks target 800 tokens with 150 overlap under a pinned deterministic chunker version | matches normative RAG contract; changing policy requires re-indexing and a new baseline |
| D-036 | Namespace access is explicit typed grants checked before lexical/vector scoring; even `GLOBAL` access is granted within tenant context | prevents ranking and existence leakage; preserves forced-RLS invariant |
| D-037 | PostgreSQL source/document/chunk rows are provenance authority; `vector_items` is a replaceable derived index with UUID-backed references | retrieval indexes may be rebuilt and must never become citation authority |
| D-038 | Source-ingestion Temporal payloads carry content-addressed object references, never raw bytes; PostgreSQL operation rows own acquire/parse/embed/index checkpoints while object storage owns bytes only | keeps Temporal history bounded and non-authoritative; exact retries bind immutable request identity without duplicating provenance |
| D-039 | Phase 7 uses exact FR-501 names; resolution appends Critique versions; responses are author-bound; revisions compose existing artifact/graph/ledger paths; simulation requests remain unresolved until Phase 8; Phase 7 emits an internal complete handoff rather than a premature consensus explanation | preserves frozen Phase 3 immutability and Phase 6 authority while satisfying FR-205/501…504 without duplicate stores or future-phase fabrication |
| D-040 | Q2/Q3/Q5 are answered from durable facts already written (Q2: revision writes with `actor`/`supersedes_id`/`warrant_artifact_ids`; Q3: lifecycle projection + bound agent definitions + round-filtered `AGENT_TURN_COMPLETED`; Q5: terminal `session_lifecycles` + last ledger event) — no synthetic `STATUS_CHANGED`/`CONTEXT_ASSEMBLED`/`ROUND_TERMINATED`/`CONSENSUS_REACHED`/`HUMAN_TERMINATED` events are emitted; AUDITABILITY.md §5 paths name those sources | avoids inventing audit state that never exists; every Q is derivable from Phase 3–4 facts |
| D-041 | Q7 ("accessed before it was accepted") is defined as rows whose `recorded_at` is strictly before `recommendations.created_at`, and access evidence is anchored by the ledger through cursor pagination over `access_log` | makes the acceptance boundary deterministic and testable |

## Superseded / rejected

| # | Item | Outcome |
| --- | --- | --- |
| R-001 | One Docker service per logical agent | **Rejected** — does not scale (ADR-005) |
| R-002 | Kubernetes as orchestration platform | **Out of scope** — Swarm is the fixed target (ADR-011) |
| R-003 | Neo4j as the initial graph store | **Deferred** — Postgres first (ADR-007) |
| R-004 | LangChain-style orchestration dependency in the domain layer | **Rejected** — violates ADR-012 |
| R-005 | LLM-judged "explainability score" as a metric | **Rejected** — no formal definition (D-028) |
| R-006 | Autonomous fine-tuning in MVP | **Deferred** — controlled relearning only |
| R-007 | Next.js frontend | **Rejected for now** — no SSR requirement (ADR-010) |

## Open decisions (none block Phase 3)

| # | Question | Affects | Current leaning |
| --- | --- | --- | --- |
| O-2 | API concurrency: single-process asyncio vs replicas behind Swarm routing mesh | Phase 1/17 | replicas behind routing mesh |
| O-3 | Event ledger partitioning: per-session stream vs per-workspace | Phase 4 | per-session stream, workspace subject prefix |
| O-4 | Embedding provider default: OpenAI-compatible vs local model | Phase 5 | configurable; local default for offline tests |
| O-5 | Chunking defaults and per-namespace overrides | Phase 5 | **Resolved D-035:** 800-token target, 150 overlap; overrides deferred until measured need |
| O-6 | Does `CONDITIONAL_CONSENSUS` require explicit human acceptance to complete? | Phase 9 | yes; acceptance recorded as a first-class event |
| O-7 | Trust/reliability inputs at MVP time (history may be empty) | Phase 13 | neutral prior + documented cold-start behaviour |

## How to record a new decision

1. Add `docs/adr/ADR-0XX-slug.md` using the ADR template (Context, Options, Decision,
   Rationale, Consequences, Alternatives rejected).
2. Add a row to the table above and to [../project/DECISIONS.md](../project/DECISIONS.md).
3. If it changes a contract, update [api-contracts.md](api-contracts.md) and
   `docs/API_CONTRACTS.md` in the same commit.
4. Never delete a superseded decision — mark it `Superseded by ADR-0YY`.
