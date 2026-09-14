# Current State

**As of:** 2026-09-14 · **Phase:** 14 in progress · **Active task:** T14-04 Explanation Panel complete
**Track:** MVP · **Confidence:** Phases 0–4, 6–10 exact-SHA remote evidence; Phase 5 local gates green; Phase 13 local gates green

Phase 14 T14-04 Explanation Panel is complete. Authenticated
`GET /api/v1/sessions/{session_id}/explanation` composes the latest persisted consensus result and exact
explanation with recommendations, alternatives, evidence/citations, Assumption Register, complete Critique
handoff, risks/uncertainties, symbolic feasibility, conditions, authored counterfactuals and provenance. It
does not recompute consensus or generate prose. Required drivers, inhibitors and absent-data sections carry
explicit empty reasons; persisted numbers carry kind/unit/version/caveat; weakest evidence is selected only
from recorded verification/lifecycle/citation/relation facts. The code-split panel exposes executive, expert,
formal and exact machine-readable views with keyboard, screen-reader and responsive behavior. No migration
or persistence was added; Alembic remains `20260914_0026`. Focused, live PostgreSQL, full local,
contract/docs and isolated Compose gates pass. T14-05 Replay Controls is next and has not started.

Phase 14 T14-03 Assumption Register is complete. Authenticated
`GET /api/v1/sessions/{session_id}/assumptions` composes every persisted ASSUMPTION, CONSTRAINT and
UNCERTAINTY revision with lifecycle, attribution, provenance, supporting/opposing/qualifying evidence,
dependents, recommendation exposure, active critiques and graph identities. Constraints include exact
formalization/evaluation facts and preserve `SAT → PROCEED`, `UNSAT → BLOCK`, and `UNKNOWN → DEFER`; missing
formalization/evaluation is explicit. The code-split React register distinguishes artifact kinds and
ACTIVE/SUPERSEDED/WITHDRAWN/DISPUTED states with keyboard, screen-reader and responsive behavior. No
migration or persistence was added; Alembic remains `20260914_0026`. Focused, live PostgreSQL, full local,
contract/docs and isolated Compose gates pass. T14-04 Explanation Panel is next and has not started.

Phase 14 T14-02 Dissent View is complete. Authenticated
`GET /api/v1/sessions/{session_id}/dissent` composes the latest persisted consensus explanation, selected
alternative context, supporting/opposing/qualifying evidence, complete Critique handoff, exact artifact
lifecycle and existing graph/provenance links. It has no omission or filter parameter and returns explicit
not-evaluated, explanation-unavailable and evaluated-without-dissent states. The code-split React view keeps
minority positions, abstention, critique type/severity/resolution and evidence relation distinct; it exposes
keyboard navigation, textual labels, visible focus and responsive layouts without a composite score. No
migration or new persistence was added; Alembic remains `20260914_0026`. Focused API/frontend tests, the
live HTTP/PostgreSQL fixture, full local gates and isolated Compose deployment are green.

Phase 14 T14-01 Graph View is complete. Authenticated `POST /api/v1/graph/subgraph` is a thin public-ID
boundary over `ReasoningTransaction.graph.subgraph()`: it validates tenant/session-visible roots, radius,
closed edge filters, page size and query-bound cursors, and preserves deterministic ordering plus independent
truncation/pagination. The code-split React Graph View uses TanStack Query for server state and provides
distinct labelled edge semantics, SVG and textual equivalents, keyboard selection, visible focus, explicit
loading/error/empty/pagination/truncation states, and desktop/mobile layouts. No migration, persistence,
repository or traversal implementation was added. Focused API/graph/frontend tests, 807 offline backend
tests, 30 frontend tests, strict/static/contract/docs gates and isolated Compose deployment are green;
Alembic remains `20260914_0026`, backend `/ready` and frontend return 200, and the live HTTP/PostgreSQL
fixture passes.

Phase 14 task authority remains frozen in [PHASE14_ACCEPTANCE.md](../docs/PHASE14_ACCEPTANCE.md): T14-01 Graph
View, T14-02 Dissent View, T14-03 Assumption Register, T14-04 Explanation Panel, T14-05 Replay Controls and
T14-06 Audit Search, in that order. T14-01…04 are complete and T14-05…06 remain open. The contract preserves earlier-phase domain,
storage and requirement ownership: Phase 14 adds authenticated API exposure and accessible UI presentation,
not replacement graph, consensus, symbolic, replay, manifest or audit infrastructure. The scripted phase
fixture is defined but has not passed.

Phase 13 T13-04 is complete locally. `RunManifestDocument` is the strict, canonical version-1 run
identity. It pins code/images, migration/artifact schemas, configuration/protocol/budget/consensus,
agent/prompt/inference, retrieval/index, metric, symbolic, simulation, Phase 12 MARL, content and scoped
randomness identities. `RunManifestService` creates immutable creation pins and finalizes exactly once by
writing canonical JSON to content-addressed object storage. Migration `20260914_0026` adds one
`reproducibility_manifests` row per tenant/session, optional same-workspace source-session lineage,
forced RLS, tenant-safe foreign keys and a trigger that allows only `CREATED → FINALIZED` and rejects
all later mutation/deletion. `PersistedReplaySource` integrates T13-03 with exact finalized
id/version/hash lookup, digest verification and canonical-byte validation; there is no latest fallback.
No HTTP/API was added. NFR-003 and NFR-014 are implemented for the Phase 13 replay/manifest scope.
Validation is green: 16 focused replay/manifest tests, 792 non-integration tests, 57 PostgreSQL
integration tests with 8 unrelated service-gated skips, strict mypy over 314 files, one Alembic head
`20260914_0026` with no drift, offline migration SQL, traceability, links, Compose build/readiness and
deployed manifest/STRICT replay acceptance.

Phase 13 T13-03 is complete locally. `backend/app/domain/replay.py` defines the closed
`REPLAY_STRICT` / `REPLAY_TOLERANT` / `REPLAY_LIVE` modes and immutable manifest references,
historical inputs, exact implementation identities, replay steps, executions, first mismatches,
structured differences and results. `backend/app/application/replay.py` provides exact-version
`ReplayImplementationRegistry` and exhaustive `SessionReplayService` orchestration. All modes first
bind the request to a caller-scoped `ReplaySource`, verify the authoritative ledger chain and exact
recorded event sequence, and reuse Phase 12 `verify_bundle()` for captured MARL trajectories without
changing MARL semantics. STRICT reconstructs recorded provider/retrieval steps without calls, invokes
only deterministic non-external exact-version implementations, and fails on the first output/status
divergence. TOLERANT re-executes only explicitly allowed steps and reports ordered implementation,
provider, model, configuration, output, status and timing-sensitive differences; it returns `MATCHED`
or `DIFFERENT`, never `VERIFIED`. LIVE delegates new execution to `LiveReplayLauncher`, requires source
linkage plus fresh session/manifest/event/result identities, and returns `LIVE_STARTED`, never a
reproduction claim. T13-03 adds no API or persistence: durable run manifests and database-backed live
lineage remain T13-04. Eleven focused tests cover all stated boundaries, including no external strict
calls, historical immutability, cross-workspace denial and deterministic ordering.

Phase 13 T13-01 and T13-02 are complete locally. T13-02 ships the Phase 13 audit substrate: migration
`20260912_0025` adds tenant-safe forced-RLS, caller-append-only `access_log` and `audit_anchors`
(shared `BEFORE UPDATE OR DELETE` trigger raising sqlstate 27000, `REVOKE UPDATE, DELETE`,
`(workspace_id, session_id)` FK into `sessions`), and the eight audit queries (Q1–Q8 of
[AUDITABILITY.md](../docs/AUDITABILITY.md)) as typed application services
(`backend/app/application/audit.py`) over new domain contracts (`backend/app/domain/audit.py`),
DB adapters (`backend/app/db/audit.py`), and `ConsensusResultStore.get_round_result`
(`backend/app/db/consensus.py`). Design invariants kept: Q1 origin walks `causation_id` (≤32 hops),
Q7 is bounded strictly before `recommendations.created_at`, all helper logic is pure
(`_anchor_facts` shared module function makes anchor hashes deterministic and documentable), and
verification (`ChainVerificationService.chain_integrity`) recomputes each day-head from the ledger
with `reasoning_ledger.verify`. No HTTP/OpenAPI added (Phase 14); no event emit for
status/context/round-terminal events (they remain doc fiction). Evidence: 21 focused unit tests and
7 live PostgreSQL acceptance tests (append-only, RLS 42501 isolation, FK 23503, same-day anchor
conflict, two-day chain, tamper detection) plus the census test
`test_reasoning_revision_downgrades_reupgrades_and_has_no_drift` extended with the Phase 13 table
set. Docs: AUDITABILITY.md 1.4 and DATA_MODEL.md §11.1 now describe the implemented tables.
Traceability FR-807/NFR-006 flipped to implemented (`last_verified: local-phase13-2026-09-14`), 104 generated rows
with no drift. Full local validation: unit `698 passed`, PostgreSQL integration `55 passed, 8 skipped`,
strict mypy over 305 files, `alembic check` reports no
new upgrade operations, links green over 90 Markdown files, `git diff --check` clean, Compose config
valid, and the backend image builds.

Phase 13 T13-01 is complete locally. The [METRICS.md](../docs/METRICS.md) catalogue is now shipped as 43
immutable `MetricDefinition` value objects behind the new `MetricPlugin` port
(`backend/app/ports/metrics.py`), a deterministic domain `MetricCatalogue`
(`backend/app/domain/metrics.py`) and a 43-entry application catalogue
(`backend/app/application/metrics.py`): EP-01…06, RR-01…07, DH-01…07, CQ-01…06, RB-01…05, CE-01…05,
HO-01…04, CA-01…03. Every definition carries the six admission fields (profile/dimension, label,
direction, interval/enum range, unit, ID) from METRICS.md and its authored `inputs`/
`interpretation`, which the document now declares as the executable authority. `MetricCatalogue`
rejects duplicates/empties, orders deterministically, and `get(metric_id, metric_version)` fails
closed with no "latest" fallback. Thirteen focused tests transcribe METRICS.md field-by-field, verify
the FR-901 no-single-score profile rule, and pin the Phase 12 reward metrics (`ep-02`, `dh-03`,
`dh-02`, `cq-03`, `ce-03`) at version `"1"`. Traceability now records FR-901 and NFR-019 as partial
and FR-902 as implemented (`last_verified: local-phase13-2026-09-14`); the generated
[TRACEABILITY.csv](TRACEABILITY.csv) rose to 104 rows with no drift. No metric engine,
`metric_values` storage, API, UI, replay or migration was added; Alembic head remains
`20260912_0024` and MARL reward computation is unchanged. The Compose stack was also isolated under
project name `agora_opencode` with env-parameterized loopback host ports (`POSTGRES 15432`, `REDIS
16379`, `MINIO 19000/19001`, `NATS 14222/18222`, `TEMPORAL 17233/18080/15433`, `BACKEND 18000`,
`FRONTEND 13000`) and dedicated volumes/networks so it cannot collide with an existing `agora`
deployment. Validation is green end-to-end on this stack: the non-integration suite runs
`755 passed, 56 deselected` and the integration suite inside the isolated stack runs `56 passed`; the gate
surfaced and fixed two pre-existing Phase 12 alembic-chain defects (E-21: ORM metadata omitted
`ck_marl_episodes_status_shape`; E-22: head acceptance held a Phase 10 literal), with head
`20260912_0024` unchanged and no new migration.

Phase 12 T12-01 through T12-05 are complete locally. Strict infrastructure-neutral contracts model source
snapshots, observations/features, proposals/executions, coordinator decisions, a fixed five-component exact
reward vector, non-causal conserved provenance credit, transitions, terminal observations, and explicit
incomplete markers. Canonical export is exactly `manifest.json` plus `trajectory.jsonl`; bounded hermetic
verification uses only those bytes and a local implementation registry and returns one deterministic failure.
In-memory and PostgreSQL stores share immutable append-or-conflict semantics. Migration `20260912_0024`
adds forced-RLS tenant-safe episode/record storage and append-only guards. MARL is not composed into production
consensus; no learner, Phase 13 metric engine, or full-session `REPLAY_STRICT` was added.

Phase 10 T10-01 through T10-04 and the phase exit gate are complete locally on
`phase10-reasoning-graph`. T10-02 exposes bounded
artifact provenance through the existing cycle-safe backward traversal and enriches EVIDENCE nodes from
canonical citation records, including exact source/document/chunk identity, evidence verification, and
current source retraction status. SOURCE/DOCUMENT/CHUNK remain outside the graph schema. Five focused
provenance tests pass. Live citation/provenance persistence acceptance passed against a fresh disposable
`pgvector/pgvector:pg16` database using only a subprocess-scoped `TEST_DATABASE_URL`; the container was
removed afterward. The implementation SHA under test was `e86e9ca24c06b8139a35d510a3c36b372f3499be`.
T10-03 now generates all 104 traceability rows from 74 documentation, 46 source, and 511 test
annotations. The semantic audit retained 77 sole-`NFR-016` tests, reassigned 149, and narrowed broad
Phase 8/9 mappings. The latest non-integration run passes 677 tests with 52 service-dependent tests
deselected. Strict mypy passes over 267 files.
Mapping coverage is not a claim that every requirement is implemented or behaviorally verified.
T10-04 adds workspace-wide cycle-safe source-impact traversal, immutable exact-version dependency
snapshots, explicit completeness state, and atomic `SOURCE_RETRACTED` workspace-outbox publication. It
reports exposure without mutating downstream artifacts. Retraction and report reads are authenticated,
tenant-scoped APIs with opaque IDs and idempotent command handling. Two live PostgreSQL tests pass on a
fresh disposable pgvector/PostgreSQL 16 database, including migration drift, forced RLS, append-only
enforcement, rollback atomicity, exact dependency round-trip, and outbox publication.

T11-01 is complete on `phase10-reasoning-graph`. PostgreSQL now owns immutable formalisation revisions,
deterministic validation facts, and explicit human decisions. The API derives `CANDIDATE`, `VALIDATED`,
and `REJECTED`; only a successful exact-AST validation plus human confirmation is enforceable. The AST
is closed and typed, symbols declare meaning/sort/unit, source and premises pin exact artifact revisions,
and the canonical hash uses the existing RFC 8785/JCS implementation. Focused evidence is 7 passing
domain/API tests and one passing disposable-PostgreSQL test covering migration drift, forced RLS,
append-only enforcement, and confirmation constraints. No Z3, satisfiability result, witness, unsat core,
model checking, or symbolic-evaluation persistence was introduced.

T11-02 is complete. The AGORA-owned `SymbolicReasoner` port now has a Z3 infrastructure adapter that
explicitly translates every closed T11-01 node/operator and BOOLEAN/INTEGER/REAL declaration, preserving
canonical decimals as exact rationals. Every call uses a fresh solver context and bounded validated timeout;
results are immutable `SAT`, `UNSAT`, or first-class `UNKNOWN` values with revision/hash and reproducibility
metadata. Invalid/unsupported input and solver failure are separate fail-closed errors. No API, migration,
result persistence, model/witness, unsat core, graph edge, outbox fact, or lifecycle mutation was added.
`VALIDATED != SAT`; enforceability remains exactly the T11-01 rule.

T11-03 extends the solver-neutral result with exact typed SAT witness bindings and contradiction-sufficient
UNSAT cores identified by stable AST paths. A caller-transaction-owned service persists those outcomes against
the exact revision/hash and solver configuration in a forced-RLS append-only table. Idempotent re-evaluation
returns identical evidence. T11-03 added no HTTP API, graph, outbox, lifecycle, or violation-policy behavior.

T11-04 and Phase 11 are complete. The application-owned policy maps `SAT` to `PROCEED`, `UNSAT` to
`BLOCK`, and first-class `UNKNOWN` to `DEFER`; timeout, incomplete, and other unknown causes receive
stable classifications and deterministic explanation metadata. Policy derivation follows immutable
evaluation persistence and never rewrites solver evidence. The shared consensus feasibility gate is the
only downstream consumer: unresolved alternatives stay visible in its trace and can only be selected as
explicit `CONDITIONAL_CONSENSUS`, never as symbolically assured. No migration, API, graph, outbox, lifecycle, retry, or override behavior
was added. Phase 12 is next in the task register and has not started.
## Where the project actually is

Phase 0 is complete and was approved by the project owner on 2026-09-04 (D-13). Its documentation and
contract baseline remains normative.

Phase 1 is complete. T1-00 through T1-15 satisfy their acceptance criteria. A `backend/` package,
enforced import boundaries, executable ports/adapters, a lifespan-managed FastAPI factory, async
SQLAlchemy database wiring, Alembic migrations with forced PostgreSQL RLS, pgvector cosine storage,
liveness/readiness probes, uniform error handling, and configuration exist. Bearer authentication and
explicit route-role policy are deny-by-default; users are external-identity projections and workspace
memberships carry the canonical four-role enum. The development Compose stack builds the locked backend
image, runs migrations and bucket initialization, and brings Postgres, Redis, MinIO, NATS, and the
backend to healthy. T1-12 observability is implemented with app-scoped OpenTelemetry and Prometheus,
authenticated metrics, SQLAlchemy telemetry, and recursively redacted logs. The 70 non-integration
tests pass; Ruff and mypy across 81 source files are green. The live API-to-PostgreSQL acceptance test
passes against the Compose PostgreSQL service and observes server/database span relationships without
SQL leakage. An authored OpenAPI 3.1 contract now generates the strict TypeScript client with
no diff; the React/Vite operational skeleton uses TanStack Query and ships as a non-root static image.
GitHub Actions gates backend and frontend quality, contracts, links, traceability, empty-session replay,
the complete Compose stack, all live adapters, and the API-to-PostgreSQL trace. Run `33923240340`
passed every required job and closes T1-15.

Phase 2 is complete. Provider-neutral generation and embedding contracts have OpenAI-compatible and
deterministic mock adapters, structured-output validation with bounded repair, content-addressed raw
traces, and durable per-call token/cost accounting. Tenant-scoped LLM configurations, envelope-encrypted
credentials, versioned agent definitions, forced RLS, and database-enforced immutability are implemented.
One agent definition ran through two distinct OpenAI-compatible endpoints and the mock, producing three
traceable cost records. The Compose stack reached healthy; 95 non-integration tests and all 7 live
integration tests passed. No production SDK import exists outside `app/adapters/`.

Commit `5034e7b07cefec9532fc8930f086e5da082bf6d9` is pushed to `origin/master`. GitHub Actions run
[`33952091288`](https://github.com/potatosaladz/agora/actions/runs/33952091288) completed successfully
for that exact SHA.

Phase 3 contract T3-00 is complete. The frozen baseline uses exactly the 14 FR-301 artifact kinds in
one versioned `reasoning_artifacts` contract; opinion is `Position`, hypothesis is a typed `Claim`, and
`Fact` is first-class with opaque Phase 3 source provenance. Lifecycle is `ACTIVE`, `SUPERSEDED`, or
`WITHDRAWN`. Session creation binds problem, pinned agents, inline objectives/constraints and budget
without starting Temporal. The ledger uses four actor classes, a locked per-session head, gapless
committed sequence, RFC 8785 JCS and exact payload/event hash preimages.

T3-01 through T3-08 are complete locally. The domain now has strict immutable values for every reasoning
artifact plus canonical content identity, and a separate immutable `DRAFT` session aggregate binding the
problem, pinned agent-definition versions, typed objectives/constraints and bounded budget. Proposition
normalization is typed and versioned; deterministic normalization identity excludes original prose and
review status, while ambiguous normalizations are rejected from consensus input. Migration
`20260905_0005` and matching SQLAlchemy rows persist only the frozen draft-session and unified artifact
schema. Composite tenant foreign keys, strict JSONB checks, deferred revision/reference/binding triggers,
immutable artifact content, delete prevention, indexes and forced RLS are database-enforced. Clean upgrade,
downgrade to `20260905_0004`, re-upgrade, `alembic check`, and the exact five-table migration delta pass on
PostgreSQL 16. Migration `20260905_0006` and matching graph rows/adapter add tenant-safe graph projections
inside caller-owned transactions. The database enforces artifact-kind resolution, the complete endpoint
matrix, tenant/session affinity, no self-loops, unique triples, incident-edge-safe node updates and forced
RLS. Automatic decomposition and the Phase 4 workflow state machine are not claimed.
Migration `20260905_0007`, ledger domain values, SQLAlchemy rows and the caller-transaction-scoped
append/read/verify adapter now persist a per-session hash chain. Locked head rows provide gapless committed
sequence allocation; retries are content-checked, rollback consumes no sequence, and canonical payload/event
hashes verify against the frozen preimage. PostgreSQL enforces tenant-safe references, forced RLS, automatic
session-head creation and append-only mutation rejection. A transaction-level `ArtifactCommitService` now
composes a typed artifact store, graph projection and ledger: initial commit writes all three, revision
inserts a new row and `SUPERSEDES` edge while locking/superseding the predecessor, declared parent
relationships project to graph edges, and withdrawal changes only lifecycle state while appending a
warranted event. The caller owns commit/rollback, and a deferred-constraint
failure proves artifact, graph and ledger writes all roll back without consuming sequence.
The tenant-scoped HTTP boundary now creates and reads draft sessions and creates, reads, revises and withdraws
artifacts through the same caller-owned transaction. RBAC, durable workspace-scoped idempotency, changed-request
conflicts, `If-Match`, public typed IDs and explicit unsupported claims are enforced. Migration
`20260905_0008` persists forced-RLS idempotency records. Authored OpenAPI and generated TypeScript remain in
sync. Current evidence is 210 offline tests and 22 configured PostgreSQL integration tests; Ruff format/lint,
strict mypy over 123 files, frontend lint/typecheck/6 tests/build, contracts and migration generation are green.

T3-08 adds the accessible reasoning desk and browser walkthrough from complete session manifest through
structured proposition and explicit unsupported hypothesis. FR-101…103 and FR-301…312 now have implemented
matrix rows with resolvable code and exact test-node evidence. Unit, exhaustive property, generated-contract,
UI/accessibility and live PostgreSQL suites cover the frozen verification methods. Current evidence is 226
offline tests passed and 25 live integrations passing with no skips; strict mypy covers 126 files and 9
frontend tests pass with lint, typecheck, build, OpenAPI/client drift, trace, links and whitespace green.

T3-09 and Phase 3 are complete. `DATA_MODEL.md` now carries an executable schema
manifest for all 10 Phase 3 tables; a clean PostgreSQL migration matched every documented column, type,
nullability and table delta. All 34 anti-patterns were reviewed with no Phase 3 violation. A disposable
volume-free Compose rebuild reached healthy, `/ready` returned five `ok` components, the frontend returned
200, Alembic was at `20260905_0008` (`head`), and all 26 live integrations passed without skips. The full
backend/frontend/contract/document gate is green; detailed evidence is in
[`PHASE3_ACCEPTANCE.md`](../docs/PHASE3_ACCEPTANCE.md).

Commit `7aaf1aabdc74a8cdba283d4524759eb1db6a0d03` is pushed to `origin/master`. GitHub Actions run
[`33989090448`](https://github.com/potatosaladz/agora/actions/runs/33989090448) passed all six required jobs
for that exact SHA and closes T3-09.

Planning commit `0eb5810fe2ddb4b7e069c068922e2a712dd0e071` is pushed. GitHub Actions run
[`33952819808`](https://github.com/potatosaladz/agora/actions/runs/33952819808) completed successfully
for that exact SHA.

T4-01 is complete locally. The public workflow boundary is split into a typed client
`WorkflowEngine` and lifecycle-only `WorkflowWorker`; concrete SDK definitions never cross the port.
Temporal SDK 1.32.0, Server 1.29.1 and UI 2.34.0 are pinned. Start uses workflow-id idempotency with
duplicate rejection, and Temporal state is explicitly diagnostic while PostgreSQL/ledger state remains
authoritative. Compose is healthy with Temporal and its separate PostgreSQL 16 store; `/ready` reports
six `ok` components. Final evidence is 240 offline and 28 live tests, including real Temporal
start/duplicate/describe and worker poll/complete; Ruff, strict mypy over 137 files, links, contracts,
traceability, Compose config and whitespace gates are green. No session workflow, activity, signal or
control behavior was introduced in T4-01.

T4-02 is complete. The full lifecycle graph is validated in the domain and persisted in the
forced-RLS `session_lifecycles` projection added by migration `20260905_0009`. Projection changes and
reasoning-ledger appends are row-locked and atomic, including exact event-ID retries. T4-02 introduced the
deterministic `SessionBootstrapWorkflow` and its `SESSION_INITIALIZED` activity transition; API-allocated
event IDs remain immutable workflow input. The separate idempotent
`POST /api/v1/sessions/{id}/start` endpoint returns `202` and reattaches the original Temporal run after
an API transaction rollback. Evidence is 252 offline backend tests, strict mypy over 149 files, Ruff,
frontend contract/lint/typecheck/10 tests/build, migration drift checks, and focused live PostgreSQL and
Temporal tests. The cumulative T4-03 exact-SHA CI run below covers this implementation.

T4-03 is complete. Strict protocol-versioned agent-turn activities resolve pinned agent and LLM
configuration state without retaining transaction-scoped SQLAlchemy sessions, load and hash-check sealed
prompt artifacts before provider invocation, persist normalized completed-call usage, reject malformed or
authority-escalating proposals, and close turn-scoped providers deterministically. The production Temporal
worker registers `run_agent_turn`. Bootstrap now persists round-one `ROUND_STARTED`, so PostgreSQL reaches
`RUNNING`/round 1 before the workflow waits. Evidence is 274 offline tests, strict mypy over 153 files,
Ruff, 22 focused agent-turn tests, and focused live PostgreSQL and Temporal proofs. GitHub Actions run
[`34005422198`](https://github.com/potatosaladz/agora/actions/runs/34005422198) passed all six jobs for exact
implementation SHA `8cc835f4029aca5964c388513aeaba1fc02af4d3`.

## Document inventory

| Area | Documents | Status |
| --- | --- | --- |
| Foundations | [README](../docs/README.md), [REQUIREMENTS](../docs/REQUIREMENTS.md), [ARCHITECTURE](../docs/ARCHITECTURE.md), [DATA_MODEL](../docs/DATA_MODEL.md), [PORTS](../docs/PORTS.md) | design |
| Reasoning core | [STRUCTURED_REASONING](../docs/STRUCTURED_REASONING.md), [REASONING_GRAPH](../docs/REASONING_GRAPH.md), [AGENT_MODEL](../docs/AGENT_MODEL.md), [AGENT_PROTOCOLS](../docs/AGENT_PROTOCOLS.md) | design |
| Research core | [CONSENSUS_MODEL](../docs/CONSENSUS_MODEL.md), [EPISTEMIC_MODEL](../docs/EPISTEMIC_MODEL.md), [METRICS](../docs/METRICS.md) | design |
| Knowledge | [RAG_ARCHITECTURE](../docs/RAG_ARCHITECTURE.md), [MEMORY_ARCHITECTURE](../docs/MEMORY_ARCHITECTURE.md), [SIMULATION_ARCHITECTURE](../docs/SIMULATION_ARCHITECTURE.md) | design |
| Formal | [NEURO_SYMBOLIC](../docs/NEURO_SYMBOLIC.md), [MARL_MODEL](../docs/MARL_MODEL.md) | design |
| Interfaces | [API](../docs/API.md), [API_CONTRACTS](../docs/API_CONTRACTS.md) | design |
| Trustworthiness | [AUDITABILITY](../docs/AUDITABILITY.md), [EXPLAINABILITY](../docs/EXPLAINABILITY.md), [TRACEABILITY](../docs/TRACEABILITY.md), [REPRODUCIBILITY](../docs/REPRODUCIBILITY.md), [EXPERIMENTATION](../docs/EXPERIMENTATION.md) | design |
| Security & ops | [SECURITY](../docs/SECURITY.md), [THREAT_MODEL](../docs/THREAT_MODEL.md), [MCP_SECURITY](../docs/MCP_SECURITY.md), [DEPLOYMENT](../docs/DEPLOYMENT.md), [DOCKER_SWARM](../docs/DOCKER_SWARM.md), [OBSERVABILITY](../docs/OBSERVABILITY.md) | design + implementation status |
| Guidance | [MVP_BOUNDARY](../docs/MVP_BOUNDARY.md), [TESTING](../docs/TESTING.md), [EXTENDING](../docs/EXTENDING.md), [ANTI_PATTERNS](../docs/ANTI_PATTERNS.md), [RESEARCH_NOTES](../docs/RESEARCH_NOTES.md) | design |
| Decisions | 20 ADRs in [../docs/adr/](../docs/adr/README.md) | accepted |
| Formalisms | 6 strategy specs + template in [../docs/consensus-formalism/](../docs/consensus-formalism/README.md) | 3 MVP, 3 research |
| Project state | [PLAN](PLAN.md), [TASKS](TASKS.md), [DECISIONS](DECISIONS.md), [ERRORS](ERRORS.md), [HANDOFF](HANDOFF.md), [TRACEABILITY.csv](TRACEABILITY.csv) | current |

## What was fixed in this pass

The memory bank claimed `T0-05 … T0-10` were done while several referenced documents did not exist on
disk, and existing documents linked to files that had never been written. The reconciliation:

- created the 18 missing documents listed above;
- created `docs/adr/README.md` (index + dependency graph) and `docs/consensus-formalism/TEMPLATE.md`;
- wrote the project state set: [PLAN.md](PLAN.md), [TASKS.md](TASKS.md), [DECISIONS.md](DECISIONS.md),
  [ERRORS.md](ERRORS.md), [HANDOFF.md](HANDOFF.md), this file, and a hand-seeded
  [TRACEABILITY.csv](TRACEABILITY.csv);
- corrected `docs/README.md` so its index matches the filesystem;
- unified every `Phase:` field against the roadmap in [../README.md](../README.md) (decision D-08);
- aligned cross-references with the real section numbers of `REQUIREMENTS.md`, `DATA_MODEL.md`,
  `PORTS.md` and `ARCHITECTURE.md`;
- rewrote `memory-bank/tasks.md`, `activeContext.md`, `progress.md` and `CHANGELOG.md` to describe what
  is on disk, including the consensus-formalism filenames, which the changelog had guessed wrong.

## Phase 1 acceptance audit

| Tasks | Result | Missing evidence for open work |
| --- | --- | --- |
| T1-00, T1-01, T1-02, T1-03, T1-04, T1-11 | Complete | measured versions; green Ruff/mypy/pytest; app-factory lifecycle and API behavior tests; AST import-boundary lint with forbidden-import self-tests; clean PostgreSQL migration and non-owner cross-tenant RLS proof; tested production secret-provider refusal |
| T1-05 | Complete | pgvector extension; forced-RLS vector table; cosine IVFFlat index; deterministic 1,000-vector retrieval and tenant-isolation proof |
| T1-06 | Complete | Redis persistence disabled; every cache/rate-limit write has a 1–86,400 second TTL; fixed-window and actual expiry proven against Redis 7 |
| T1-07 | Complete | real MinIO upload/get, presigned HTTP read, digest tamper detection, and anonymous bucket-list denial |
| T1-08 | Complete | real NATS JetStream publish/subscribe, NAK redelivery of the same `event_id`, and one consumer-side effect after event-ID deduplication |
| T1-09 | Complete | clean `docker compose up --wait` exit 0; every long-running service healthy; init jobs exit 0; `/ready` all `ok`; Alembic at head; five live integrations pass |
| T1-10 | Complete | bearer verifier port; only health/readiness public; missing policy denied; all four roles tested; canonical membership enum and forced-RLS isolation proven on PostgreSQL |
| T1-12 | Complete | targeted live PostgreSQL trace passed; all six integration tests passed with no skip; server/DB relationship, metrics, correlation, and SQL non-leakage assertions held |
| T1-13 | Complete | authored OpenAPI validates; generated client has no diff; strict typecheck, lint, six tests, accessibility check, and production build pass |
| T1-14 | Complete | six-job GitHub Actions workflow gates lint, typecheck, unit, contract, integration, links, traceability seed, replay, and aggregate status |
| T1-15 | Complete | expanded Compose stack and local equivalents are green; GitHub Actions run `33923240340` passed every required job |

The review also fixed a real replay defect in `InMemoryEventBus.read_from()` and added regression tests.

## Known open items

| # | Item | Why it blocks |
| --- | --- | --- |
| 1 | `project/TRACEABILITY.csv` is hand-seeded | [TRACEABILITY.md §3](../docs/TRACEABILITY.md) requires it to be generated from `# trace:` annotations in Phase 10; the Phase 1 checker validates its shape and references only |
| 2 | Choose the evaluation task suite | every experiment in [EXPERIMENTATION.md](../docs/EXPERIMENTATION.md) needs it |
| 3 | Validate a second production vendor | Phase 2 proved two compatible endpoints plus the mock; vendor credentials and budget remain a deployment follow-up, not a Phase 3 blocker |

## Risks carried into Phase 1

| Risk | Mitigation in the design |
| --- | --- |
| Documentation drifts from code | [TRACEABILITY.md](../docs/TRACEABILITY.md) CI checks; AP-19, AP-20 |
| Phase 0 becomes a permanent state | [MVP_BOUNDARY.md](../docs/MVP_BOUNDARY.md) acceptance criteria are testable, not rhetorical |
| The team builds a chat UI with extra steps | P-1 … P-10 anti-patterns, and the no-single-score rule |
| Scope creep from the research track | §6 of [MVP_BOUNDARY.md](../docs/MVP_BOUNDARY.md) exit criteria for research items |

## Next

Phase 4 is complete. State commits remain atomic PostgreSQL lifecycle/ledger transactions. Newly
committed rows publish to `session.{workspace}.{session}.committed` only after commit; NATS wakes the SSE
gateway but cannot provide replay or ordering authority. Authenticated SSE resumes from PostgreSQL with
`Last-Event-ID`/`ledger_seq`, emits only reference payloads, and has a strict authored event schema. The UI
stores a minimal session/token recovery pointer, reloads the authoritative projection after browser reopen,
and deduplicates ordered ledger events.

Recovery evidence includes a real NATS ledger-to-SSE path, terminal browser rehydration, replacement-worker
PostgreSQL exact replay, and a real Temporal worker shutdown/replacement after simulated post-commit
acknowledgement loss. Validation is 326 non-integration backend tests, 25 frontend tests, focused live
PostgreSQL/NATS/Temporal tests, Ruff, strict mypy over 173 files, frontend lint/build, authored-contract path
checks, and generated TypeScript drift checks. Final SHA
`d9efa51cbb2fee52b6d32bf47e3346b31d7d392b` passed all six jobs in GitHub Actions run
[`34031523362`](https://github.com/potatosaladz/agora/actions/runs/34031523362).

Phase 5 T5-00 freezes retrieval/memory contracts before runtime work. Detailed T5-01…09 tasks cover
deterministic ingestion, tenant-safe provenance storage, durable indexing, hybrid retrieval,
pre-ranking namespace grants, resolvable citations, validated memory promotion and baseline evidence.
Decisions D-034…037 select a domain-neutral synthetic mechanics corpus, normative 800/150 chunking,
grant-based namespace authorization including global corpora, and PostgreSQL provenance authority over
the derived vector index.

T5-01 adds strict immutable ingestion values, deterministic `agora-whitespace-v1` chunk identity and
format adapters for PDF, DOCX, TXT, Markdown, CSV, XLSX, JSON and HTML. Structure locators preserve
pages, sections, paragraphs, tables, rows, sheets, JSON paths and exact character spans. Table rows
remain whole and repeat headers; malformed, empty or invalid-UTF-8 documents fail as permanent parser
errors. Parser/chunker versions are pinned on output. Evidence: 24 focused tests; 332 non-integration
tests with 32 live integrations deselected; Ruff and format over 170 files; strict mypy over 170 files;
12 layering tests; lock, links, authored-contract and traceability gates all pass.

T5-02 adds strict namespace, grant, source, document and chunk values; transaction-scoped SQLAlchemy
repositories; matching ORM metadata; and linear migration `20260906_0010`. Every new tenant table has
forced RLS. Composite workspace foreign keys prevent cross-tenant namespace, source, document, chunk,
session, agent and uploader references. Database triggers enforce typed grant subjects, immutable
provenance identity and no physical provenance deletion while leaving explicit lifecycle fields mutable.
The frozen data-model SQL now includes the previously prose-only namespace-grant relation and physical
parser/chunker identity columns. Evidence: 335 non-integration tests with 33 integrations deselected; 39
focused ingestion/knowledge/layering tests; 2 focused live PostgreSQL tests covering clean upgrade,
repository round-trip, RLS, cross-workspace FK rejection, immutability, downgrade/re-upgrade and
`alembic check`; Ruff/format over 186 files; strict mypy over 175 files; lock, links, authored-contract and
traceability gates pass.

T5-03 adds strict reference-only source-ingestion activity contracts, a bounded heartbeating Temporal
adapter, content-addressed object read-back verification and deterministic source/document/chunk commit.
Migration `20260906_0011` adds forced-RLS `knowledge_ingestion_operations` as PostgreSQL checkpoint
authority with immutable operation/request identity, attempt counts, independent acquire/parse/embed/index
states, parser warnings and stage-specific redacted permanent/transient failures. Exact retries return the
original IDs; conflicting retries fail permanently; unsupported media remains digest-resolvable but records
an explicit permanent parse failure. Source text becomes lexically ready after parsing while embed/index
lag remains visible. Evidence: 342 non-integration tests, 53 focused ingestion/knowledge/object/layering
tests, and 2 focused live PostgreSQL tests covering RLS, exact replay, failure/retry transitions, clean
upgrade, downgrade/re-upgrade and `alembic check`; Ruff/format over 194 files, strict mypy over 181 files,
lock, links, authored-contract, traceability and compile gates pass.

T5-04 adds migration `20260906_0012` and a typed UUID-backed knowledge vector index over existing derived
`vector_items`. Composite foreign keys bind namespace, chunk, document and source in one workspace. Writes
resolve the authoritative chain and exact chunk hash in SQL; sorted namespace advisory locking pins one
embedding model/version under concurrent indexing without reversed-order deadlocks. Queries reject
model/version mismatch, exclude stale hashes and non-ready sources/documents, and break cosine ties by chunk
UUID. Existing Phase 1 string-keyed `VectorStore` behavior remains compatible while colliding writes fail
closed. Evidence: 345 non-integration tests passed with 35 integration tests deselected; 6 authoritative
live PostgreSQL migration, persistence, RLS, vector-index and pgvector-store tests passed in 15.03s, and
disposable-container cleanup exited 0. Ruff, format, strict mypy over 182 files, offline migration SQL,
compile, layering, contracts, links and traceability pass. Frontend lint, typecheck, production build, 19
tests and generated OpenAPI contract verification pass; generated `types.ts` has no diff.

T5-05 is complete locally. Migration `20260906_0013` adds an immutable generated `tsvector` and GIN index.
Strict retrieval values record query/index/embedding/reranker identities, arm census, provenance, per-arm/
fused/rerank scores and degradation. PostgreSQL resolves active namespace grants and chunk ACLs inside
materialized relations before either lexical or vector score is computed. Application fusion uses stable
RRF (`k0 = 60`); vector outage/index mismatch retains lexical candidates explicitly, while reranker port
failure retains fused order instead of becoming no-match. Evidence: 352 offline tests with 36 integration
tests deselected, 2 focused live PostgreSQL tests, Ruff clean, strict mypy over 187 files, no Alembic drift,
and successful downgrade/re-upgrade to head.

T5-06 is complete locally. Retrieval requests carry stable attempt/trace IDs and explicit human/agent
principal identity. PostgreSQL validates every supplied workspace, user, agent-definition and session
subject, then one materialized authorization relation enforces all six namespace tier contexts before either
scorer. Agent session access requires `session_agents`; forged subjects deny the entire requested scope.
Migration `20260906_0014` adds append-only, forced-RLS `retrieval_attempts`; allowed and denied paths persist
hashes, identifiers, counts, outcome, versions and degradation but never query/chunk text. Audit failure fails
retrieval closed. Evidence: 354 offline tests with 37 integration tests deselected, 3 focused live PostgreSQL
tests, Ruff clean, strict mypy over 190 files, no Alembic drift, and successful `0014 → 0013 → head`.
T5-07 is complete locally. Hits preserve citation, ordered character span, source/chunk digests,
source/document/retrieval timestamps, trust and exact namespace/source/document/chunk IDs. Migration
`20260906_0015` adds append-only forced-RLS `evidence_citations` and `source_retractions`. PostgreSQL
validates active human attribution, evidence/claim identity, stored source references and the full ready
knowledge chain before attachment. Reason-required retraction is irreversible, excludes future retrieval
and preserves old resolution plus Phase 10 dependencies. Evidence: 359 offline tests, 4 focused live
PostgreSQL tests in 8.14s, strict mypy over 196 files and all inherited gates green; Alembic drift and
`0015 → 0014 → head` pass.

T5-08 is complete locally. Working, episodic, semantic and procedural scopes are explicit and remain
owned by Redis TTL state, the reasoning ledger/session artifacts, validated semantic promotion, and
immutable agent configuration respectively. Direct semantic writes fail. Migration `20260906_0016`
adds append-only forced-RLS semantic entries, promotions, evidence sets and lifecycle facts. PostgreSQL
revalidates active humans, historical/global namespace, source/evidence identity, caveats, timestamps and
supersession; deferred constraints reject unpromoted or evidence-free rows. Review expiry derives `STALE`,
and explicit `STALE`/`ARCHIVED` events preserve all authoritative rows. Evidence: 363 offline tests, one
focused live PostgreSQL test, strict mypy over 201 files and inherited gates green; Alembic drift and
`0016 → 0015 → head` pass. T5-09 now has a versioned domain-neutral corpus, exact expected output,
digest/isolation audit proof and durable `RAG_FAILED` semantics. All local gates pass, including 370
offline and 40 live Compose-backed tests; exact-SHA CI remains before Phase 5 completion.

Phase 5 is committed on `phase5-rag` at `45253c8b91c103e9632554de8b31d55a5a5281c4`; it is
not pushed and therefore has no exact-SHA remote evidence yet. Phase 6 proceeds on isolated branch
`phase6-domain-reasoning`. T6-00 freezes T6-01…09, corrects the Phase 6 requirement set, defines
`NO_EVIDENCE` without fabricated UUIDs, and keeps Critic/revision, consensus, metrics/replay and
experiments in their owning phases.

T6-01 is complete locally. Immutable `ReasoningContext` and generic `AgentRuntime` /
`ReasoningStrategy` protocols expose no mutation or peer-agent channel. Exact name/version strategy
selection rejects unknown and duplicate registrations. `ActivityReasoningStrategy` reuses the Phase 4
provider/prompt/usage boundary, while a deterministic in-memory strategy supports offline tests.
Position proposals now require a consistent `CITED` or `NO_EVIDENCE` disposition. Focused evidence:
31 tests, Ruff clean, and strict mypy over six files.

T6-02 is complete locally. `DECOMPOSE` now uses the same pinned provider/prompt/usage activity path.
The canonicalizer version crosses the immutable runtime and activity contracts into the LLM prompt.
`ProblemDecomposer` remains proposal-only and rejects empty, mixed, request-bearing, version-mismatched,
ambiguous, or duplicate proposition output before identity allocation or persistence. Focused evidence:
39 tests, Ruff clean, and strict mypy over nine files.

T6-03 is complete locally. `ReasoningContextAssembler` resolves and revalidates the session, exact
definition/version, active typed objectives/constraints, unique active non-future artifact envelopes,
and agent-authorized retrieval scope/results. Round-one `ASSESS` rejects artifact visibility before any
artifact read. Retrieval errors propagate; a successful zero-match retains searched namespaces, query
hash, index/embedding/reranker versions, counts, degradation and warnings. Immutable definition,
artifact and retrieval snapshots cross the activity boundary into deterministic prompt JSON and are
checked against the durable definition before provider creation. Evidence: 68 focused tests; 416 full
backend tests passed with 40 service-dependent integrations skipped; Ruff clean over `app tests`, strict
mypy over 213 files, layering, traceability, 88-link and whitespace checks green.

T6-04 is complete locally. `AgentProposalCommitter` validates every payload reference before the first
write, rejects fabricated, inactive, future and wrong-kind targets, and derives retry-stable artifact,
graph-node and event identities from the turn and proposal order. A transaction advisory lock serializes
same-turn deliveries; exact complete retries return prior state while partial or conflicting retries fail
closed. Accepted artifacts, graph projections and ledger events share the caller-owned transaction.
Position confidence is required; `CITED` or `NO_EVIDENCE` and complete agent/model/prompt/usage/cost/turn
attribution are hash-covered in artifact metadata and copied into per-artifact plus turn-completion ledger
payloads. Evidence: 53 focused unit tests, one adapter contract and 428 offline backend tests; Ruff and strict mypy are clean over 216
files. The migration-backed PostgreSQL test for concurrent retry, atomic commit and fabricated-reference
rollback is authored but skipped locally because PostgreSQL test settings are not configured.

T6-05 is complete locally. The shipped catalogue creates five active workspace-scoped fiscal,
macroeconomic, social-policy, infrastructure and risk definitions with deterministic UUIDv5 logical/version
identities, distinct objective vectors and stances, and an exact `evidence-first@1.0.0` strategy pin. Five
non-empty UTF-8 prompt resources carry frozen literal SHA-256 digests; loading rejects byte drift, object
keys include the content digest, and staging verifies the `ObjectStore` response. All five definitions run
through the real sealed round-one activity with schema-valid deterministic mock output. Structured response
parsing now uses Pydantic's JSON-native validation so JSON arrays satisfy strict tuple fields while scalar
strictness remains intact. Evidence: 16 focused and 435 offline tests, 220-file Ruff format/lint and strict
mypy gates, clean compile/contracts/traceability/88-link/whitespace checks, and a clean-wheel install that
loaded all five resources with their exact hashes. No T6-05 database migration or live adapter was added;
`TEST_DATABASE_URL` remains unavailable.

T6-06 is complete locally. `AgentTurnDispatcher` preflights the complete turn batch before any worker
invocation: inputs are scoped to one session, round and phase, and round-one `ASSESS` inputs must be sealed.
A fixed worker fleet bounds shared-worker concurrency, while indexed result slots preserve caller/pinned-agent
order independently of completion order. Per-turn deadlines become typed `ABSTAIN` outcomes with
`TURN_TIMEOUT`; cancellation and runtime failures are not reclassified. The worker protocol receives only
immutable proposal inputs and exposes no persistence, workflow-transition or peer-agent channel. Evidence:
7 focused and 442 offline tests, plus the default suite at 442 passed with 41 service-dependent integrations
skipped; Ruff format/lint, strict mypy, contracts, traceability, links and whitespace gates are clean. No
database schema or live adapter changed. T6-07 followed.

T6-07 is complete locally. Strict frozen proposals permit only `DECOMPOSE`, `ROUTE`, or
`ADVANCE_PHASE` recommendations and reject unknown mutation/transition fields at the schema boundary.
`CoordinatorOrchestratorPolicy` depends only on the reasoning ledger, compares every coordinator-owned
identity pin, checks route targets against the eligible set and enforces the fixed immediate phase order.
Each decision appends one retry-stable accepted/rejected event as `ActorClass.POLICY`, with exact
orchestrator attribution, rationale, stable rule/version and `applied: false`; it performs no state change.
Evidence: 22 focused and 464 non-integration tests, 41 service-backed tests deselected, Ruff format/lint and
strict mypy clean over 225 files, and contracts, 54-row traceability, 88-link and whitespace gates green.
No database schema or live adapter changed; `TEST_DATABASE_URL` remains unavailable. T6-08 followed.

T6-08 is complete locally. Migration `20260907_0018` adds append-only, forced-RLS effective-round
membership interventions linked to their reasoning events. Coordinator policy serializes membership
changes with both a transaction advisory lock and the lifecycle row, allows replacement only before round
1 and injection only for the next round, requires active workspace definitions, and replays deltas by
canonical ledger sequence. Context assembly and session-scoped retrieval authorize the effective round,
including removal of replaced definitions. Durable `llm_call_records` totals are checked against typed
session and strict per-definition token/USD ceilings before dispatch and after accounting; a reached ceiling
atomically fails the session once with `BUDGET_EXHAUSTED`. The 20-agent fixture runs through four shared
workers, retains pinned order, and commits 20 attributed claims through the real coordinator committer.
Evidence: 21 focused coordinator/retrieval tests and 474 offline backend tests pass with 42 service-backed
tests skipped; Ruff format/lint and strict mypy over 229 files, offline Alembic SQL, contracts, 54-row
traceability, 88-link and whitespace gates are green. The PostgreSQL membership/RLS/append-only/usage test
and live downgrade/re-upgrade were initially deferred to the T6-09 Compose run recorded below.

T6-09 and Phase 6 are complete. `.gitattributes` pins the five packaged prompt resources to LF before the
loader validates their exact raw bytes against frozen SHA-256 digests. The generated TypeScript client
freshness check normalizes
CRLF/CR to LF before comparison while retaining exact non-EOL drift detection; focused tests cover both cases.
The five prompt worktree resources match their committed LF bytes and literal digests. Evidence: 69 focused
Phase 6 tests and 479 offline backend tests pass; Ruff format/lint and strict mypy over 229 files are clean;
contracts, 54-row traceability, 88-link and whitespace gates pass. Anti-pattern review found no Phase 6
regression: agents remain proposal-only and sealed, evidence absence stays explicit, prompts are digest-pinned,
and coordinator/ledger authority remains singular. On CI-matching Node 22, frontend lint, strict typecheck,
22 tests, production build, OpenAPI validation and generated-client freshness pass. A repository Prettier
configuration now treats the existing platform-native EOL convention as valid, and its full Node 22 format gate
passes without rewriting unrelated files. The disposable Compose stack built, all services reached healthy, and
all 42 live integration tests passed against PostgreSQL and the other live adapters (479 offline tests deselected).
Exact-SHA GitHub Actions run [34148649503](https://github.com/potatosaladz/agora/actions/runs/34148649503)
passed all six jobs for final published commit `6d671acffe7abd3e5b587042457f300e0c442adc`, including the live
integration and aggregate required-check gates. The final test-only fix guarantees AES-GCM tampering with
an XOR bit flip and records the former 1/256 no-op flake; production encryption is unchanged.

T7-00 is complete on `phase7-critic-revision`. [PHASE7_ACCEPTANCE.md](../docs/PHASE7_ACCEPTANCE.md)
reconciles the roadmap aliases with the exact ten FR-501 values and freezes Critic-only proposal authority,
all-artifact target validation, seven author-bound responses, immutable Critique resolution through
`SUPERSEDES`, targeted revision through `RESPONDS_TO`, explicit evidence/simulation request disposition,
stable phase ordering, and a complete internal explanation handoff. Existing Phase 3 artifact/graph/ledger
and Phase 6 runtime/attribution/budget paths remain authoritative.

T7-01 through T7-04 are complete locally. Strict frozen contracts enforce the exact ten FR-501 Critique
types and seven FR-503 responses; aliases and malformed disposition effects fail closed. One shipped
workspace-scoped Critic has adversarial objectives and a digest-sealed LF prompt, and its real mock-backed
activity attacks all 14 artifact kinds. Coordinator dispatch pins assignments to authorized contexts,
retains budget and worker bounds, distinguishes timeout, and emits `CRITIC_INACTIVE` only after three
consecutive completed empty rounds. Atomic commit derives one `ATTACKS` relationship per Critique and
reuses the Phase 3 transaction/idempotency path; type/severity qualify each edge, and the shared path
requires the exact coordinator assignment. Evidence: 86 focused tests and 565 offline tests
pass with 42 service-backed tests deselected; Ruff format/lint and strict mypy over 238 files, contracts,
58-row traceability, 89 links and whitespace are green.

T7-05/T7-06 are complete locally. Provider/accounting metadata now survives the runtime and dispatcher.
Append-only, forced-RLS response request/result rows preserve exact retry identity and explicit disposition
outcomes. The sealed response committer locks both current heads, enforces target ownership and authorized
references, appends every Critique resolution, and for `REVISE` appends a same-kind/logical-id/owner target
successor with coordinator-derived `SUPERSEDES`, `RESPONDS_TO`, and Critique `ATTACKS`. Migration
`20260907_0019` is the single head. Evidence is 23 response-specific and 589 offline tests, Ruff and strict
mypy clean over all 242 app/test files, compile, offline migration SQL, contracts, traceability,
links and whitespace. Two focused tests pass against a disposable PostgreSQL 16/pgvector database, proving
the graph matrix and atomic rollback/commit/retry plus response-table RLS/immutability; migration downgrade/
re-upgrade and drift checks pass.

T7-07 is complete locally. The coordinator now performs budgeted bounded dispatch for the dedicated Critic
and optional peers, validates all `CRITIQUE` outputs before pinned Critic-then-peer commits, dispatches sealed
`REVISE` contexts afterward, validates all response outputs and commits them by stable target/responder order.
Runtime-owned response IDs, duplicate response/head rejection, complete execution attribution semantics and
ordered timeout abstention events are explicit. The deterministic handoff returns every latest Critique head with no omit path and
distinguishes no Critic run from a completed empty Critic run. Unsupported Claims produce `EVIDENCE_GAP`;
the deprecated `UNSUPPORTED_CLAIM` alias remains rejected. Evidence is 49 focused and 607 offline tests,
clean Ruff/format and strict mypy over 248 app/test files, compileall, and one passing disposable-PostgreSQL
handoff integration. No public HTTP API changed.

T7-08 and Phase 7 are complete. The final exit covered 82 focused and 677 non-integration tests, all 52
live integration tests against a clean disposable Compose/PostgreSQL stack, Alembic head
`20260911_0021`, migration drift, backend/frontend quality, contracts, generated traceability, links,
whitespace, and anti-pattern review. Docker Hub removed the pinned MinIO repositories during exact-SHA
verification, so the same pinned MinIO server/client manifests were moved to their canonical Quay paths.
GitHub Actions run [34667037521](https://github.com/potatosaladz/agora/actions/runs/34667037521)
passed all six jobs for exact SHA `25914b48e1c5140279720d1a4dfb66483cf744a3`.

Phase 8 T8-00 through T8-05 are complete on `phase8-simulation`. Simulation domain types are split across
layers: port-level `SimulationSpec`, `SimulationResult`, enums (`EngineKind`, `ConvergenceStatus`,
`SimulationFailureCode`, `NetworkPolicy`) and value objects (`DistributionSpec`, `ParameterSpec`,
`ScenarioOverride`, `SimulationHorizon`, `RunBudget`, `SensitivityEntry`, `ResourceUsage`,
`SimulationResultVariable`, `ValidationCheck`, `ValidationReport`) live in `app/ports/simulation.py` using
a local `_Frozen` base class that mirrors `FrozenModel` without cross-layer imports. Domain adds `RunStatus`,
`SimulationRunRecord`, and `SimulationRunStore` protocol. `SimulationEngine` and `SandboxExecutionProvider`
port protocols define the engine lifecycle and sandbox execution boundary. `SimulationOrchestrator` in the
application layer coordinates request → validate → run → rank sensitivity → store with proper error handling
(`TimeoutError` → `TIMEOUT`, generic → `FAILED`). `compute_sensitivity_ranks()` is a pure function ranking
by descending absolute index. Alembic migration `20260909_0020` creates `simulation_runs` and
`simulation_results` tables with forced RLS, CHECK constraints, and indexes. Content-addressed
`spec_content_hash` uses `_canonical_json` in-ports with no external dependency. Evidence is 36 new contract
tests (76 total with existing contracts + layering), all passing. Phase 8 is merged to `master` at `77dbf01`.

Phase 9 T9-01 through T9-06 are complete and merged to `master` at `b95f24b`. `backend/app/ports/consensus.py`
defines `ConsensusContext`, `ConsensusResult`, `ConsensusExplanation` and every supporting value object
(`AgentPosition`, `EvidenceCitationInput`, `ObjectiveInput`, `DissentEntry`, `MinorityEntry`,
`FeasibilityVerdict`, `StrategyConfig`) behind the `ConsensusStrategy`/`ConvergenceStrategy` protocols, plus
the eight-member `ConsensusOutcome` enum required by FR-604. `backend/app/domain/consensus.py` adds the
shared `feasibility_gate()` — implemented once, not per strategy — so an infeasible alternative can never be
ranked regardless of score (FR-602, FR-603), plus `ConsensusRunRecord` and `ConsensusResultStore` persistence
contracts. `backend/app/application/consensus.py` implements `WeightedStrategy` (deterministic linear
aggregation), `EvidenceWeightedStrategy` (support weighted by verified evidence strength) and
`ConstraintAwareStrategy` (feasibility-gated lexicographic, MVP default) exactly per their worked examples in
`docs/consensus-formalism/`, plus `StrategyRegistry` (refuses an unregistered or undocumented strategy per
FR-608/S-1) and `ConsensusOrchestrator` (resolves a strategy, evaluates it, persists result and explanation).
Every result carries a minority report of dissenting/abstaining agents that cannot be suppressed through the
API (FR-505, FR-506). Evidence is 13 new unit tests in `backend/tests/unit/test_consensus.py` covering the
three worked examples, registry rejection paths and orchestrator persistence; 620 tests pass total with 43
pre-existing unrelated skips, and Ruff/mypy are clean.

Phase 10 T10-01 is complete locally on `phase10-reasoning-graph`. `ReasoningGraphStore` now exposes
`trace_backward`, `trace_forward`, and bidirectional `subgraph` reads implemented by tenant/session-scoped,
cycle-safe recursive PostgreSQL CTEs. Trace depth is bounded at 12; subgraph radius defaults to 2 and is
capped at 5. Results are UUID-stable and use opaque query-bound cursor pagination (100 default, 200 maximum),
with `truncated` reserved for hidden depth-reachable members and `next_cursor` for remaining page members.
Unit and live PostgreSQL coverage proves cycles, depth-zero/truncation, edge filtering, radius, isolation,
lossless deterministic paging, and cursor-query binding. The cumulative migration assertion now follows the
actual `20260909_0020` head and includes Phase 8 tables; missing simulation ORM metadata and the invalid
`session_agents.id` foreign key in that inherited migration were repaired so clean upgrades and `alembic
check` pass.

T10-02 is complete. `GET /api/v1/artifacts/{artifact_id}/provenance` composes the bounded, cycle-safe
backward graph traversal with canonical artifact and citation stores, preserving exact edge semantics and
pagination metadata while surfacing evidence verification and current source status. The acceptance fixture
now gives its two chunks distinct content hashes and matching source references, preserving the production
uniqueness and exact-provenance invariants. On implementation SHA
`e86e9ca24c06b8139a35d510a3c36b372f3499be`, `uv run pytest
tests/integration/test_citation_retraction_persistence.py -q -rs` passed 1 test in 2.98 seconds against a
fresh `pgvector/pgvector:pg16` container with database/user `agora_test`, a random loopback host port, a
generated password, and a subprocess-only `TEST_DATABASE_URL`; no persistent volume was used and the
container was removed. The focused provenance suite passed 5 tests; focused Ruff/format, 65-row
traceability, and whitespace checks are green.
