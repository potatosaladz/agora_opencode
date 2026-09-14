# Architecture (memory bank digest)

**Version:** 1.0 · **Last reviewed:** 2026-09-04
**Normative source:** [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md). This file is a
recovery-oriented digest; where the two disagree, `docs/ARCHITECTURE.md` wins and this
file must be corrected.

---

## 1. One-paragraph summary

A React UI talks to a FastAPI API layer, which starts and observes **durable Temporal
workflows**. A deterministic **Workflow Coordinator** (Temporal workflow code) owns all
session state transitions and invokes **activities**; every nondeterministic operation —
LLM calls, retrieval, simulation, symbolic solving, MCP tool calls — is an activity,
never inline workflow logic. Logical domain agents execute inside replicated stateless
**reasoning-worker** pools, not one container per agent. All structured reasoning
artifacts are the authoritative state in **PostgreSQL**; **NATS JetStream** is transport
only; **pgvector** is retrieval only; **Redis** is ephemeral only; **MinIO** holds blobs.
A pluggable **ConsensusStrategy** evaluates normalized propositions and alternatives
after **hard-constraint feasibility** filtering by a symbolic reasoner. Everything is
recorded in an append-only **reasoning event ledger** enabling audit, replay and
reproducibility manifests.

## 2. Layers (clean architecture)

```text
Domain        ← entities, value objects, invariants. Imports NOTHING from infra.
Application   ← use cases, orchestration, workflows, RAG, simulation, MARL, symbolic.
Ports         ← Protocols/ABCs: LLMProvider, EventBus, VectorStore, ConsensusStrategy…
Adapters      ← postgres, pgvector, minio, redis, nats, temporal, mcp, llm, symbolic.
```

Rule: domain logic must not import FastAPI, SQLAlchemy, Temporal, Redis, NATS, MinIO or
the OpenAI SDK. Dependency direction is inward only. See ADR-012.

## 3. Deployed services (functional workloads, not per-agent)

`frontend` · `api` · `workflow-worker` · `reasoning-worker` · `rag-worker` ·
`simulation-worker` · `mcp-gateway` · `temporal` (+ its own DB) · `nats` · `postgres` ·
`redis` · `minio` · `observability` (OTel Collector, Prometheus, Grafana, optional Loki).

## 4. Agent runtime model (ADR-005)

```text
Agent Definition (registry row, versioned)
        ↓ instantiated into
Logical Agent Runtime (in-memory state: identity, objectives, constraints, memory refs)
        ↓ executed by
Reasoning Worker Pool (replicated stateless containers)
```

Fiscal, Macroeconomic, Social Policy, Infrastructure and Risk agents normally share the
same `reasoning-worker` service. Separate containers exist only for
`SandboxExecutionProvider` needs: untrusted code, special engines, resource-heavy or
security-sensitive workloads.

## 5. Authority split (the most important invariant)

| Workflow Coordinator (deterministic) | Orchestrator LLM Agent (semantic) |
| --- | --- |
| owns workflow state, retries, ordering, timeouts, transitions, persistence, permissions, convergence checks, consensus invocation | interprets problems, identifies domains and missing evidence, proposes next actions, summarizes disagreements, proposes questions and simulations, interprets results |

The Orchestrator LLM has **no** authority to mutate platform state directly. Every LLM
recommendation passes through deterministic application policy. See ADR-013.

T6-08 preserves that split for membership and budgets. Initial agent pins plus append-only effective-round
deltas define membership in ledger order; lifecycle-row locking serializes changes with round start.
Context/retrieval use only effective definitions. Durable session/definition usage is checked around
bounded dispatch, and a reached ceiling atomically terminates with `BUDGET_EXHAUSTED`.

## 6. Storage responsibilities

| Store | Authoritative for | Explicitly NOT |
| --- | --- | --- |
| PostgreSQL | users, workspaces, agents+versions, LLM configs, sessions, propositions, claims, evidence metadata, assumptions, risks, uncertainty, objectives, constraints, alternatives, positions, critiques, simulation metadata, recommendations, reasoning events, graph nodes/edges, metrics, experiments, plugin metadata | blobs, embeddings-as-primary, workflow execution state |
| pgvector | embeddings + ANN indexes | system-of-record |
| MinIO/S3 | documents, datasets, raw uploads, exports, simulation artifacts, large experiment artifacts | structured reasoning state |
| Redis | cache, rate limiting, ephemeral locks, temporary coordination | **any** durable truth |
| NATS JetStream | event distribution, decoupled subscribers, realtime propagation | workflow or reasoning state |
| Temporal | workflow execution state, retries, timers, durable history | domain reasoning artifacts |

## 7. Reasoning artifact model

Phase 3 first-class artifacts: `Claim`, `Fact`, `Assumption`, `Inference`, `Proposition`,
`Evidence`, `Uncertainty`, `Risk`, `Impact`, `Objective`, `Constraint`, `Alternative`,
`Position`, `Critique`. Opinion is `Position`; hypothesis is a typed `Claim`. Simulation,
recommendation, decision and assessment contracts belong to later phases.

Common envelope: `id`, `session_id`, `workspace_id`, `owner_agent_id`, `created_at`,
`updated_at`, `version`, lifecycle `status`, `provenance`, `source_references`, `confidence`,
`parent_relationships`, `supersedes_id`, `metadata`, `schema_version`, `content_hash`.

Epistemic ladder (never conflated): `FACT` · `EVIDENCE` · `ASSUMPTION` · `CLAIM` ·
`INFERENCE` · `OPINION` · `SIMULATION_RESULT` · `RECOMMENDATION`. LLM text never
auto-becomes `FACT` or `EVIDENCE`; evidence requires provenance.

## 8. Graph model (ADR-007)

Nodes: evidence, assumption, claim, objective, constraint, risk, critique, simulation
result, alternative, recommendation, proposition, position. Edges (versioned,
provenance-aware): `SUPPORTS`, `ATTACKS`, `CONTRADICTS`, `DEPENDS_ON`, `DERIVED_FROM`,
`SATISFIES`, `VIOLATES`, `MITIGATES`, `REQUIRES`, `ASSUMES`, `CAUSES`, `INCREASES`,
`DECREASES`, `REFINES`, `SUPERSEDES`, `TRIGGERED_BY`, `RESPONDS_TO`. Stored in
PostgreSQL behind `ReasoningGraphStore`; Neo4j/Memgraph/RDF are later adapters. Semantic
export (JSON-LD/RDF) is an adapter, not a schema constraint.

## 9. Consensus (ADR-014)

`ConsensusStrategy.evaluate(ConsensusContext) -> ConsensusResult`. Deterministic,
pluggable, versioned, documented. The baseline weighted-sum support function is **one
plugin**, not platform semantics. Feasibility precedes ranking:
`F = { a ∈ A | all mandatory hard constraints satisfied }`; nothing outside `F` is
selectable for having a high score. Outcomes: `FULL_CONSENSUS`, `PARTIAL_CONSENSUS`,
`CONDITIONAL_CONSENSUS`, `PARETO_SET`, `DEADLOCK`, `NO_CONSENSUS`,
`INSUFFICIENT_EVIDENCE`, `INFEASIBLE`. Consensus is reported as a **metric profile**,
never a single "AI quality score".

## 10. Session state machine

`CREATED → INITIALIZING → RUNNING → {WAITING_FOR_AGENT, WAITING_FOR_CRITIQUE,
WAITING_FOR_EVIDENCE, WAITING_FOR_SIMULATION, WAITING_FOR_HUMAN} → EVALUATING_CONSENSUS
→ {RUNNING (next round), COMPLETED, NO_CONSENSUS, DEADLOCK}`; plus `PAUSED`,
`FAILED_RETRYABLE`, `FAILED`, `CANCELLED`. UI connection has **no** authority over
workflow lifetime.

## 11. Durability & failure policy

Retry with exponential backoff, timeouts, idempotency keys, circuit breakers where
appropriate, dead-letter handling, checkpointing, structured failure events. Failed
reasoning operations are never silently discarded.

## 12. Realtime

`RealtimeGateway` abstraction; SSE preferred for one-directional server→client event
streaming, WebSocket where bidirectional interaction is required. Domain logic is not
coupled to either protocol (ADR-016).

## 13. Deployment

Docker Compose for local development; Docker Swarm stack for production-like deployment
(overlay networks, Docker Secrets, replicas, restart policies, health checks, rolling
updates, resource limits, placement constraints, graceful shutdown). `replicas: 3` on a
stateful service is **not** HA — production stateful HA is a separately documented
architecture (ADR-020).

## 14. Known architectural contradictions — resolved

| Tension | Resolution |
| --- | --- |
| Logical agent vs Docker service | Logical agents live in the registry and execute in shared worker pools (ADR-005). |
| Workflow responsibility vs event bus | Temporal + PostgreSQL own state; NATS is transport only (§6). |
| Source of truth | PostgreSQL only; Redis/NATS/pgvector are derived or ephemeral (ADR-001). |
| Agent vs orchestrator authority | Deterministic coordinator decides; orchestrator LLM proposes (ADR-013). |
| LLM vs symbolic authority | LLM interprets and proposes; symbolic reasoner decides constraint satisfaction (ADR-015). |
| RAG knowledge vs factual evidence | Retrieved content is a candidate with provenance; verification status gates `EVIDENCE`. |
| Consensus score vs metric profile | A score is one strategy's output; the session reports a multi-dimensional metric profile (docs/METRICS.md). |
| MVP vs research extensions | Hard boundary table in docs/MVP_BOUNDARY.md; MARL training and epistemic logic excluded. |

## 15. Open architecture questions

Tracked in [../project/DECISIONS.md](../project/DECISIONS.md#3-open-decisions). None
currently blocks Phase 1; the ones that could shape Phase 4/5 are flagged there.

