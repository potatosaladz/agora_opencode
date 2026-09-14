# Plan

**Horizon:** Phase 0 → Phase 17 · **Last updated:** 2026-09-05
**Normative inputs:** [../docs/REQUIREMENTS.md](../docs/REQUIREMENTS.md) (what),
[../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) (where),
[../docs/MVP_BOUNDARY.md](../docs/MVP_BOUNDARY.md) (in what order),
[../docs/adr/](../docs/adr/README.md) (with what choices).

This file is the phase contract. [../memory-bank/tasks.md](../memory-bank/tasks.md) is the live
register; [TASKS.md](TASKS.md) holds the same phases with acceptance criteria and estimates. When this
file and `docs/` disagree, `docs/` wins and this file is corrected.

## Rules that govern every phase

| # | Rule | Source |
| --- | --- | --- |
| R-1 | A phase ends only when its exit gate is green. "Mostly done" is not a state. | [DEPLOYMENT.md §5](../docs/DEPLOYMENT.md) |
| R-2 | No phase introduces a stateful service without an ADR. | [adr/README.md](../docs/adr/README.md) |
| R-3 | Every requirement claimed done must be `implemented` in the traceability matrix, not merely ticked. | [TRACEABILITY.md §4](../docs/TRACEABILITY.md) TR-1 |
| R-4 | Research-track work never enters the MVP dependency graph. | [MVP_BOUNDARY.md §6](../docs/MVP_BOUNDARY.md) |
| R-5 | The anti-pattern checklist is run at every phase exit; a hit blocks the gate. | [ANTI_PATTERNS.md](../docs/ANTI_PATTERNS.md) |
| R-6 | Docs are updated in the same commit as the behaviour they describe. | [README.md §Maintenance](../docs/README.md) |
| R-7 | A small correct increment beats a large speculative one. | [../README.md](../README.md) |

## Phase 0 — Requirements & architecture · **complete and approved**

**Deliverables:** 34 documents in `docs/`, 20 ADRs, 6 consensus formalisms + template, memory bank,
project state files, this plan.
**Exit gate:** link check clean; every `FR-`/`NFR-` has ≥ 1 design ref; contradiction checklist run;
architecture approval recorded in [DECISIONS.md](DECISIONS.md).
**Approval:** granted by the project owner on 2026-09-04 and recorded as [D-13](DECISIONS.md#accepted); T0-12 is complete.

## Phase 1 — Foundation · *the stack must be boring and real*

**Goal:** a running, observable, testable skeleton with every stateful service reachable.

| Task | Deliverable |
| --- | --- |
| T1-00 | toolchain verification (Docker, Python 3.12+, Node 20+, git identity) |
| T1-01…03 | backend package layout `domain/application/ports/adapters`, import-lint enforcing direction ([ADR-012](../docs/adr/ADR-012-clean-architecture-ports-adapters.md)) |
| T1-02 | FastAPI app factory, settings, `/health` `/ready`, error envelope ([API_CONTRACTS.md §3](../docs/API_CONTRACTS.md)) |
| T1-04…05 | Postgres + SQLAlchemy 2 async + Alembic baseline; RLS enabled on day one ([SECURITY.md §6](../docs/SECURITY.md)) |
| T1-06…08 | Redis, MinIO, NATS adapters behind their ports; `InMemoryEventBus` for tests |
| T1-09 | `docker-compose.yml` with healthchecks on every service |
| T1-10 | auth skeleton: users, workspaces, RBAC ADMIN/RESEARCHER/OPERATOR/VIEWER, deny-by-default |
| T1-11 | `SecretProvider` with `env_file` (dev) and `swarm_secret` (prod) adapters ([ADR-017](../docs/adr/ADR-017-secret-provider-docker-secrets.md)) |
| T1-12 | OTel traces, Prometheus `/metrics`, structured logs with redaction filter |
| T1-13 | Vite + React + TS skeleton, generated API client, router |
| T1-14 | CI: lint, typecheck, unit, contract, integration, docs link check, `trace-check` |

**Exit gate:** `docker compose up` yields a healthy stack; `/ready` green; CI green including a replay of
the empty-session golden fixture; a request traced end to end in Jaeger.
**Deliberately excluded:** Temporal, LLM calls, any reasoning logic.

## Phase 2 — LLM abstraction & agent registry

**Goal:** call a model through a port, and describe an agent without writing code.

T2-01 `LLMProvider` port + capability models · T2-02 `OpenAICompatibleProvider`
([ADR-006](../docs/adr/ADR-006-openai-compatible-llm-abstraction.md)) · T2-03 `MockLLMProvider` with
fixture scenarios (the test suite depends on this existing before any reasoning code) · T2-04
structured-output validation + bounded repair retry · T2-05/06 agent definitions, registry CRUD,
versioning with `superseded_by` · T2-07/08 LLM configuration entities, envelope encryption, master key
from a Swarm secret · T2-09 token and cost accounting on every call.

**Exit gate:** the same agent definition runs against two providers and against the mock, producing
three traceable records; cost is visible per call; no provider SDK import outside `adapters/`
(import-lint enforces it).

## Phase 3 — Structured reasoning model · *contract reconciliation in progress*

**Goal:** the Phase 3 artifact taxonomy exists in PostgreSQL before any agent generates artifacts, and
every accepted mutation is attributable, versioned and committed with its ledger record.

The former "20 first-class entities" task mixed Phase 3 artifacts with entities owned by later phases.
This phase is split into four independently green increments. T3-00 freezes the exact boundary before
runtime work starts; it must reconcile `REQUIREMENTS.md`, `DATA_MODEL.md`, `STRUCTURED_REASONING.md`, the
API contracts and ADR-019 rather than choosing one silently.

| Increment | Task | Deliverable |
| --- | --- | --- |
| 3A — contract | T3-00 | reconcile the Phase 3 entity list, `Fact`/opinion/hypothesis representation, common envelope/status vocabulary, forward references to Phase 5 tables, FR-101…103 API/UI ownership and verification, and exact ledger hash/sequence/actor semantics; update normative docs first |
| 3A — contract | T3-01 | immutable domain value objects and enums for the common envelope and the 14 FR-301 artifact kinds, with strict validation and deterministic canonical JSON/content hashes |
| 3A — contract | T3-02 | session/problem binding and versioned proposition normalization, preserving original text and canonicalizer version; no orchestration state machine from Phase 4 |
| 3B — storage | T3-03 | linear Alembic revisions and SQLAlchemy rows for only the frozen Phase 3 session/artifact schema, with composite tenant foreign keys, forced RLS, checks and indexes |
| 3B — storage | T3-04 | `ReasoningGraphStore` contract plus PostgreSQL node/edge write path; endpoint resolution, same-workspace edges, no self-loop and uniqueness enforced in the database; traversal APIs remain Phase 10 |
| 3C — ledger | T3-05 | append/read/verify ledger boundary with idempotent event ids, gapless per-session `ledger_seq`, causation/correlation ids, canonical payload hash, `prev_hash` and `event_hash` |
| 3C — ledger | T3-06 | one transaction-level commit service writes artifact revision, ledger event and graph projection atomically; revision creates a new row and withdrawal is additive |
| 3D — boundary | T3-07 | tenant-scoped session create/read and artifact read/write boundary required by the frozen FR-101…103 acceptance, with authored OpenAPI and generated-client drift checks |
| 3D — proof | T3-08 | unit/property/contract tests, the FR-101 user walkthrough and live PostgreSQL proofs for clean migration, RLS, tenant-safe FKs, concurrent sequence assignment, chain verification/tamper detection, non-destructive versioning and database-level mutation rejection |
| 3D — exit | T3-09 | trace rows, schema-document comparison, anti-pattern review, full Phase 1/2 regression suite, healthy Compose proof and updated state documents |

**Deliberately excluded:** Temporal and session lifecycle execution (Phase 4); source/document/chunk
ingestion (Phase 5); agent reasoning behaviour (Phase 6); graph traversal/impact APIs (Phase 10); daily
external anchors and audit-record queries (Phase 13).

**Exit gate:** `UPDATE` and `DELETE` on `reasoning_events` are revoked from the application role and
rejected by database triggers; clean and deliberately tampered chains are distinguished by the
verification query; every persisted Phase 3 artifact resolves to its typed row and graph node; revisions
and withdrawals preserve prior rows; cross-workspace references fail in PostgreSQL; and the frozen
Phase 3 schema in [DATA_MODEL.md](../docs/DATA_MODEL.md) matches the migrations under an automated
schema-drift test.

## Phase 4 — Durable orchestration

**Goal:** a session survives the death of any process, including the browser.

T4-01 `WorkflowEngine` port + Temporal adapter ([ADR-003](../docs/adr/ADR-003-temporal-durable-workflow.md)) ·
T4-02 deterministic coordinator workflow owning the state machine
([ADR-013](../docs/adr/ADR-013-coordinator-vs-orchestrator-authority.md)) · T4-03 every LLM, RAG,
simulation and symbolic call is an activity · T4-04 pause/resume/cancel and human-in-the-loop signals ·
T4-05 retry, timeout, idempotency keys, dead-letter, checkpoints · T4-06 ledger → NATS → SSE
([ADR-016](../docs/adr/ADR-016-realtime-gateway-sse-first.md)) · T4-07/T4-08 recovery tests.

**Exit gate (T4-07, non-negotiable):** close the browser mid-session, kill the worker, let the session
complete, reopen the UI and see the finished state restored from the ledger with no lost events.

## Phase 5 — RAG & memory namespaces

T5-00 freezes the conflicting retrieval, memory, namespace and schema contracts before runtime work ·
T5-01 deterministic structure-aware ingestion · T5-02 tenant-safe source/document/chunk storage ·
T5-03 durable object/ingestion lifecycle · T5-04 UUID-backed `VectorStore` integration on pgvector
([ADR-002](../docs/adr/ADR-002-pgvector-vector-store.md)) · T5-05 hybrid retrieval (lexical + vector +
rerank) · T5-06 namespace grants and pre-ranking ACL enforcement · T5-07 exact citation spans, manual
evidence and retraction · T5-08 memory tiers with validated promotion and review-trigger decay
([MEMORY_ARCHITECTURE.md](../docs/MEMORY_ARCHITECTURE.md)) · T5-09 exit evidence.

**Exit gate:** retrieval quality measured on the fixture corpus with a recorded baseline; every returned
chunk resolves to a stored artifact digest; a cross-namespace retrieval attempt fails closed and is
audited.

## Phase 6 — Domain expert reasoning

Agent roles from [AGENT_MODEL.md](../docs/AGENT_MODEL.md) produce artifacts, not prose: positions with
cited propositions, explicit assumptions, declared uncertainty. **Exit gate:** every position a role
emits validates against its schema and links ≥ 1 evidence or an explicit `NO_EVIDENCE` marker; a
position with a fabricated citation fails the test suite.

T6-00 freezes the authority, runtime, evidence-disposition, attribution and budget contracts before
runtime work · T6-01 strict `AgentRuntime` / `ReasoningStrategy` ports · T6-02 automatic structured
decomposition · T6-03 authorized reasoning-context assembly · T6-04 deterministic proposal validation
and atomic commit · T6-05 five policy-analysis experts and pinned prompts · T6-06 sealed shared-pool
multi-agent dispatch · T6-07 orchestrator proposal policy · T6-08 agent injection, budget enforcement,
attribution and 20-agent proof · T6-09 exit evidence. Normative detail:
[PHASE6_ACCEPTANCE.md](../docs/PHASE6_ACCEPTANCE.md).

## Phase 7 — Critic & revision loop

T7-00 freezes Critic authority, exact FR-501 taxonomy, target eligibility, immutable resolution,
response mapping, revision sealing and explanation handoff · T7-01 strict Critic/response contracts ·
T7-02 shipped Critic definition and prompt · T7-03 authorized Critic context, dispatch and inactivity ·
T7-04 atomic Critique/`ATTACKS` commit · T7-05 response policy and additive resolution · T7-06 targeted
revision with `SUPERSEDES`/`RESPONDS_TO` · T7-07 phase ordering and explanation handoff fixture · T7-08
exit evidence. Normative detail: [PHASE7_ACCEPTANCE.md](../docs/PHASE7_ACCEPTANCE.md).

**Exit gate:** a fixture session with a planted unsupported claim produces an `EVIDENCE_GAP` Critique;
the latest unresolved head is present in the deterministic explanation handoff; valid revision preserves
both target and Critique history; inherited local, live and exact-SHA CI gates pass.

## Phase 8 — Simulation

T8-01 `SimulationEngine` port + `system_dynamics` and `monte_carlo` adapters · T8-02 model specs stored
as artifacts with source digest pinning · T8-03 sandbox execution
([ADR-018](../docs/adr/ADR-018-sandbox-execution-boundary.md)) · T8-04 results as artifacts with
sensitivity analysis · T8-05 validation against analytic cases.
**Exit gate:** the same spec plus seed replays byte-identically in `REPLAY_STRICT`; a sandboxed run
cannot reach the network or the `data` overlay (proven by a test, not by configuration review).

## Phase 9 — Consensus engine

T9-01 `ConsensusContext` assembly · T9-02 the shared feasibility gate, implemented once in the
coordinator · T9-03 `weighted`, `evidence_weighted`, `constraint_aware` per
[consensus-formalism/](../docs/consensus-formalism/README.md) · T9-04 outcome classification including
`INFEASIBLE`, `INSUFFICIENT_EVIDENCE`, `PARETO_SET`, `CONDITIONAL_CONSENSUS` · T9-05 explanation object
emitted with every outcome · T9-06 strategy registry refusing an unregistered or undocumented strategy.
**Exit gate:** the three formalisms pass their worked examples as unit tests; a session with no verified
evidence returns `INSUFFICIENT_EVIDENCE` rather than a ranking; minority positions appear in the output.

## Phase 10 — Reasoning graph & traceability · **complete**

T10-01 graph read APIs and traversals ([REASONING_GRAPH.md](../docs/REASONING_GRAPH.md)) · T10-02
recommendation-to-source path query · T10-03 `TRACEABILITY.csv` generated from `# trace:` annotations ·
T10-04 impact analysis (which recommendations depend on this evidence).
**Exit gate satisfied:** from any recommendation, one API call returns the chain to primary sources with
verification states; deterministic `trace-check` covers all 104 requirements and fails on an orphan.

## Phase 11 — Neuro-symbolic (Z3)

T11-01 formalisation pipeline with `validation_status` · T11-02 Z3 adapter behind `SymbolicReasoner`
([ADR-015](../docs/adr/ADR-015-z3-symbolic-reasoner.md)) · T11-03 unsat cores and witness models
surfaced into the graph · T11-04 `UNKNOWN` handling policy.
**Exit gate:** an alternative that violates a hard constraint is removed by the gate with its unsat core
quoted; an unvalidated formalisation cannot produce an enforceable verdict (NS-invariant, tested).

T11-01 is limited to the closed typed AST, deterministic structural/type/unit validation, immutable
revisions, explicit human decisions, and authoritative `CANDIDATE | VALIDATED | REJECTED` derivation
(FR-707). Z3 execution, SAT/UNSAT/UNKNOWN, witnesses, unsat cores, and persisted symbolic evaluations
remain T11-02 through T11-04.

## Phase 12 — MARL environment *(research track)*

T12-01 exact domain/canonical identities and five-component reward vector · T12-02 lifecycle and in-memory
store · T12-03 canonical two-file export and hermetic verifier · T12-04 append-only PostgreSQL persistence
and migration · T12-05 golden/mutation/contract/live acceptance and traceability — **no training**
([MARL_MODEL.md](../docs/MARL_MODEL.md)). **Exit gate:** trajectories replay deterministically and each
reward component is traceable to a metric id. This is not Phase 13 full-session `REPLAY_STRICT`.

## Phase 13 — Trustworthiness

T13-01 metric catalogue implemented ([METRICS.md](../docs/METRICS.md)) · T13-02 audit record generation
and the eight audit queries ([AUDITABILITY.md](../docs/AUDITABILITY.md)) · T13-03 replay modes
`STRICT` / `TOLERANT` / `LIVE` · T13-04 run manifests with pinning.
**Exit gate:** a past session answers "why did it say that" with evidence, dissent and assumptions all
rendered; the manifest of a completed run reproduces it in `TOLERANT` mode.

## Phase 14 — Full UI

T14-01 Graph View · T14-02 Dissent View · T14-03 Assumption Register · T14-04 Explanation Panel ·
T14-05 Replay Controls · T14-06 Audit Search. The tasks expose and render existing graph, consensus,
provenance, symbolic, replay, manifest and audit authority; they do not rebuild those capabilities.
Normative scope, acceptance, requirement-reference boundaries and the scripted usability fixture are frozen
in [PHASE14_ACCEPTANCE.md](../docs/PHASE14_ACCEPTANCE.md).
**Exit gate:** a reviewer with no knowledge of the internals can identify the minority position and the
weakest evidence in a session from the UI alone (a scripted usability test, not an opinion).

## Phase 15 — MCP gateway

T15-01 gateway as the sole tool egress · T15-02 server registry with allowlist and a recorded decision
per server · T15-03 tool-level authz, approval gates, rate limits · T15-04 injection containment for tool
output ([MCP_SECURITY.md](../docs/MCP_SECURITY.md)).
**Exit gate:** a worker container has no route to the internet; a tool result cannot write artifacts
directly; a hostile tool-output fixture does not change agent behaviour outside its declared scope.

## Phase 16 — Research extensions

`deliberative`, `bayesian`, `prediction_market` strategies; experiment harness; ablations
([EXPERIMENTATION.md](../docs/EXPERIMENTATION.md)). **Exit gate:** each strategy has a formalism
document, a passing worked example, and a comparison run against `constraint_aware` on identical inputs.

## Phase 17 — Swarm & hardening

T17-01 stack files per environment · T17-02 secrets out of the environment entirely · T17-03 streaming
replica, WAL archiving, restore drill
([ADR-020](../docs/adr/ADR-020-stateful-ha-boundary.md)) · T17-04 chaos pass · T17-05 threat-model
re-run with every mitigation verified by a test.
**Exit gate:** a restore drill succeeds from a production-shaped backup; ledger chain verification is
clean after a node loss; every `T-n` threat in [THREAT_MODEL.md](../docs/THREAT_MODEL.md) has a control
with a test id.

## MVP demo

Ends at the Phase 14 core, with Phases 15–17 required before any external deployment. The 18 success
criteria live in [../docs/MVP_BOUNDARY.md](../docs/MVP_BOUNDARY.md) and are checked, not asserted.

## Sequencing constraints

```text
1 → 2 → 3 → 4 → {5, 6} → 7 → {8, 9} → 10 → 11 → 13 → 14 → 15 → 17
                                     12, 16 run in parallel (research track)
```

Phase 9 cannot precede Phases 8 and 11 without becoming a popularity contest: the feasibility gate needs
constraints to gate on. Phase 13 cannot precede Phase 10: there is nothing to audit without provenance.

## Re-planning triggers

| Trigger | Action |
| --- | --- |
| A phase exit gate fails twice | stop, write the root cause in [ERRORS.md](ERRORS.md), re-plan the phase |
| A requirement proves unimplementable as specified | amend `REQUIREMENTS.md` first, code second |
| Scope pressure from a demo | route through [../docs/MVP_BOUNDARY.md](../docs/MVP_BOUNDARY.md) scope-change protocol |
| A new stateful service appears desirable | new ADR, or the service does not appear |
| A phase takes 2× its estimate | split it; do not extend it |

