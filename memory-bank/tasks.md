# Tasks (memory bank)

**Last updated:** 2026-09-14
Working task register. `project/TASKS.md` holds the same tasks with acceptance criteria
and estimates; this file is the fast "what is open right now" view.

Legend: `[ ]` open · `[~]` in progress · `[x]` done · `[!]` blocked · `[-]` dropped

---

## Phase 0 — Requirements & architecture

| ID | Task | Status |
| --- | --- | --- |
| T0-01 | Inspect repository, confirm project location, init Git | `[x]` |
| T0-02 | Root docs: README, CHANGELOG, .gitignore | `[x]` |
| T0-03 | Memory bank (9 files) | `[x]` |
| T0-04 | `docs/ARCHITECTURE.md` + 8 Mermaid diagrams | `[x]` |
| T0-05 | Domain & research specifications | `[x]` |
| T0-06 | Port/interface contracts (19 ports) | `[x]` |
| T0-07 | API + versioned contract documents | `[x]` |
| T0-08 | MVP boundary + requirement classification | `[x]` |
| T0-09 | ADR-001 … ADR-020 | `[x]` |
| T0-10 | Security / trustworthiness / operations docs | `[x]` |
| T0-11 | Consistency pass: contradiction checklist + link/fence validation | `[x]` |
| T0-12 | Present Phase 0 summary, request architecture approval | `[x]` |
| T0-13 | Reconciliation: 18 missing docs, ADR-017…020, consensus formalisms, `project/` state set, phase-number unification | `[x]` |

**Gate satisfied:** Phase 0 was approved on 2026-09-04; see project decision D-13.

---

## Phase 1 — Project foundation (complete)

| ID | Status | Task |
| --- | --- | --- |
| T1-00 | `[x]` | Verify host toolchain: Docker engine, Python 3.12+, Node 20+, git identity |
| T1-01 | `[x]` | Backend project config (`pyproject.toml`, ruff/mypy/pytest config, package skeleton) |
| T1-02 | `[x]` | FastAPI skeleton: app factory, settings, health endpoints, error envelope |
| T1-03 | `[x]` | Domain/application/ports/adapters package layout with import-lint enforcement |
| T1-04 | `[x]` | PostgreSQL + SQLAlchemy 2 async engine + Alembic baseline migration |
| T1-05 | `[x]` | pgvector extension + `VectorStore` port + Postgres adapter (thin) |
| T1-06 | `[x]` | Redis adapter (cache/rate-limit only) |
| T1-07 | `[x]` | MinIO adapter behind `ObjectStore` |
| T1-08 | `[x]` | NATS adapter behind `EventBus` + `InMemoryEventBus` for tests |
| T1-09 | `[x]` | `docker-compose.yml` (dev) with healthchecks |
| T1-10 | `[x]` | Auth skeleton: users, workspaces, RBAC roles ADMIN/RESEARCHER/OPERATOR/VIEWER |
| T1-11 | `[x]` | `SecretProvider` port: `.env` dev adapter + Docker Secrets adapter |
| T1-12 | `[x]` | Observability: live FastAPI→PostgreSQL trace, authenticated RED metrics, safe SQL spans, redacted logs |
| T1-13 | `[x]` | Frontend skeleton: Vite + React + strict TS, router, TanStack Query, generated API client |
| T1-14 | `[x]` | CI: backend/frontend quality, contract, integration, link, trace, replay, and aggregate gate |
| T1-15 | `[x]` | Local exit gates and all jobs in GitHub Actions run `33923240340` green |

## Phase 2 — LLM & agent registry (complete)

| ID | Status | Task |
| --- | --- | --- |
| T2-01 | `[x]` | `LLMProvider` port + `LLMRequest`/`LLMResponse`/capability models |
| T2-02 | `[x]` | `OpenAICompatibleProvider` (per-agent base_url/model/params, retries, timeouts) |
| T2-03 | `[x]` | `MockLLMProvider` with fixture-driven deterministic scenarios |
| T2-04 | `[x]` | Structured-output validation + repair-retry policy for malformed LLM JSON |
| T2-05 | `[x]` | Agent definition model (identity, objectives, constraints, reasoning config) |
| T2-06 | `[x]` | Agent registry CRUD + agent versioning + `superseded_by` |
| T2-07 | `[x]` | LLM configuration entities with encrypted credential references |
| T2-08 | `[x]` | Envelope encryption for per-agent secrets (master key via Docker Secret) |
| T2-09 | `[x]` | Token/cost accounting hooks on every provider call |

## Phase 3 — Structured reasoning model (complete)

| ID | Status | Task |
| --- | --- | --- |
| T3-00 | `[x]` | Reconcile and freeze the entity taxonomy, envelope, session boundary, provenance references and exact ledger semantics across the normative documents |
| T3-01 | `[x]` | Common envelope + strict domain types for the 14 FR-301 artifact kinds; deterministic canonical JSON/content hashes |
| T3-02 | `[x]` | Session/problem binding + proposition normalization preserving original text and canonicalizer version |
| T3-03 | `[x]` | Phase 3 Alembic/SQLAlchemy persistence with composite tenant FKs, forced RLS, checks and indexes |
| T3-04 | `[x]` | `ReasoningGraphStore` contract + PostgreSQL graph write path and database-enforced edge invariants |
| T3-05 | `[x]` | Append/read/verify ledger with per-session sequence, causation/correlation ids and tamper-evident hash chain |
| T3-06 | `[x]` | Atomic artifact commit/revise/withdraw: typed row + ledger event + graph projection in one transaction |
| T3-07 | `[x]` | Tenant-scoped Phase 3 API, authored OpenAPI and generated-client drift gate |
| T3-08 | `[x]` | Requirement-level unit/property/contract/live PostgreSQL acceptance for FR-101…103 and FR-301…312 |
| T3-09 | `[x]` | Phase exit: schema-doc diff, anti-pattern review, inherited gates, healthy Compose and remote CI green |

## Phase 4 — Durable orchestration

| ID | Task |
| --- | --- |
| T4-01 | `[x]` `WorkflowEngine` / `WorkflowWorker` ports + Temporal and in-memory adapters; live start, duplicate, describe, health and worker polling proof |
| T4-02 | `[x]` Session workflow, full validated state machine, PostgreSQL/ledger transitions and idempotent `202` start |
| T4-03 | `[x]` Typed agent-turn activity, sealed prompt verification, turn-scoped provider lifecycle and tenant transaction facade; future RAG/sim/symbolic ports must follow the same activity boundary |
| T4-04 | `[x]` Typed, authenticated and idempotent pause/resume/cancel/legacy-terminate and human-input signals; deterministic workflow interpretation with PostgreSQL-authoritative transitions |
| T4-05 | `[x]` Bounded retry/timeout and heartbeat policy, stable operation identity, redacted failure taxonomy, durable dead-letter transitions and PostgreSQL-authoritative checkpoints |
| T4-06 | `[x]` Event ledger → post-commit NATS publication → ledger-authoritative SSE `RealtimeGateway`; `Last-Event-ID` resumes by `ledger_seq` |
| T4-07 | `[x]` Browser-close recovery restores terminal PostgreSQL projection and ledger timeline from durable local session pointer |
| T4-08 | `[x]` Real Temporal worker replacement and post-commit activity retry preserve one committed effect per stable event identity |

## Phases 5–17

Broken out with acceptance criteria in [../project/TASKS.md](../project/TASKS.md).
Phase 12 T12-01 through T12-05 `[x]`; deterministic MARL trajectory capture/export/replay foundation
complete, with no training. Phase 13 (Trustworthiness): T13-01 metric catalogue `[x]` (43
`MetricDefinition`s, exact-lookup `MetricCatalogue`, 13 tests); T13-02 audit records + eight queries
`[x]` (migration `20260912_0025` `access_log`/`audit_anchors`, `app/domain/audit.py`,
`app/db/audit.py`, `app/application/audit.py` answering Q1–Q8, 21 unit + 7 live PostgreSQL tests,
FR-807/NFR-006 implemented); T13-03 `STRICT`/`TOLERANT`/`LIVE` replay `[x]` (typed contracts,
exact-version orchestration, ledger/MARL verification, structured tolerant diff, fresh LIVE identities,
11 focused tests); T13-04 run manifests `[x]` (canonical typed pins, content-addressed finalized bytes,
migration `20260914_0026`, forced RLS, one manifest/session, source lineage, exact T13-03 resolution).
Phase 14 contract `[x]`; implementation tasks are T14-01 Graph View `[x]`, T14-02 Dissent View `[ ]`,
T14-03 Assumption Register `[ ]`, T14-04 Explanation Panel `[ ]`, T14-05 Replay Controls `[ ]`, and
T14-06 Audit Search `[ ]`. Exact boundaries and the unpassed scripted usability fixture are frozen in
[../docs/PHASE14_ACCEPTANCE.md](../docs/PHASE14_ACCEPTANCE.md). T14-02 is next; do not start it
automatically.
Phase 5 T5-00 through T5-09 are committed locally at
`45253c8b91c103e9632554de8b31d55a5a5281c4`; its exact-SHA remote CI remains pending independently.
Phase 6 T6-00 through T6-09 are complete on `phase6-domain-reasoning`; final commit
`6d671acffe7abd3e5b587042457f300e0c442adc` passed all six jobs in GitHub Actions run `34148649503`.
Detailed T6-00…09
acceptance lives in [../project/TASKS.md](../project/TASKS.md) and
[../docs/PHASE6_ACCEPTANCE.md](../docs/PHASE6_ACCEPTANCE.md).
Phase 7 T7-00 through T7-08 are complete. Exact SHA `25914b48e1c5140279720d1a4dfb66483cf744a3`
passed all six jobs in GitHub Actions run `34667037521`. Detailed
T7-00…08 acceptance lives in [../docs/PHASE7_ACCEPTANCE.md](../docs/PHASE7_ACCEPTANCE.md) and
[../project/TASKS.md](../project/TASKS.md).
Phase 8 T8-00 through T8-05 are complete and merged to `master` at `77dbf01`. Simulation domain types,
`SimulationEngine`/`SandboxExecutionProvider` port protocols, `SimulationOrchestrator` application
service, `compute_sensitivity_ranks()`, and Alembic migration `20260909_0020` are implemented.
36 contract tests pass (76 total with existing suites).
Phase 9 T9-01 through T9-06 are complete and merged to `master` at `b95f24b`. `weighted`,
`evidence_weighted` and `constraint_aware` `ConsensusStrategy` implementations, a shared feasibility
gate, `StrategyRegistry` and `ConsensusOrchestrator` are implemented per
[../docs/CONSENSUS_MODEL.md](../docs/CONSENSUS_MODEL.md) and
[../docs/consensus-formalism/](../docs/consensus-formalism/). 13 unit tests pass (620 total, 43
pre-existing unrelated skips). Phase 10 (reasoning graph & traceability) is starting next.
Summary: RAG & memory (5) · domain reasoning (6) · critic loop (7) · simulation (8) ·
consensus engine (9) · graph & traceability (10) · neuro-symbolic Z3 (11) · MARL
environment (12) · trustworthiness (13) · full UI (14) · MCP gateway (15) · research
extensions (16) · Swarm & hardening (17).

---

## Standing tasks (never "done")

| ID | Task |
| --- | --- |
| TS-01 | Update memory bank + project state after every significant unit of work |
| TS-02 | Keep `memory-bank/api-contracts.md` and `docs/API_CONTRACTS.md` synchronized with code |
| TS-03 | Record every significant error in `memory-bank/errors.md` with root cause + prevention |
| TS-04 | Write/refresh `docs/consensus-formalism/<plugin>.md` for every consensus plugin |
| TS-05 | Re-run the anti-pattern checklist (docs/ANTI_PATTERNS.md) at each phase exit |
